"""
Water Rocket Ground Station GUI v2
====================================
Connects to the ground receiver over USB serial, parses telemetry
packets, and displays real-time flight data with live graphs.

Features:
  - Live telemetry from flight firmware (F packets) or data collector (D packets)
  - CSV recording for post-flight analysis
  - RSSI signal quality graph
  - Peak value tracking (max alt, max accel, max velocity)
  - Audio alerts on flight state changes
  - Gyro display in data-collector mode
  - Flight replay from saved CSV files
  - Multi-flight overlay for comparison
  - Pre-launch checklist (battery, continuity, temperature)

Usage:
  pip install pyserial matplotlib
  python ground_station.py
"""

import sys
import os
import json
import random
import threading
import time
import csv
import math
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
from collections import deque
from datetime import datetime

import serial
import serial.tools.list_ports
import matplotlib
matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

# Windows audio support (optional)
try:
    import winsound
    HAS_AUDIO = True
except ImportError:
    HAS_AUDIO = False

# ── Constants ──────────────────────────────────────────────────
STATE_NAMES = {
    0: "IDLE", 1: "READY", 2: "ARMED", 3: "BOOST",
    4: "COAST", 5: "DESCENT", 6: "LANDED", 7: "FAULT",
}
STATE_COLORS = {
    0: "#888888", 1: "#2196F3", 2: "#FF9800", 3: "#F44336",
    4: "#9C27B0", 5: "#4CAF50", 6: "#00BCD4", 7: "#F44336",
}

HISTORY_LEN = 1200          # ~2 min at 10 Hz
OVERLAY_COLORS = ["#ff00ff", "#ffff00", "#00ffff", "#ff8888"]

# Event severity levels
SEV_INFO = "INFO"
SEV_WARN = "WARN"
SEV_FAULT = "FAULT"
SEV_COLORS = {SEV_INFO: "#88aaff", SEV_WARN: "#ff8800", SEV_FAULT: "#ff4444"}

# Fault detection thresholds
STALE_TIMEOUT_S = 3.0       # no packet for this long -> stale warning
MAX_ALT_JUMP_M = 200.0      # single-step altitude delta > this -> fault
MAX_ACCEL_G = 50.0          # accel > this -> fault (realistic water rocket << 30g)
MIN_PRES_HPA = 300.0        # pressure below this is impossible at ground
MAX_ALT_ABS_M = 3000.0      # no water rocket goes this high

# Signal-quality gates: when the link is marginal, corrupted bytes can still
# parse into a "valid" packet with garbage numbers. These thresholds drop
# packets that are clearly unreliable before they reach graphs/history.
MIN_VALID_RSSI_DBM = -120   # weaker than this -> ignore packet
MAX_VALID_RSSI_DBM = 0      # positive RSSI usually means bogus byte
MAX_VEL_MS = 120.0          # water rocket: well under sound
MAX_ALT_STEP_M = 150.0      # single-sample alt jump that is guaranteed fake

# Unit conversion
FT_PER_M = 3.28084

# Default config
DEFAULT_CONFIG = {
    "launch_detect_g": 2.0,
    "apogee_filter_samples": 5,
    "landing_detect_m": 2.0,
    "telemetry_rate_hz": 10,
    "logging_rate_hz": 20,
    "buzzer_enable": True,
    "sim_mode": False,
    "units": "m",           # "m" or "ft"
    "view_mode": "operator",  # "operator" or "debug"
    "min_rssi_dbm": MIN_VALID_RSSI_DBM,
    "reject_garbage": True,
}

CSV_HEADER = [
    "utc", "elapsed_s", "type", "rssi", "snr", "state",
    "alt", "max_alt", "vel", "accel", "pyro", "safe",
    "vbat", "cont1", "cont2", "temp",
    "ax", "ay", "az", "gx", "gy", "gz", "pres_hpa",
]


# ── Telemetry record ──────────────────────────────────────────
class Telemetry:
    __slots__ = (
        "time_s", "state", "alt", "max_alt", "accel", "vel", "pyro",
        "rssi", "snr", "remote_safe", "packet_type",
        "ax", "ay", "az", "gx", "gy", "gz",
        "temp_c", "pres_hpa", "vbat", "cont1", "cont2", "arm",
    )

    def __init__(self):
        self.time_s = 0.0;  self.state = 0
        self.alt = 0.0;     self.max_alt = 0.0
        self.accel = 0.0;   self.vel = 0.0
        self.pyro = False;  self.rssi = 0;  self.snr = 0.0
        self.remote_safe = False;  self.packet_type = "F"
        self.ax = 0.0; self.ay = 0.0; self.az = 0.0
        self.gx = 0.0; self.gy = 0.0; self.gz = 0.0
        self.temp_c = 0.0; self.pres_hpa = 0.0; self.vbat = 0.0
        self.cont1 = 0; self.cont2 = 0; self.arm = 0

    def to_csv_row(self, elapsed: float) -> list:
        return [
            datetime.utcnow().isoformat(), f"{elapsed:.3f}",
            self.packet_type, self.rssi, self.snr, self.state,
            self.alt, self.max_alt, self.vel, self.accel,
            int(self.pyro), int(self.remote_safe),
            self.vbat, self.cont1, self.cont2, self.temp_c,
            self.ax, self.ay, self.az, self.gx, self.gy, self.gz,
            self.pres_hpa,
        ]


def parse_line(line: str) -> "Telemetry | None":
    """Parse ground-receiver line into Telemetry.

    Handles:
      R,rssi,snr,F,...   (flight via receiver)
      R,rssi,snr,D,...   (data-collector via receiver)
      F,...  or  D,...    (raw)
    """
    parts = line.strip().split(",")
    t = Telemetry()
    try:
        if parts[0] == "R" and len(parts) >= 6:
            t.rssi = int(parts[1])
            t.snr = float(parts[2])
            fp = parts[3:]
        elif parts[0] in ("F", "D"):
            fp = parts
        else:
            return None

        # Flight: F,ms,st,alt,max,acc,vel,pyro,safe[,vbat,c1,c2,temp]
        if fp[0] == "F" and len(fp) >= 6:
            t.packet_type = "F"
            t.time_s = int(fp[1]) / 1000.0
            t.state  = int(fp[2])
            t.alt    = float(fp[3])
            t.max_alt = float(fp[4])
            t.accel  = float(fp[5])
            t.vel    = float(fp[6]) if len(fp) > 6 else 0.0
            t.pyro   = int(fp[7])   if len(fp) > 7 else 0
            t.remote_safe = bool(int(fp[8])) if len(fp) > 8 else False
            # Extended fields (v2 firmware)
            t.vbat   = float(fp[9])  if len(fp) > 9  else 0.0
            t.cont1  = int(fp[10])   if len(fp) > 10 else 0
            t.cont2  = int(fp[11])   if len(fp) > 11 else 0
            t.temp_c = float(fp[12]) if len(fp) > 12 else 0.0
            # Gyro body-frame rates (°/s) — added in flight_v3 gyro upgrade
            t.gx = float(fp[13]) if len(fp) > 13 else 0.0
            t.gy = float(fp[14]) if len(fp) > 14 else 0.0
            t.gz = float(fp[15]) if len(fp) > 15 else 0.0
            return t

        # Data: D,seq,ax,ay,az,gx,gy,gz,temp,pres,alt,vbat,c1,c2,arm
        if fp[0] == "D" and len(fp) >= 11:
            t.packet_type = "D"
            t.time_s  = int(fp[1]) * 0.5
            t.ax = float(fp[2]);  t.ay = float(fp[3]);  t.az = float(fp[4])
            t.gx = float(fp[5]);  t.gy = float(fp[6]);  t.gz = float(fp[7])
            t.temp_c  = float(fp[8])
            t.pres_hpa = float(fp[9])
            t.alt     = float(fp[10])
            t.vbat    = float(fp[11]) if len(fp) > 11 else 0.0
            t.cont1   = int(fp[12])   if len(fp) > 12 else 0
            t.cont2   = int(fp[13])   if len(fp) > 13 else 0
            t.arm     = int(fp[14])   if len(fp) > 14 else 0
            t.accel   = math.sqrt(t.ax**2 + t.ay**2 + t.az**2)
            t.vel = 0.0;  t.max_alt = t.alt;  t.state = 0
            t.pyro = False;  t.remote_safe = False
            return t

        return None
    except (ValueError, IndexError):
        return None


# ── Audio alerts ───────────────────────────────────────────────
def _beep_thread(pattern: list[tuple[int, int]]):
    """Play a sequence of (freq_hz, duration_ms) beeps in a thread."""
    if not HAS_AUDIO:
        return
    def _play():
        for freq, ms in pattern:
            try:
                if freq == 0:
                    time.sleep(ms / 1000.0)
                else:
                    winsound.Beep(freq, ms)
            except Exception:
                pass
    threading.Thread(target=_play, daemon=True).start()

ALERT_PATTERNS = {
    "armed":   [(800, 200), (0, 80), (800, 200)],
    "launch":  [(1000, 150), (1200, 150), (1500, 300)],
    "apogee":  [(1500, 200), (0, 80), (2000, 300)],
    "landed":  [(2000, 100), (2500, 100), (3000, 200)],
    "fault":   [(400, 400), (0, 100), (400, 400)],
}


# ── Serial reader thread ──────────────────────────────────────
class SerialReader:
    def __init__(self):
        self.ser = None
        self.thread = None
        self.running = False
        self.lock = threading.Lock()
        self.queue: deque[Telemetry] = deque(maxlen=64)
        self.raw_log: deque[str] = deque(maxlen=200)
        self.packet_count = 0

    def connect(self, port: str, baud: int = 115200):
        try:
            self.ser = serial.Serial(port, baud, timeout=0.1)
            self.running = True
            self.packet_count = 0
            self.thread = threading.Thread(target=self._read_loop, daemon=True)
            self.thread.start()
            return None
        except serial.SerialException as e:
            return str(e)

    def disconnect(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=2)
        if self.ser and self.ser.is_open:
            self.ser.close()
        self.ser = None

    @property
    def connected(self) -> bool:
        return self.ser is not None and self.ser.is_open and self.running

    def drain(self):
        with self.lock:
            items = list(self.queue)
            self.queue.clear()
        return items

    def send_command(self, cmd: str) -> bool:
        if not self.connected:
            return False
        try:
            self.ser.write((cmd + "\n").encode("utf-8"))
            self.ser.flush()
            return True
        except serial.SerialException:
            return False

    def drain_log(self):
        with self.lock:
            items = list(self.raw_log)
            self.raw_log.clear()
        return items

    def _read_loop(self):
        while self.running:
            try:
                if not self.ser or not self.ser.is_open:
                    break
                raw = self.ser.readline()
                if not raw:
                    continue
                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                with self.lock:
                    self.raw_log.append(line)
                t = parse_line(line)
                if t:
                    self.packet_count += 1
                    with self.lock:
                        self.queue.append(t)
            except serial.SerialException:
                break
            except Exception:
                continue
        self.running = False


# ── Event log ──────────────────────────────────────────────────
class EventLog:
    """Structured event log with timestamp / source / severity / message."""

    def __init__(self, maxlen: int = 1000):
        self.events: deque[dict] = deque(maxlen=maxlen)
        self.lock = threading.Lock()
        self._start = time.monotonic()

    def add(self, severity: str, source: str, message: str):
        ev = {
            "t_wall": datetime.now().strftime("%H:%M:%S"),
            "t_mission": time.monotonic() - self._start,
            "severity": severity,
            "source": source,
            "message": message,
        }
        with self.lock:
            self.events.append(ev)
        return ev

    def reset_mission_time(self):
        self._start = time.monotonic()

    def list(self, min_severity: str | None = None) -> list[dict]:
        with self.lock:
            evs = list(self.events)
        if min_severity is None:
            return evs
        order = {SEV_INFO: 0, SEV_WARN: 1, SEV_FAULT: 2}
        thresh = order.get(min_severity, 0)
        return [e for e in evs if order.get(e["severity"], 0) >= thresh]

    def clear(self):
        with self.lock:
            self.events.clear()

    def export_csv(self, path: str):
        with self.lock:
            evs = list(self.events)
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["wall_time", "mission_s", "severity", "source", "message"])
            for e in evs:
                w.writerow([e["t_wall"], f"{e['t_mission']:.3f}",
                            e["severity"], e["source"], e["message"]])


# ── Preflight checklist ────────────────────────────────────────
class PreflightChecklist:
    """Named checks, each required or optional, auto or manual.

    `all_required_passed()` gates the ARM action.
    """

    def __init__(self):
        # key: (label, required, manual, status, bypassed)
        # status: None=unknown, True/False  |  bypassed: locks status to True
        self.items: dict[str, dict] = {
            "radio":       {"label": "Radio link active",      "required": True,  "manual": False, "status": None, "bypassed": False},
            "packets":     {"label": "Telemetry updating",     "required": True,  "manual": False, "status": None, "bypassed": False},
            "battery":     {"label": "Battery voltage >= 7.0V","required": True,  "manual": False, "status": None, "bypassed": False},
            "cont1":       {"label": "Pyro 1 continuity",      "required": True,  "manual": False, "status": None, "bypassed": False},
            "cont2":       {"label": "Pyro 2 continuity",      "required": True,  "manual": False, "status": None, "bypassed": False},
            "sensors":     {"label": "Sensors producing data", "required": True,  "manual": False, "status": None, "bypassed": False},
            "sd":          {"label": "SD card writable",       "required": False, "manual": True,  "status": None, "bypassed": False},
            "zero_alt":    {"label": "Zero-altitude calibrated","required": True, "manual": True,  "status": None, "bypassed": False},
            "ground_pres": {"label": "Ground pressure set",    "required": False, "manual": True,  "status": None, "bypassed": False},
            "rocket_ok":   {"label": "Rocket visually OK",     "required": True,  "manual": True,  "status": None, "bypassed": False},
            "pad_clear":   {"label": "Pad area clear",         "required": True,  "manual": True,  "status": None, "bypassed": False},
            "fill":        {"label": "Water/pressure set",     "required": True,  "manual": True,  "status": None, "bypassed": False},
        }

    def set_manual(self, key: str, ok: bool):
        if key in self.items:
            self.items[key]["bypassed"] = ok
            self.items[key]["status"] = True if ok else self.items[key]["status"]

    def update_auto(self, connected: bool, pkt_count: int, last_pkt_age: float,
                    t: "Telemetry | None"):
        def _set(key, val):
            if not self.items[key]["bypassed"]:
                self.items[key]["status"] = val

        _set("radio", connected and last_pkt_age < STALE_TIMEOUT_S)
        _set("packets", pkt_count > 5 and last_pkt_age < STALE_TIMEOUT_S)
        if t is None:
            for k in ("battery", "cont1", "cont2", "sensors"):
                _set(k, None)
            return
        _set("battery", t.vbat >= 7.0 if t.vbat > 0 else None)
        _set("cont1", (200 < t.cont1 < 3800) if t.cont1 else None)
        _set("cont2", (200 < t.cont2 < 3800) if t.cont2 else None)
        _set("sensors", (t.temp_c != 0 or t.pres_hpa != 0
                         or t.alt != 0 or t.accel != 0))

    def all_required_passed(self) -> bool:
        for it in self.items.values():
            if it["required"] and it["status"] is not True:
                return False
        return True

    def summary(self) -> tuple[int, int]:
        required = [it for it in self.items.values() if it["required"]]
        passed = sum(1 for it in required if it["status"] is True)
        return passed, len(required)


# ── Simulation source ─────────────────────────────────────────
class SimulationSource:
    """Generates a canned nominal water-rocket flight profile."""

    def __init__(self):
        self.t0 = time.monotonic()
        self.max_alt_seen = 0.0
        self.seq = 0

    def reset(self):
        self.t0 = time.monotonic()
        self.max_alt_seen = 0.0
        self.seq = 0

    def get_packet(self) -> "Telemetry | None":
        t_s = time.monotonic() - self.t0
        self.seq += 1

        # Profile: 0-3s idle, 3-3.5s boost, 3.5-6s coast to apogee ~40m,
        # 6-10s descent, 10s+ landed
        if t_s < 3.0:
            state, alt, vel, acc = 1, 0.0, 0.0, 1.0   # READY
        elif t_s < 3.5:
            frac = (t_s - 3.0) / 0.5
            state = 3                                   # BOOST
            acc = 12.0 + random.uniform(-1, 1)
            vel = frac * 28.0
            alt = 0.5 * vel * frac * 0.5
        elif t_s < 6.0:
            state = 4                                   # COAST
            v_apogee_t = 6.0
            vel = 28.0 - 9.81 * (t_s - 3.5)
            alt = 28.0 * (t_s - 3.5) - 0.5 * 9.81 * (t_s - 3.5) ** 2 + 7.0
            acc = 1.0 + random.uniform(-0.2, 0.2)
        elif t_s < 10.0:
            state = 5                                   # DESCENT
            vel = -5.0 + random.uniform(-0.5, 0.5)
            dt = t_s - 6.0
            alt = max(0.0, 40.0 - 5.0 * dt)
            acc = 1.0 + random.uniform(-0.3, 0.3)
        else:
            state, alt, vel, acc = 6, 0.0, 0.0, 1.0     # LANDED

        alt += random.uniform(-0.2, 0.2)
        self.max_alt_seen = max(self.max_alt_seen, alt)

        t = Telemetry()
        t.packet_type = "F"
        t.time_s = t_s
        t.state = state
        t.alt = alt
        t.max_alt = self.max_alt_seen
        t.accel = acc
        t.vel = vel
        t.pyro = state == 5 and t_s < 6.5
        t.remote_safe = False
        t.rssi = -60 + random.randint(-5, 5)
        t.snr = 10.0 + random.uniform(-2, 2)
        t.vbat = 8.1 + random.uniform(-0.05, 0.05)
        t.cont1 = 1500
        t.cont2 = 1500
        t.temp_c = 22.0 + random.uniform(-0.5, 0.5)
        t.pres_hpa = 1013.0 - alt * 0.12

        # Body-frame accel/gyro for orientation display
        if state == 3:          # BOOST: wobble
            t.ax = random.uniform(-2, 2)
            t.ay = random.uniform(-2, 2)
            t.az = 1.0
            t.gx = random.uniform(-20, 20)
            t.gy = random.uniform(-20, 20)
            t.gz = random.uniform(-10, 10)
        elif state == 4:        # COAST: near-zero accel (freefall-ish), slow spin
            t.ax = random.uniform(-0.1, 0.1)
            t.ay = random.uniform(-0.1, 0.1)
            t.az = random.uniform(-0.1, 0.1)
            t.gx = random.uniform(-5, 5)
            t.gy = random.uniform(-5, 5)
            t.gz = 30.0 + random.uniform(-5, 5)
        elif state == 5:        # DESCENT: tumble
            t.ax = random.uniform(-0.4, 0.4)
            t.ay = random.uniform(-0.4, 0.4)
            t.az = 1.0 + random.uniform(-0.3, 0.3)
            t.gx = random.uniform(-60, 60)
            t.gy = random.uniform(-60, 60)
            t.gz = random.uniform(-40, 40)
        else:                    # IDLE / READY / LANDED: stationary (~1g z)
            t.ax = random.uniform(-0.02, 0.02)
            t.ay = random.uniform(-0.02, 0.02)
            t.az = 1.0 + random.uniform(-0.02, 0.02)
            t.gx = random.uniform(-0.5, 0.5)
            t.gy = random.uniform(-0.5, 0.5)
            t.gz = random.uniform(-0.5, 0.5)
        return t


# ── Fault detector ────────────────────────────────────────────
class FaultDetector:
    """Detects impossible / suspicious values and raises events."""

    def __init__(self, events: EventLog):
        self.events = events
        self.last_alt: float | None = None
        self.last_fault_ts: dict[str, float] = {}

    def reset(self):
        self.last_alt = None
        self.last_fault_ts.clear()

    def _throttle(self, key: str, min_gap: float = 2.0) -> bool:
        now = time.monotonic()
        if now - self.last_fault_ts.get(key, 0) < min_gap:
            return False
        self.last_fault_ts[key] = now
        return True

    def check(self, t: "Telemetry"):
        if t.alt > MAX_ALT_ABS_M and self._throttle("alt_abs"):
            self.events.add(SEV_FAULT, "fault",
                            f"Absurd altitude {t.alt:.0f} m (>{MAX_ALT_ABS_M:.0f})")
        if self.last_alt is not None:
            jump = abs(t.alt - self.last_alt)
            if jump > MAX_ALT_JUMP_M and self._throttle("alt_jump"):
                self.events.add(SEV_FAULT, "fault",
                                f"Altitude jump {jump:.0f} m between samples")
        self.last_alt = t.alt

        if t.accel > MAX_ACCEL_G and self._throttle("accel"):
            self.events.add(SEV_FAULT, "fault",
                            f"Accel spike {t.accel:.1f} g (>{MAX_ACCEL_G:.0f})")
        if 0 < t.pres_hpa < MIN_PRES_HPA and self._throttle("pres_low"):
            self.events.add(SEV_FAULT, "fault",
                            f"Pressure {t.pres_hpa:.0f} hPa implausible")
        if t.vbat > 0 and t.vbat < 6.5 and self._throttle("vbat_low"):
            self.events.add(SEV_WARN, "fault",
                            f"Battery voltage low: {t.vbat:.2f} V")


# ── GUI ────────────────────────────────────────────────────────
class GroundStationApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Water Rocket Ground Station")
        self.root.configure(bg="#1a1a2e")
        self.root.geometry("1120x940")
        self.root.minsize(960, 780)

        self.reader = SerialReader()

        # History buffers
        self.t_hist    = deque(maxlen=HISTORY_LEN)
        self.alt_hist  = deque(maxlen=HISTORY_LEN)
        self.vel_hist  = deque(maxlen=HISTORY_LEN)
        self.acc_hist  = deque(maxlen=HISTORY_LEN)
        self.rssi_hist = deque(maxlen=HISTORY_LEN)
        self.gyro_hist = deque(maxlen=HISTORY_LEN)
        self.t_offset  = None

        self.last_telem = None
        self._current_mode = None
        self._prev_state = None        # for audio alerts
        self._graph_counter = 0

        # Peak tracking
        self.peak_alt   = 0.0
        self.peak_accel = 0.0
        self.peak_vel   = 0.0

        # CSV recording
        self._recording = False
        self._csv_file  = None
        self._csv_writer = None
        self._csv_path  = None

        # Overlay data
        self._overlays = {}  # {filename: (t_list, alt_list, vel_list, acc_list)}
        self._overlay_lines = []

        # New subsystems
        self.events = EventLog()
        self.preflight = PreflightChecklist()
        self.fault_detector = FaultDetector(self.events)
        self.sim_source = SimulationSource()
        self.config = dict(DEFAULT_CONFIG)

        # Runtime state
        self._last_packet_ts = 0.0     # monotonic of last received packet
        self._stale = False
        self._graph_paused = False
        self._mission_name = ""
        self._mission_notes = ""
        self._mission_folder: str | None = None
        self._apogee_marker = None
        self._apogee_announced = False
        self._launch_ts: float | None = None
        self._landed_ts: float | None = None
        self._last_sim_ts = 0.0

        self._filtered_count = 0  # packets dropped by signal-quality gate
        self._dropped_total = 0   # cumulative packets dropped (gap detection)
        self.events.add(SEV_INFO, "system", "Ground station started")

        self._build_ui()
        self._tick()

    # ── Signal-quality gate ─────────────────────────────────────
    def _is_packet_valid(self, t: "Telemetry") -> tuple[bool, str]:
        """Return (ok, reason). Drops packets that are almost certainly
        corrupted bytes from a weak/dying link."""
        if not self.config.get("reject_garbage", True):
            return True, ""
        # Sim packets bypass the filter (they're clean by construction)
        if self.config.get("sim_mode"):
            return True, ""
        min_rssi = self.config.get("min_rssi_dbm", MIN_VALID_RSSI_DBM)
        if t.rssi != 0:   # only check if we actually have an RSSI reading
            if t.rssi < min_rssi:
                return False, f"RSSI {t.rssi} below {min_rssi}"
            if t.rssi > MAX_VALID_RSSI_DBM:
                return False, f"RSSI {t.rssi} positive (bogus)"
        if abs(t.alt) > MAX_ALT_ABS_M:
            return False, f"alt {t.alt:.0f} m impossible"
        if abs(t.vel) > MAX_VEL_MS:
            return False, f"vel {t.vel:.1f} m/s impossible"
        if t.accel > MAX_ACCEL_G * 2:
            return False, f"accel {t.accel:.1f} g impossible"
        if t.pres_hpa != 0 and t.pres_hpa < MIN_PRES_HPA / 2:
            return False, f"pressure {t.pres_hpa:.0f} hPa impossible"
        # Cross-packet step check
        if self.last_telem and self.last_telem.packet_type == t.packet_type:
            if abs(t.alt - self.last_telem.alt) > MAX_ALT_STEP_M:
                return False, (
                    f"alt step {t.alt - self.last_telem.alt:.0f} m too large")
        return True, ""

    # ── UI construction ──────────────────────────────────────────
    def _build_ui(self):
        s = ttk.Style()
        s.theme_use("clam")
        s.configure("Title.TLabel",  background="#1a1a2e", foreground="#e0e0e0",
                     font=("Consolas", 16, "bold"))
        s.configure("Dark.TFrame",   background="#1a1a2e")
        s.configure("Card.TFrame",   background="#16213e")
        s.configure("Val.TLabel",    background="#16213e", foreground="#00ff88",
                     font=("Consolas", 22, "bold"))
        s.configure("Unit.TLabel",   background="#16213e", foreground="#888888",
                     font=("Consolas", 10))
        s.configure("Lbl.TLabel",    background="#16213e", foreground="#aaaaaa",
                     font=("Consolas", 10))
        s.configure("Status.TLabel", background="#1a1a2e", foreground="#888888",
                     font=("Consolas", 10))
        s.configure("Peak.TLabel",   background="#1a1a2e", foreground="#666666",
                     font=("Consolas", 9))
        s.configure("Check.TLabel",  background="#1a1a2e", foreground="#aaaaaa",
                     font=("Consolas", 10))
        s.configure("Banner.TLabel", background="#222244", foreground="#ffffff",
                     font=("Consolas", 28, "bold"), anchor="center")
        s.configure("SubBanner.TLabel", background="#222244", foreground="#aaaaaa",
                     font=("Consolas", 11))
        s.configure("TNotebook", background="#1a1a2e", borderwidth=0)
        s.configure("TNotebook.Tab", background="#16213e", foreground="#cccccc",
                     padding=(14, 6), font=("Consolas", 10, "bold"))
        s.map("TNotebook.Tab",
              background=[("selected", "#2a3a6e")],
              foreground=[("selected", "#ffffff")])

        # ── Menu bar ──
        menubar = tk.Menu(self.root)
        filemenu = tk.Menu(menubar, tearoff=0)
        filemenu.add_command(label="Load Flight CSV...", command=self._load_flight)
        filemenu.add_command(label="Load Overlay...", command=self._load_overlay)
        filemenu.add_command(label="Clear Overlays", command=self._clear_overlays)
        filemenu.add_separator()
        filemenu.add_command(label="Export Events CSV...", command=self._export_events)
        filemenu.add_separator()
        filemenu.add_command(label="Exit", command=lambda: (
            self._stop_recording(), self.reader.disconnect(), self.root.destroy()))
        menubar.add_cascade(label="File", menu=filemenu)
        self.root.config(menu=menubar)

        # ── Giant status banner (always visible) ──
        banner = tk.Frame(self.root, bg="#222244", height=90)
        banner.pack(fill=tk.X, side=tk.TOP)
        banner.pack_propagate(False)
        self.banner_label = ttk.Label(banner, text="DISCONNECTED",
                                      style="Banner.TLabel")
        self.banner_label.pack(fill=tk.X, expand=True, padx=8, pady=(6, 0))
        self.banner_sub = ttk.Label(banner, text="No telemetry",
                                    style="SubBanner.TLabel", anchor="center")
        self.banner_sub.pack(fill=tk.X, padx=8, pady=(0, 6))

        # ── Notebook ──
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)
        self.notebook = notebook

        dash_tab = ttk.Frame(notebook, style="Dark.TFrame")
        preflight_tab = ttk.Frame(notebook, style="Dark.TFrame")
        events_tab = ttk.Frame(notebook, style="Dark.TFrame")
        review_tab = ttk.Frame(notebook, style="Dark.TFrame")
        settings_tab = ttk.Frame(notebook, style="Dark.TFrame")
        diag_tab = ttk.Frame(notebook, style="Dark.TFrame")
        notebook.add(dash_tab, text="Dashboard")
        notebook.add(preflight_tab, text="Preflight")
        notebook.add(events_tab, text="Events")
        notebook.add(review_tab, text="Review")
        notebook.add(settings_tab, text="Settings")
        notebook.add(diag_tab, text="Diagnostics")

        # Dashboard lives in dash_tab (existing layout below)
        main = ttk.Frame(dash_tab, style="Dark.TFrame")
        main.pack(fill=tk.BOTH, expand=True, padx=8, pady=6)

        self._preflight_tab = preflight_tab
        self._events_tab = events_tab
        self._review_tab = review_tab
        self._settings_tab = settings_tab
        self._diag_tab = diag_tab

        # ── Title ──
        ttk.Label(main, text="WATER ROCKET GROUND STATION",
                  style="Title.TLabel").pack(anchor=tk.W, padx=4)

        # ── Connection bar ──
        conn = ttk.Frame(main, style="Dark.TFrame")
        conn.pack(fill=tk.X, pady=(6, 3))

        ttk.Label(conn, text="Port:", style="Status.TLabel").pack(
            side=tk.LEFT, padx=(0, 4))
        self.port_var = tk.StringVar()
        self.port_combo = ttk.Combobox(
            conn, textvariable=self.port_var, width=16, state="readonly")
        self.port_combo.pack(side=tk.LEFT, padx=2)
        self._refresh_ports()

        ttk.Button(conn, text="Refresh", command=self._refresh_ports,
                   width=7).pack(side=tk.LEFT, padx=2)
        self.btn_connect = ttk.Button(
            conn, text="Connect", command=self._toggle_connect, width=9)
        self.btn_connect.pack(side=tk.LEFT, padx=2)
        self.conn_status = ttk.Label(conn, text="DISCONNECTED",
                                     style="Status.TLabel")
        self.conn_status.pack(side=tk.LEFT, padx=8)

        # Right side: record button, packet count, RSSI
        self.pkt_label = ttk.Label(conn, text="Packets: 0", style="Status.TLabel")
        self.pkt_label.pack(side=tk.RIGHT, padx=6)
        self.rssi_label = ttk.Label(conn, text="RSSI: -- dBm",
                                    style="Status.TLabel")
        self.rssi_label.pack(side=tk.RIGHT, padx=6)

        self.btn_record = tk.Button(
            conn, text="  RECORD  ", font=("Consolas", 10, "bold"),
            bg="#555555", fg="white", activebackground="#cc0000",
            relief=tk.RAISED, bd=2, command=self._toggle_record)
        self.btn_record.pack(side=tk.RIGHT, padx=6)

        # ── Button bar ──
        btn_frame = ttk.Frame(main, style="Dark.TFrame")
        btn_frame.pack(fill=tk.X, pady=3)

        def _mkbtn(parent, text, bg, cmd, w=12):
            return tk.Button(
                parent, text=text, font=("Consolas", 11, "bold"),
                bg=bg, fg="white", activeforeground="white",
                relief=tk.RAISED, bd=2, width=w, height=1, command=cmd)

        self.btn_safe = _mkbtn(btn_frame, "SAFE PYROS", "#cc0000", self._send_safe)
        self.btn_safe.pack(side=tk.LEFT, padx=3)
        self.btn_arm = _mkbtn(btn_frame, "RE-ARM", "#555555", self._send_arm)
        self.btn_arm.pack(side=tk.LEFT, padx=3)
        self.btn_reset = _mkbtn(btn_frame, "RESET", "#2196F3", self._reset_display)
        self.btn_reset.pack(side=tk.LEFT, padx=3)

        self.safe_status = ttk.Label(btn_frame, text="", style="Status.TLabel")
        self.safe_status.pack(side=tk.LEFT, padx=10)

        # ── Data cards ──
        cards = ttk.Frame(main, style="Dark.TFrame")
        cards.pack(fill=tk.X, pady=(4, 2))
        self.card_labels = {}
        self.state_label  = self._make_card(cards, "STATE",    "--",  "",    "state")
        self.alt_label    = self._make_card(cards, "ALTITUDE", "0.0", "m",   "alt")
        self.maxalt_label = self._make_card(cards, "MAX ALT",  "0.0", "m",   "maxalt")
        self.vel_label    = self._make_card(cards, "VELOCITY", "0.0", "m/s", "vel")
        self.accel_label  = self._make_card(cards, "ACCEL",    "0.0", "g",   "accel")
        self.pyro_label   = self._make_card(cards, "PYRO",     "SAFE","",    "pyro")

        # ── Peak values bar ──
        self.peak_label = ttk.Label(
            main, text="Peak:  Alt --  |  Vel --  |  Accel --  |  RSSI --",
            style="Peak.TLabel")
        self.peak_label.pack(fill=tk.X, padx=4, pady=(2, 1))

        # ── Pre-launch checklist bar ──
        self.checklist_label = ttk.Label(main, text="", style="Check.TLabel")
        self.checklist_label.pack(fill=tk.X, padx=4, pady=(1, 3))

        # ── Graphs (4 rows) ──
        graph_frame = ttk.Frame(main, style="Dark.TFrame")
        graph_frame.pack(fill=tk.BOTH, expand=True, pady=2)

        self.fig = Figure(figsize=(10, 5), facecolor="#0f0f1a")
        self.fig.subplots_adjust(
            hspace=0.55, left=0.07, right=0.97, top=0.96, bottom=0.05)

        self.ax_alt  = self.fig.add_subplot(4, 1, 1)
        self.ax_vel  = self.fig.add_subplot(4, 1, 2)
        self.ax_acc  = self.fig.add_subplot(4, 1, 3)
        self.ax_rssi = self.fig.add_subplot(4, 1, 4)

        graph_cfg = [
            (self.ax_alt,  "Alt (m)",     "#00ff88"),
            (self.ax_vel,  "Vel (m/s)",   "#ff8800"),
            (self.ax_acc,  "Accel (g)",   "#ff4444"),
            (self.ax_rssi, "RSSI (dBm)",  "#8888ff"),
        ]
        for ax, ylabel, color in graph_cfg:
            ax.set_facecolor("#0f0f1a")
            ax.set_ylabel(ylabel, color=color, fontsize=8)
            ax.tick_params(colors="#666666", labelsize=7)
            for sp in ax.spines.values():
                sp.set_color("#333333")
            ax.grid(True, color="#222222", linewidth=0.5)

        self.line_alt,  = self.ax_alt.plot([], [], color="#00ff88", lw=1.5)
        self.line_vel,  = self.ax_vel.plot([], [], color="#ff8800", lw=1.5)
        self.line_acc,  = self.ax_acc.plot([], [], color="#ff4444", lw=1.5)
        self.line_rssi, = self.ax_rssi.plot([], [], color="#8888ff", lw=1.2)

        self.canvas = FigureCanvasTkAgg(self.fig, master=graph_frame)
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        # ── Log panel ──
        log_frame = ttk.Frame(main, style="Dark.TFrame")
        log_frame.pack(fill=tk.X, pady=(3, 0))
        self.log_text = tk.Text(
            log_frame, height=4, bg="#0f0f1a", fg="#44ff44",
            font=("Consolas", 9), relief=tk.FLAT,
            insertbackground="#44ff44", state=tk.DISABLED, wrap=tk.NONE)
        log_scroll = ttk.Scrollbar(
            log_frame, orient=tk.VERTICAL, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scroll.set)
        log_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.log_text.pack(fill=tk.X, expand=False)

        # Pause button for graph freeze
        self.btn_pause = tk.Button(
            conn, text="  PAUSE  ", font=("Consolas", 10, "bold"),
            bg="#444444", fg="white", activebackground="#666666",
            relief=tk.RAISED, bd=2, command=self._toggle_pause)
        self.btn_pause.pack(side=tk.RIGHT, padx=6)

        # Build remaining tabs
        self._build_preflight_tab(self._preflight_tab)
        self._build_events_tab(self._events_tab)
        self._build_review_tab(self._review_tab)
        self._build_settings_tab(self._settings_tab)
        self._build_diag_tab(self._diag_tab)

    # ── Preflight tab ────────────────────────────────────────────
    def _build_preflight_tab(self, parent):
        title = ttk.Label(parent, text="PREFLIGHT CHECKLIST",
                          style="Title.TLabel")
        title.pack(anchor=tk.W, padx=8, pady=(8, 4))

        info = ttk.Label(
            parent,
            text="ARM is disabled until all REQUIRED checks pass. Click any item to bypass it.",
            style="Status.TLabel")
        info.pack(anchor=tk.W, padx=8, pady=(0, 8))

        # Bulk action bar
        bulk = tk.Frame(parent, bg="#1a1a2e")
        bulk.pack(fill=tk.X, padx=8, pady=(0, 6))
        tk.Button(bulk, text="BYPASS ALL", bg="#aa6600", fg="white",
                  font=("Consolas", 10, "bold"), relief=tk.RAISED, bd=2,
                  command=self._bypass_all).pack(side=tk.LEFT, padx=4)
        tk.Button(bulk, text="CLEAR ALL", bg="#444444", fg="white",
                  font=("Consolas", 10, "bold"), relief=tk.RAISED, bd=2,
                  command=self._clear_all_bypass).pack(side=tk.LEFT, padx=4)

        # Scrollable list of checks
        list_frame = tk.Frame(parent, bg="#1a1a2e")
        list_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        self._check_rows = {}  # key -> (status_label, button_or_none)

        for key, item in self.preflight.items.items():
            row = tk.Frame(list_frame, bg="#16213e", height=36)
            row.pack(fill=tk.X, pady=1)
            row.pack_propagate(False)

            # Status dot
            st_lbl = tk.Label(row, text=" ? ", bg="#16213e", fg="#888888",
                              font=("Consolas", 14, "bold"), width=4)
            st_lbl.pack(side=tk.LEFT, padx=(8, 4))

            req_tag = "[REQ]" if item["required"] else "[opt]"
            req_color = "#ff8800" if item["required"] else "#666666"
            tk.Label(row, text=req_tag, bg="#16213e", fg=req_color,
                     font=("Consolas", 9, "bold"), width=6).pack(side=tk.LEFT)

            tk.Label(row, text=item["label"], bg="#16213e", fg="#e0e0e0",
                     font=("Consolas", 11), anchor="w").pack(
                side=tk.LEFT, padx=8, fill=tk.X, expand=True)

            btn = tk.Button(
                row, text="Mark OK", bg="#2196F3", fg="white",
                font=("Consolas", 9, "bold"), relief=tk.RAISED, bd=1,
                command=lambda k=key: self._toggle_manual_check(k))
            btn.pack(side=tk.RIGHT, padx=8)

            self._check_rows[key] = (st_lbl, btn)

        # ARM / DISARM panel
        ctl = tk.Frame(parent, bg="#1a1a2e")
        ctl.pack(fill=tk.X, padx=8, pady=(12, 8))

        self.preflight_summary = tk.Label(
            ctl, text="Required passed: 0/0", bg="#1a1a2e", fg="#aaaaaa",
            font=("Consolas", 11, "bold"))
        self.preflight_summary.pack(side=tk.LEFT, padx=8)

        self.btn_arm_gated = tk.Button(
            ctl, text="ARM (gated)", font=("Consolas", 14, "bold"),
            bg="#333333", fg="#888888", relief=tk.RAISED, bd=3,
            width=16, height=2, state=tk.DISABLED,
            command=self._arm_with_confirm)
        self.btn_arm_gated.pack(side=tk.RIGHT, padx=8)

        self.btn_disarm = tk.Button(
            ctl, text="DISARM / SAFE", font=("Consolas", 14, "bold"),
            bg="#cc0000", fg="white", relief=tk.RAISED, bd=3,
            width=16, height=2, command=self._send_safe)
        self.btn_disarm.pack(side=tk.RIGHT, padx=8)

    # ── Events tab ──────────────────────────────────────────────
    def _build_events_tab(self, parent):
        title_bar = tk.Frame(parent, bg="#1a1a2e")
        title_bar.pack(fill=tk.X, padx=8, pady=(8, 4))
        ttk.Label(title_bar, text="EVENT LOG", style="Title.TLabel").pack(
            side=tk.LEFT)

        self.ev_filter = tk.StringVar(value="ALL")
        for lbl, val, color in [("ALL", "ALL", "#aaaaaa"),
                                ("INFO+", SEV_INFO, "#88aaff"),
                                ("WARN+", SEV_WARN, "#ff8800"),
                                ("FAULT", SEV_FAULT, "#ff4444")]:
            tk.Radiobutton(title_bar, text=lbl, value=val,
                           variable=self.ev_filter, bg="#1a1a2e",
                           fg=color, selectcolor="#1a1a2e",
                           activebackground="#1a1a2e",
                           activeforeground=color,
                           font=("Consolas", 9, "bold"),
                           command=self._refresh_events).pack(
                side=tk.RIGHT, padx=4)

        tk.Button(title_bar, text="Clear", bg="#555555", fg="white",
                  font=("Consolas", 9, "bold"),
                  command=self._clear_events).pack(side=tk.RIGHT, padx=4)
        tk.Button(title_bar, text="Export", bg="#2196F3", fg="white",
                  font=("Consolas", 9, "bold"),
                  command=self._export_events).pack(side=tk.RIGHT, padx=4)

        body = tk.Frame(parent, bg="#0f0f1a")
        body.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)

        self.events_text = tk.Text(
            body, bg="#0f0f1a", fg="#dddddd", font=("Consolas", 10),
            relief=tk.FLAT, wrap=tk.NONE, state=tk.DISABLED)
        scroll = ttk.Scrollbar(body, orient=tk.VERTICAL,
                               command=self.events_text.yview)
        self.events_text.configure(yscrollcommand=scroll.set)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.events_text.pack(fill=tk.BOTH, expand=True)

        for sev, color in SEV_COLORS.items():
            self.events_text.tag_configure(sev, foreground=color)

    # ── Review tab ──────────────────────────────────────────────
    def _build_review_tab(self, parent):
        top = tk.Frame(parent, bg="#1a1a2e")
        top.pack(fill=tk.X, padx=8, pady=(8, 4))
        ttk.Label(top, text="FLIGHT REVIEW", style="Title.TLabel").pack(
            side=tk.LEFT)
        tk.Button(top, text="Load CSV...", bg="#2196F3", fg="white",
                  font=("Consolas", 10, "bold"),
                  command=self._load_flight).pack(side=tk.RIGHT, padx=4)
        tk.Button(top, text="Load Overlay...", bg="#555555", fg="white",
                  font=("Consolas", 10, "bold"),
                  command=self._load_overlay).pack(side=tk.RIGHT, padx=4)
        tk.Button(top, text="Clear Overlays", bg="#555555", fg="white",
                  font=("Consolas", 10, "bold"),
                  command=self._clear_overlays).pack(side=tk.RIGHT, padx=4)

        # Summary panel
        self.review_summary = tk.Label(
            parent, text="No flight loaded.", bg="#16213e", fg="#e0e0e0",
            font=("Consolas", 11), justify=tk.LEFT, anchor="w", padx=10, pady=8)
        self.review_summary.pack(fill=tk.X, padx=8, pady=4)

        # Scrubber
        scrub = tk.Frame(parent, bg="#1a1a2e")
        scrub.pack(fill=tk.X, padx=8, pady=4)
        tk.Label(scrub, text="Scrub:", bg="#1a1a2e", fg="#aaaaaa",
                 font=("Consolas", 10)).pack(side=tk.LEFT)
        self._scrub_var = tk.DoubleVar(value=0.0)
        self._scrub = ttk.Scale(scrub, from_=0.0, to=1.0,
                                variable=self._scrub_var,
                                orient=tk.HORIZONTAL,
                                command=self._on_scrub)
        self._scrub.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=8)
        self.scrub_readout = tk.Label(scrub, text="--",
                                       bg="#1a1a2e", fg="#00ff88",
                                       font=("Consolas", 11, "bold"), width=16)
        self.scrub_readout.pack(side=tk.RIGHT)

        ttk.Label(parent,
                  text="Loaded flights show on the Dashboard graphs. "
                       "Use the scrubber above to jump to a mission time.",
                  style="Status.TLabel").pack(anchor=tk.W, padx=8, pady=(4, 8))

    # ── Settings tab ────────────────────────────────────────────
    def _build_settings_tab(self, parent):
        ttk.Label(parent, text="SETTINGS", style="Title.TLabel").pack(
            anchor=tk.W, padx=8, pady=(8, 4))

        grid = tk.Frame(parent, bg="#1a1a2e")
        grid.pack(fill=tk.X, padx=8, pady=4)

        # Simulation mode
        self.sim_var = tk.BooleanVar(value=False)
        tk.Checkbutton(grid, text="Simulation mode (no hardware)",
                       variable=self.sim_var, bg="#1a1a2e", fg="#e0e0e0",
                       selectcolor="#16213e", activebackground="#1a1a2e",
                       activeforeground="#e0e0e0",
                       font=("Consolas", 11, "bold"),
                       command=self._toggle_sim).grid(
            row=0, column=0, sticky="w", pady=4, columnspan=2)

        # Units
        tk.Label(grid, text="Units:", bg="#1a1a2e", fg="#aaaaaa",
                 font=("Consolas", 10)).grid(row=1, column=0, sticky="w", pady=4)
        self.units_var = tk.StringVar(value="m")
        for i, u in enumerate(("m", "ft")):
            tk.Radiobutton(grid, text=u, value=u, variable=self.units_var,
                           bg="#1a1a2e", fg="#e0e0e0", selectcolor="#16213e",
                           activebackground="#1a1a2e",
                           font=("Consolas", 10),
                           command=self._apply_units).grid(
                row=1, column=1 + i, sticky="w")

        # View mode
        tk.Label(grid, text="View:", bg="#1a1a2e", fg="#aaaaaa",
                 font=("Consolas", 10)).grid(row=2, column=0, sticky="w", pady=4)
        self.view_var = tk.StringVar(value="operator")
        for i, v in enumerate(("operator", "debug")):
            tk.Radiobutton(grid, text=v, value=v, variable=self.view_var,
                           bg="#1a1a2e", fg="#e0e0e0", selectcolor="#16213e",
                           activebackground="#1a1a2e",
                           font=("Consolas", 10)).grid(
                row=2, column=1 + i, sticky="w")

        # Mission info
        tk.Label(grid, text="Mission name:", bg="#1a1a2e", fg="#aaaaaa",
                 font=("Consolas", 10)).grid(row=3, column=0, sticky="w", pady=4)
        self.mission_entry = tk.Entry(grid, width=28, bg="#16213e",
                                       fg="#e0e0e0", insertbackground="#e0e0e0",
                                       font=("Consolas", 10))
        self.mission_entry.grid(row=3, column=1, columnspan=3, sticky="w", pady=4)

        tk.Label(grid, text="Notes:", bg="#1a1a2e", fg="#aaaaaa",
                 font=("Consolas", 10)).grid(row=4, column=0, sticky="nw", pady=4)
        self.notes_entry = tk.Text(grid, width=50, height=5, bg="#16213e",
                                    fg="#e0e0e0", insertbackground="#e0e0e0",
                                    font=("Consolas", 10))
        self.notes_entry.grid(row=4, column=1, columnspan=3, sticky="w", pady=4)

        # Signal-quality filter
        tk.Label(grid, text="Min valid RSSI (dBm):",
                 bg="#1a1a2e", fg="#aaaaaa", font=("Consolas", 10)).grid(
            row=5, column=0, sticky="w", pady=4)
        self.rssi_entry = tk.Entry(grid, width=8, bg="#16213e", fg="#e0e0e0",
                                    insertbackground="#e0e0e0",
                                    font=("Consolas", 10))
        self.rssi_entry.insert(0, str(MIN_VALID_RSSI_DBM))
        self.rssi_entry.grid(row=5, column=1, sticky="w", pady=4)
        tk.Button(grid, text="Apply", bg="#555555", fg="white",
                  font=("Consolas", 9, "bold"),
                  command=self._apply_rssi_threshold).grid(
            row=5, column=2, sticky="w", padx=4)

        self.reject_var = tk.BooleanVar(value=True)
        tk.Checkbutton(grid,
                       text="Reject garbage packets from weak/dying link",
                       variable=self.reject_var, bg="#1a1a2e", fg="#e0e0e0",
                       selectcolor="#16213e", activebackground="#1a1a2e",
                       activeforeground="#e0e0e0",
                       font=("Consolas", 10),
                       command=self._toggle_reject).grid(
            row=6, column=0, columnspan=4, sticky="w", pady=4)

        # Config editor (thresholds)
        tk.Label(parent, text="Flight computer config",
                 bg="#1a1a2e", fg="#aaaaaa",
                 font=("Consolas", 11, "bold")).pack(
            anchor=tk.W, padx=8, pady=(12, 2))

        cfg_frame = tk.Frame(parent, bg="#1a1a2e")
        cfg_frame.pack(fill=tk.X, padx=8, pady=4)
        self.cfg_entries = {}
        cfg_fields = [
            ("launch_detect_g", "Launch detect (g)"),
            ("apogee_filter_samples", "Apogee filter samples"),
            ("landing_detect_m", "Landing detect (m)"),
            ("telemetry_rate_hz", "Telemetry rate (Hz)"),
            ("logging_rate_hz", "Logging rate (Hz)"),
        ]
        for i, (key, lbl) in enumerate(cfg_fields):
            tk.Label(cfg_frame, text=lbl, bg="#1a1a2e", fg="#aaaaaa",
                     font=("Consolas", 10)).grid(row=i, column=0,
                                                  sticky="w", pady=2)
            e = tk.Entry(cfg_frame, width=10, bg="#16213e", fg="#e0e0e0",
                         insertbackground="#e0e0e0", font=("Consolas", 10))
            e.insert(0, str(DEFAULT_CONFIG[key]))
            e.grid(row=i, column=1, sticky="w", padx=8)
            self.cfg_entries[key] = e

        tk.Button(parent, text="Apply & Upload Config", bg="#2196F3",
                  fg="white", font=("Consolas", 10, "bold"),
                  command=self._apply_config).pack(anchor=tk.W, padx=8, pady=8)

        # Hardware test commands
        tk.Label(parent, text="Hardware tests", bg="#1a1a2e", fg="#aaaaaa",
                 font=("Consolas", 11, "bold")).pack(
            anchor=tk.W, padx=8, pady=(12, 2))
        hw = tk.Frame(parent, bg="#1a1a2e")
        hw.pack(fill=tk.X, padx=8, pady=4)
        for lbl, cmd in [("Buzzer test", "CMD,BUZZ"),
                         ("LED test", "CMD,LED"),
                         ("Radio ping", "CMD,PING"),
                         ("Zero altitude", "CMD,ZEROALT"),
                         ("Calibrate ground pres", "CMD,CALPRES")]:
            tk.Button(hw, text=lbl, bg="#555555", fg="white",
                      font=("Consolas", 9, "bold"),
                      command=lambda c=cmd: self._send_cmd(c)).pack(
                side=tk.LEFT, padx=3)

    # ── Diagnostics tab ─────────────────────────────────────────
    def _build_diag_tab(self, parent):
        ttk.Label(parent, text="DIAGNOSTICS / PACKET INSPECTOR",
                  style="Title.TLabel").pack(anchor=tk.W, padx=8, pady=(8, 4))

        top = tk.Frame(parent, bg="#16213e")
        top.pack(fill=tk.X, padx=8, pady=4)
        self.diag_stats = tk.Label(
            top, text="Packets: 0  |  Dropped: 0  |  Last age: --  |  RSSI: --",
            bg="#16213e", fg="#00ff88", font=("Consolas", 11, "bold"),
            padx=10, pady=6, anchor="w")
        self.diag_stats.pack(fill=tk.X)

        # Latest decoded packet
        tk.Label(parent, text="Latest decoded packet",
                 bg="#1a1a2e", fg="#aaaaaa",
                 font=("Consolas", 11, "bold")).pack(anchor=tk.W,
                                                      padx=8, pady=(8, 2))
        self.diag_decoded = tk.Text(parent, height=10, bg="#0f0f1a",
                                     fg="#00ff88", font=("Consolas", 10),
                                     relief=tk.FLAT, state=tk.DISABLED)
        self.diag_decoded.pack(fill=tk.X, padx=8, pady=2)

        tk.Label(parent, text="Raw serial log (tail)",
                 bg="#1a1a2e", fg="#aaaaaa",
                 font=("Consolas", 11, "bold")).pack(anchor=tk.W,
                                                      padx=8, pady=(8, 2))
        raw = tk.Frame(parent, bg="#0f0f1a")
        raw.pack(fill=tk.BOTH, expand=True, padx=8, pady=2)
        self.diag_raw = tk.Text(raw, bg="#0f0f1a", fg="#44ff44",
                                 font=("Consolas", 9), relief=tk.FLAT,
                                 wrap=tk.NONE, state=tk.DISABLED)
        rscroll = ttk.Scrollbar(raw, orient=tk.VERTICAL,
                                 command=self.diag_raw.yview)
        self.diag_raw.configure(yscrollcommand=rscroll.set)
        rscroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.diag_raw.pack(fill=tk.BOTH, expand=True)

    def _make_card(self, parent, title, init_val, unit, key=""):
        card = ttk.Frame(parent, style="Card.TFrame", width=140, height=88)
        card.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=3)
        card.pack_propagate(False)
        t_lbl = ttk.Label(card, text=title, style="Lbl.TLabel")
        t_lbl.pack(pady=(6, 0))
        v_lbl = ttk.Label(card, text=init_val, style="Val.TLabel")
        v_lbl.pack()
        u_lbl = ttk.Label(card, text=unit, style="Unit.TLabel")
        u_lbl.pack()
        if key:
            self.card_labels[key] = (t_lbl, u_lbl)
        return v_lbl

    # ── Commands ─────────────────────────────────────────────────
    def _send_safe(self):
        if not self.reader.connected:
            self.safe_status.configure(text="NOT CONNECTED", foreground="#ff4444")
            return
        if self.reader.send_command("CMD,SAFE"):
            self.safe_status.configure(text="SAFE SENT", foreground="#ff8800")
            self.btn_safe.configure(bg="#884400", text="SAFE SENT")
            # Send 3x for reliability
            self.root.after(200, lambda: self.reader.send_command("CMD,SAFE"))
            self.root.after(400, lambda: self.reader.send_command("CMD,SAFE"))

    def _send_arm(self):
        if not self.reader.connected:
            self.safe_status.configure(text="NOT CONNECTED", foreground="#ff4444")
            return
        if self.reader.send_command("CMD,ARM"):
            self.safe_status.configure(text="ARM SENT \u00d73",
                                       foreground="#ff8800")
            self.btn_arm.configure(bg="#885500", text="ARM SENT",
                                   state=tk.NORMAL)
            self.btn_safe.configure(bg="#cc0000", text="SAFE PYROS",
                                    state=tk.NORMAL)
            self.root.after(200, lambda: self.reader.send_command("CMD,ARM"))
            self.root.after(400, lambda: self.reader.send_command("CMD,ARM"))

    def _refresh_ports(self):
        ports = [p.device for p in serial.tools.list_ports.comports()]
        self.port_combo["values"] = ports
        if ports and not self.port_var.get():
            self.port_var.set(ports[0])

    def _toggle_connect(self):
        if self.reader.connected:
            self.reader.disconnect()
            self.btn_connect.configure(text="Connect")
            self.conn_status.configure(text="DISCONNECTED", foreground="#888888")
        else:
            port = self.port_var.get()
            if not port:
                return
            err = self.reader.connect(port)
            if err:
                self.conn_status.configure(
                    text=f"ERROR: {err}", foreground="#ff4444")
            else:
                self.btn_connect.configure(text="Disconnect")
                self.conn_status.configure(
                    text=f"CONNECTED ({port})", foreground="#00ff88")
                self._reset_display()

    # ── Reset ────────────────────────────────────────────────────
    def _reset_display(self):
        self.t_hist.clear();    self.alt_hist.clear()
        self.vel_hist.clear();  self.acc_hist.clear()
        self.rssi_hist.clear(); self.gyro_hist.clear()
        self.t_offset = None;   self.last_telem = None
        self._current_mode = None; self._prev_state = None
        self.peak_alt = 0.0; self.peak_accel = 0.0; self.peak_vel = 0.0
        self.reader.packet_count = 0
        self._dropped_total = 0
        self._filtered_count = 0

        self.sim_source.reset()
        self.fault_detector.reset()
        self._launch_ts = None
        self._landed_ts = None
        self._apogee_announced = False
        self._last_packet_ts = 0.0
        self._last_sim_ts = 0.0
        self._stale = False
        self.events.reset_mission_time()
        self.events.add(SEV_INFO, "ui", "Display and simulation reset")

        self.state_label.configure(text="--",   foreground="#ffffff")
        self.alt_label.configure(text="0.0",    foreground="#00ff88")
        self.maxalt_label.configure(text="0.0",  foreground="#00ff88")
        self.vel_label.configure(text="0.0",     foreground="#00ff88")
        self.accel_label.configure(text="0.0",   foreground="#00ff88")
        self.pyro_label.configure(text="SAFE",   foreground="#00ff88")

        for key, (t_lbl, u_lbl) in self.card_labels.items():
            if key == "state":   t_lbl.configure(text="STATE");   u_lbl.configure(text="")
            elif key == "maxalt": t_lbl.configure(text="MAX ALT"); u_lbl.configure(text="m")
            elif key == "vel":   t_lbl.configure(text="VELOCITY"); u_lbl.configure(text="m/s")
            elif key == "accel": t_lbl.configure(text="ACCEL")

        self.btn_safe.configure(bg="#cc0000", text="SAFE PYROS", state=tk.NORMAL)
        self.btn_arm.configure(bg="#555555", text="RE-ARM", state=tk.NORMAL)
        self.safe_status.configure(text="")
        self.pkt_label.configure(text="Packets: 0")
        self.rssi_label.configure(text="RSSI: -- dBm")
        self.peak_label.configure(
            text="Peak:  Alt --  |  Vel --  |  Accel --  |  RSSI --")
        self.checklist_label.configure(text="")

        for line in [self.line_alt, self.line_vel, self.line_acc, self.line_rssi]:
            line.set_data([], [])
        for ax in (self.ax_alt, self.ax_vel, self.ax_acc, self.ax_rssi):
            ax.relim(); ax.autoscale_view()
        self.canvas.draw_idle()

        self.log_text.configure(state=tk.NORMAL)
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state=tk.DISABLED)

    # ── CSV recording ────────────────────────────────────────────
    def _toggle_record(self):
        if self._recording:
            self._stop_recording()
        else:
            self._start_recording()

    def _start_recording(self):
        folder = os.path.dirname(os.path.abspath(__file__))
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._csv_path = os.path.join(folder, f"flight_{ts}.csv")
        try:
            self._csv_file = open(self._csv_path, "w", newline="")
            self._csv_writer = csv.writer(self._csv_file)
            self._csv_writer.writerow(CSV_HEADER)
            self._recording = True
            self.btn_record.configure(bg="#cc0000", text="  STOP REC  ")
            self.safe_status.configure(
                text=f"Recording: {os.path.basename(self._csv_path)}",
                foreground="#ff4444")
        except Exception as e:
            self.safe_status.configure(text=f"Record error: {e}",
                                       foreground="#ff4444")

    def _stop_recording(self):
        self._recording = False
        if self._csv_file:
            self._csv_file.close()
            self._csv_file = None
            self._csv_writer = None
        self.btn_record.configure(bg="#555555", text="  RECORD  ")
        if self._csv_path:
            self.safe_status.configure(
                text=f"Saved: {os.path.basename(self._csv_path)}",
                foreground="#00ff88")

    def _record_telemetry(self, t: Telemetry, elapsed: float):
        if self._recording and self._csv_writer:
            try:
                self._csv_writer.writerow(t.to_csv_row(elapsed))
            except Exception:
                pass

    # ── Flight replay ────────────────────────────────────────────
    def _load_flight(self):
        path = filedialog.askopenfilename(
            title="Load Flight CSV",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")])
        if not path:
            return
        self._reset_display()
        try:
            data = self._parse_csv(path)
            if not data["t"]:
                self.safe_status.configure(text="CSV has no data",
                                           foreground="#ff4444")
                return
            t0 = data["t"][0]
            for i in range(len(data["t"])):
                ts = data["t"][i] - t0
                self.t_hist.append(ts)
                self.alt_hist.append(data["alt"][i])
                self.vel_hist.append(data["vel"][i])
                self.acc_hist.append(data["acc"][i])
                self.rssi_hist.append(data["rssi"][i])
                self.gyro_hist.append(data.get("gyro", [0]*len(data["t"]))[i])
                self.peak_alt   = max(self.peak_alt, data["alt"][i])
                self.peak_vel   = max(self.peak_vel, abs(data["vel"][i]))
                self.peak_accel = max(self.peak_accel, data["acc"][i])

            self._update_peaks(0)
            self._redraw_graphs()
            self._update_apogee_marker()
            self._update_review_summary()
            self.canvas.draw_idle()
            name = os.path.basename(path)
            self.safe_status.configure(
                text=f"Loaded: {name} ({len(data['t'])} points)",
                foreground="#00ff88")
            self.conn_status.configure(text=f"REPLAY: {name}",
                                       foreground="#00bcd4")
            self.events.add(SEV_INFO, "replay", f"Loaded CSV: {name}")
        except Exception as e:
            self.safe_status.configure(text=f"Load error: {e}",
                                       foreground="#ff4444")

    # ── Overlay ──────────────────────────────────────────────────
    def _load_overlay(self):
        path = filedialog.askopenfilename(
            title="Load Overlay CSV",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")])
        if not path:
            return
        try:
            data = self._parse_csv(path)
            if not data["t"]:
                return
            t0 = data["t"][0]
            t_list = [t - t0 for t in data["t"]]
            name = os.path.basename(path)
            self._overlays[name] = (t_list, data["alt"], data["vel"], data["acc"])
            self._draw_overlays()
            self.safe_status.configure(
                text=f"Overlay: {name} ({len(t_list)} points)",
                foreground="#00bcd4")
        except Exception as e:
            self.safe_status.configure(text=f"Overlay error: {e}",
                                       foreground="#ff4444")

    def _clear_overlays(self):
        for line in self._overlay_lines:
            line.remove()
        self._overlay_lines.clear()
        self._overlays.clear()
        self.canvas.draw_idle()
        self.safe_status.configure(text="Overlays cleared", foreground="#888888")

    def _draw_overlays(self):
        # Remove old overlay lines
        for line in self._overlay_lines:
            line.remove()
        self._overlay_lines.clear()

        for i, (name, (tl, al, vl, acl)) in enumerate(self._overlays.items()):
            color = OVERLAY_COLORS[i % len(OVERLAY_COLORS)]
            la, = self.ax_alt.plot(tl, al, color=color, lw=1, ls="--", alpha=0.7)
            lv, = self.ax_vel.plot(tl, vl, color=color, lw=1, ls="--", alpha=0.7)
            lc, = self.ax_acc.plot(tl, acl, color=color, lw=1, ls="--", alpha=0.7)
            self._overlay_lines.extend([la, lv, lc])
        self.canvas.draw_idle()

    def _parse_csv(self, path: str) -> dict:
        """Parse a recorded CSV into lists of values."""
        result = {"t": [], "alt": [], "vel": [], "acc": [], "rssi": [], "gyro": []}
        with open(path, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    result["t"].append(float(row.get("elapsed_s", 0)))
                    result["alt"].append(float(row.get("alt", 0)))
                    result["vel"].append(float(row.get("vel", 0)))
                    result["acc"].append(float(row.get("accel", 0)))
                    result["rssi"].append(float(row.get("rssi", 0)))
                    gx = float(row.get("gx", 0))
                    gy = float(row.get("gy", 0))
                    gz = float(row.get("gz", 0))
                    result["gyro"].append(math.sqrt(gx**2 + gy**2 + gz**2))
                except (ValueError, TypeError):
                    continue
        return result

    # ── Audio alerts ─────────────────────────────────────────────
    def _check_alerts(self, t: Telemetry):
        if t.packet_type != "F":
            return
        new_state = t.state
        if self._prev_state is not None and new_state != self._prev_state:
            if new_state == 2:   _beep_thread(ALERT_PATTERNS["armed"])
            elif new_state == 3: _beep_thread(ALERT_PATTERNS["launch"])
            elif new_state == 5: _beep_thread(ALERT_PATTERNS["apogee"])
            elif new_state == 6: _beep_thread(ALERT_PATTERNS["landed"])
            elif new_state == 7: _beep_thread(ALERT_PATTERNS["fault"])
        self._prev_state = new_state

    # ── Graph redraw ─────────────────────────────────────────────
    def _redraw_graphs(self):
        t_list = list(self.t_hist)
        self.line_alt.set_data(t_list, list(self.alt_hist))
        self.line_acc.set_data(t_list, list(self.acc_hist))
        self.line_rssi.set_data(t_list, list(self.rssi_hist))

        # Graph 2: velocity in flight mode, gyro in data mode
        if self._current_mode == "D":
            self.line_vel.set_data(t_list, list(self.gyro_hist))
        else:
            self.line_vel.set_data(t_list, list(self.vel_hist))

        for ax in (self.ax_alt, self.ax_vel, self.ax_acc, self.ax_rssi):
            ax.relim()
            ax.autoscale_view()
        self.canvas.draw_idle()

    def _update_peaks(self, rssi: int):
        best_rssi = max(self.rssi_hist) if self.rssi_hist else rssi
        self.peak_label.configure(
            text=f"Peak:  Alt {self.peak_alt:.1f} m  |  "
                 f"Vel {self.peak_vel:.1f} m/s  |  "
                 f"Accel {self.peak_accel:.2f} g  |  "
                 f"RSSI {best_rssi:.0f} dBm")

    # ── Main tick (20 Hz) ────────────────────────────────────────
    def _tick(self):
        packets = list(self.reader.drain())
        log_lines = self.reader.drain_log()

        # Simulation source: inject fake packets when enabled
        if self.config.get("sim_mode"):
            now = time.monotonic()
            if now - self._last_sim_ts >= 0.1:     # 10 Hz
                self._last_sim_ts = now
                fake = self.sim_source.get_packet()
                if fake:
                    packets.append(fake)
                    self.reader.packet_count += 1

        # Append raw log (dashboard mini + diagnostics tab)
        if log_lines:
            self.log_text.configure(state=tk.NORMAL)
            for line in log_lines:
                self.log_text.insert(tk.END, line + "\n")
            lc = int(self.log_text.index("end-1c").split(".")[0])
            if lc > 200:
                self.log_text.delete("1.0", f"{lc - 200}.0")
            self.log_text.see(tk.END)
            self.log_text.configure(state=tk.DISABLED)

            if hasattr(self, "diag_raw"):
                self.diag_raw.configure(state=tk.NORMAL)
                for line in log_lines:
                    self.diag_raw.insert(tk.END, line + "\n")
                lc = int(self.diag_raw.index("end-1c").split(".")[0])
                if lc > 400:
                    self.diag_raw.delete("1.0", f"{lc - 400}.0")
                self.diag_raw.see(tk.END)
                self.diag_raw.configure(state=tk.DISABLED)

        # Process packets
        dropped_this_tick = 0
        prev_time_s = self.last_telem.time_s if self.last_telem else None
        for t in packets:
            # Signal-quality gate: drop garbage from weak/dying link
            ok, reason = self._is_packet_valid(t)
            if not ok:
                self._filtered_count += 1
                # Rate-limit the event spam
                if self._filtered_count % 5 == 1:
                    self.events.add(SEV_WARN, "filter",
                                    f"Dropped bad packet: {reason}")
                continue

            if self.t_offset is None:
                self.t_offset = t.time_s
                self.events.reset_mission_time()

            # Detect dropped packets by time_s gaps (F packets at known rate)
            if (prev_time_s is not None and t.packet_type == "F"
                    and self.last_telem and self.last_telem.packet_type == "F"):
                rate = max(1, int(self.config.get("telemetry_rate_hz", 10)))
                expected_dt = 1.0 / rate
                gap = t.time_s - prev_time_s
                if gap > expected_dt * 2.5:
                    missed = int(gap / expected_dt) - 1
                    if missed > 0:
                        dropped_this_tick += missed
            prev_time_s = t.time_s

            ts = t.time_s - self.t_offset
            self.t_hist.append(ts)
            self.alt_hist.append(t.alt)
            self.vel_hist.append(t.vel)
            self.acc_hist.append(t.accel)
            self.rssi_hist.append(t.rssi)
            gyro_mag = math.sqrt(t.gx**2 + t.gy**2 + t.gz**2)
            self.gyro_hist.append(gyro_mag)

            if t.packet_type == "F":
                self.peak_alt = max(self.peak_alt, t.max_alt, t.alt)
            else:
                self.peak_alt = max(self.peak_alt, t.alt)
            self.peak_vel   = max(self.peak_vel, abs(t.vel))
            self.peak_accel = max(self.peak_accel, t.accel)

            self._record_telemetry(t, ts)
            self._check_alerts(t)
            self.fault_detector.check(t)

            # Structured events on state transitions
            if (self.last_telem and t.packet_type == "F"
                    and self.last_telem.packet_type == "F"
                    and t.state != self.last_telem.state):
                prev_name = STATE_NAMES.get(self.last_telem.state, "?")
                new_name = STATE_NAMES.get(t.state, "?")
                sev = SEV_FAULT if t.state == 7 else SEV_INFO
                self.events.add(sev, "flight",
                                f"State {prev_name} -> {new_name}")
                if t.state == 3:
                    self._launch_ts = time.monotonic()
                    self.events.add(SEV_WARN, "flight", "LAUNCH detected")
                if t.state == 5 and not self._apogee_announced:
                    self._apogee_announced = True
                    self.events.add(SEV_INFO, "flight",
                                    f"APOGEE at {self._fmt_alt(self.peak_alt)}")
                if t.state == 6:
                    self._landed_ts = time.monotonic()
                    self.events.add(SEV_INFO, "flight",
                                    "LANDED - flight summary available in Review")
                    self._update_review_summary()

            self._last_packet_ts = time.monotonic()
            self.last_telem = t

        if dropped_this_tick > 0:
            self._dropped_total += dropped_this_tick
            self.events.add(SEV_WARN, "radio",
                            f"{dropped_this_tick} packet(s) dropped")

        # Stale telemetry detection
        now = time.monotonic()
        if self._last_packet_ts > 0:
            age = now - self._last_packet_ts
            new_stale = age > STALE_TIMEOUT_S and (
                self.reader.connected or self.config.get("sim_mode"))
            if new_stale and not self._stale:
                self.events.add(SEV_WARN, "radio",
                                f"Telemetry stale ({age:.1f}s, no packets)")
            if not new_stale and self._stale:
                self.events.add(SEV_INFO, "radio", "Telemetry resumed")
            self._stale = new_stale
        else:
            self._stale = False

        # Preflight auto-checks
        last_pkt_age = (now - self._last_packet_ts) if self._last_packet_ts else 999.0
        self.preflight.update_auto(
            self.reader.connected or self.config.get("sim_mode"),
            self.reader.packet_count, last_pkt_age, self.last_telem)
        self._refresh_preflight()

        # Card / label updates (keep showing last-good values on stale)
        if self.last_telem:
            t = self.last_telem
            self._switch_mode(t.packet_type)

            if t.packet_type == "D":
                self._update_cards_data(t)
            else:
                self._update_cards_flight(t)

            self.rssi_label.configure(text=f"RSSI: {t.rssi} dBm")
            self._update_peaks(t.rssi)
            self._update_checklist(t)

        self.pkt_label.configure(text=f"Packets: {self.reader.packet_count}")

        # Banner + diagnostics + events
        self._update_banner(self.last_telem)
        if hasattr(self, "diag_stats"):
            self._update_diag(self.last_telem, dropped_this_tick)
        if hasattr(self, "events_text"):
            self._refresh_events()

        # Disconnect detection
        if not self.reader.connected and self.btn_connect.cget("text") == "Disconnect":
            self.btn_connect.configure(text="Connect")
            self.conn_status.configure(text="DISCONNECTED (lost)",
                                       foreground="#ff8800")
            self.events.add(SEV_WARN, "radio", "Serial connection lost")

        # Graphs (throttled to 5 Hz; skip if paused)
        self._graph_counter += 1
        if (not self._graph_paused and self._graph_counter >= 4
                and len(self.t_hist) > 1):
            self._graph_counter = 0
            self._redraw_graphs()
            self._update_apogee_marker()
            self.canvas.draw_idle()

        self.root.after(50, self._tick)

    # ── Mode switching ───────────────────────────────────────────
    def _switch_mode(self, mode: str):
        if mode == self._current_mode:
            return
        self._current_mode = mode
        if mode == "D":
            self.card_labels["state"][0].configure(text="TEMP")
            self.card_labels["state"][1].configure(text="\u00b0C")
            self.card_labels["maxalt"][0].configure(text="PRESSURE")
            self.card_labels["maxalt"][1].configure(text="hPa")
            self.card_labels["vel"][0].configure(text="BATTERY")
            self.card_labels["vel"][1].configure(text="V")
            self.card_labels["accel"][0].configure(text="|ACCEL|")
            self.btn_safe.configure(bg="#333333", state=tk.DISABLED)
            self.btn_arm.configure(bg="#333333", state=tk.DISABLED)
            self.safe_status.configure(
                text="DATA MODE — arm switch is hardware only",
                foreground="#888888")
            # Switch graph 2 label to Gyro
            self.ax_vel.set_ylabel("Gyro (\u00b0/s)", color="#ff8800", fontsize=8)
            self.line_vel.set_color("#ff8800")
        else:
            self.card_labels["state"][0].configure(text="STATE")
            self.card_labels["state"][1].configure(text="")
            self.card_labels["maxalt"][0].configure(text="MAX ALT")
            self.card_labels["maxalt"][1].configure(text="m")
            self.card_labels["vel"][0].configure(text="VELOCITY")
            self.card_labels["vel"][1].configure(text="m/s")
            self.card_labels["accel"][0].configure(text="ACCEL")
            self.btn_safe.configure(bg="#cc0000", state=tk.NORMAL)
            self.btn_arm.configure(bg="#555555", state=tk.NORMAL)
            self.safe_status.configure(text="")
            # Switch graph 2 label to Velocity
            self.ax_vel.set_ylabel("Vel (m/s)", color="#ff8800", fontsize=8)
            self.line_vel.set_color("#ff8800")

    # ── Card updates ─────────────────────────────────────────────
    def _update_cards_data(self, t: Telemetry):
        self.state_label.configure(text=f"{t.temp_c:.1f}", foreground="#00bcd4")
        self.alt_label.configure(text=f"{t.alt:.2f}")
        self.maxalt_label.configure(text=f"{t.pres_hpa:.0f}")
        self.vel_label.configure(
            text=f"{t.vbat:.1f}",
            foreground="#00ff88" if t.vbat >= 7.0
            else "#ff8800" if t.vbat >= 1.0 else "#ff4444")
        self.accel_label.configure(text=f"{t.accel:.2f}")
        c1_ok = 200 < t.cont1 < 3800
        c2_ok = 200 < t.cont2 < 3800
        if t.arm:
            self.pyro_label.configure(text="ARMED", foreground="#ff8800")
        elif c1_ok and c2_ok:
            self.pyro_label.configure(text="READY", foreground="#00ff88")
        elif c1_ok or c2_ok:
            self.pyro_label.configure(text="1 CONT", foreground="#ff8800")
        else:
            self.pyro_label.configure(text="OPEN", foreground="#888888")

    def _update_cards_flight(self, t: Telemetry):
        name = STATE_NAMES.get(t.state, f"?{t.state}")
        color = STATE_COLORS.get(t.state, "#ffffff")
        self.state_label.configure(text=name, foreground=color)
        self.alt_label.configure(text=f"{t.alt:.1f}")
        self.maxalt_label.configure(text=f"{self.peak_alt:.1f}")
        self.vel_label.configure(text=f"{t.vel:.1f}")
        self.accel_label.configure(text=f"{t.accel:.2f}")

        if t.remote_safe:
            self.pyro_label.configure(text="SAFED", foreground="#ff8800")
            self.safe_status.configure(text="CONFIRMED SAFE",
                                       foreground="#00ff88")
            self.btn_safe.configure(bg="#006600", text="PYROS SAFE",
                                    state=tk.NORMAL)
            self.btn_arm.configure(bg="#cc0000", text="RE-ARM",
                                   state=tk.NORMAL)
        elif t.pyro:
            self.pyro_label.configure(text="FIRED", foreground="#ff4444")
        elif t.state == 2:
            self.pyro_label.configure(text="ARMED", foreground="#ff8800")
            self.btn_safe.configure(bg="#cc0000", text="SAFE PYROS",
                                    state=tk.NORMAL)
            self.btn_arm.configure(bg="#006600", text="ARMED",
                                   state=tk.NORMAL)
            self.safe_status.configure(text="", foreground="#888888")
        else:
            self.pyro_label.configure(text="SAFE", foreground="#00ff88")
            self.btn_safe.configure(bg="#cc0000", text="SAFE PYROS",
                                    state=tk.NORMAL)
            self.btn_arm.configure(bg="#555555", text="RE-ARM",
                                   state=tk.NORMAL)

    # ── Pre-launch checklist ─────────────────────────────────────
    def _update_checklist(self, t: Telemetry):
        if t.vbat <= 0 and t.cont1 == 0 and t.cont2 == 0 and t.temp_c == 0:
            self.checklist_label.configure(text="")
            return

        parts = []
        # Battery
        if t.vbat > 0:
            vcolor = "#00ff88" if t.vbat >= 7.0 else "#ff4444"
            vtext = "OK" if t.vbat >= 7.0 else "LOW!"
            parts.append(f"Batt: {t.vbat:.1f}V [{vtext}]")

        # Continuity
        c1_ok = 200 < t.cont1 < 3800
        c2_ok = 200 < t.cont2 < 3800
        parts.append(f"Pyro1: {'OK' if c1_ok else 'OPEN'}")
        parts.append(f"Pyro2: {'OK' if c2_ok else 'OPEN'}")

        # Temperature
        if t.temp_c != 0:
            parts.append(f"Temp: {t.temp_c:.1f}\u00b0C")

        self.checklist_label.configure(text="    ".join(parts))

        # Color based on overall status
        all_ok = (t.vbat >= 7.0 or t.vbat == 0) and c1_ok and c2_ok
        self.checklist_label.configure(
            foreground="#00ff88" if all_ok else "#ff8800")


    # ── New: banner ──────────────────────────────────────────────
    def _update_banner(self, t: "Telemetry | None"):
        if self._stale:
            self.banner_label.configure(text="STALE TELEMETRY", foreground="#ff4444")
            self.banner_sub.configure(
                text=f"No packet for {time.monotonic() - self._last_packet_ts:.1f}s")
            return
        if not self.reader.connected and not self.config.get("sim_mode"):
            self.banner_label.configure(text="DISCONNECTED", foreground="#888888")
            self.banner_sub.configure(text="No telemetry")
            return
        if t is None:
            self.banner_label.configure(text="CONNECTED", foreground="#2196F3")
            self.banner_sub.configure(text="Waiting for telemetry")
            return
        state_text = STATE_NAMES.get(t.state, f"?{t.state}")
        color = STATE_COLORS.get(t.state, "#ffffff")
        mission_s = (time.monotonic() - (self._launch_ts or time.monotonic())) \
                     if self._launch_ts else 0.0
        if t.state == 7:
            banner_text = "FAULT"
        elif t.state in (3, 4, 5):
            banner_text = "IN FLIGHT"
        elif t.state == 2:
            banner_text = "ARMED"
        elif t.state == 6:
            banner_text = "LANDED"
        elif t.state == 1:
            banner_text = "READY"
        else:
            banner_text = state_text
        live = "LIVE" if self.reader.connected and not self.config.get("sim_mode") \
               else ("SIM" if self.config.get("sim_mode") else "REPLAY")
        self.banner_label.configure(text=banner_text, foreground=color)
        sub = (f"[{live}]  state={state_text}  "
               f"alt={self._fmt_alt(t.alt)}  "
               f"vel={t.vel:.1f} m/s  "
               f"max={self._fmt_alt(self.peak_alt)}  "
               f"T+{mission_s:5.1f}s")
        self.banner_sub.configure(text=sub)

    def _fmt_alt(self, m: float) -> str:
        if self.config.get("units") == "ft":
            return f"{m * FT_PER_M:.1f} ft"
        return f"{m:.1f} m"

    # ── New: pause graphs ────────────────────────────────────────
    def _toggle_pause(self):
        self._graph_paused = not self._graph_paused
        if self._graph_paused:
            self.btn_pause.configure(bg="#cc8800", text=" RESUME ")
            self.events.add(SEV_INFO, "ui", "Graphs paused")
        else:
            self.btn_pause.configure(bg="#444444", text="  PAUSE  ")
            self.events.add(SEV_INFO, "ui", "Graphs resumed")

    # ── New: simulation toggle ───────────────────────────────────
    def _toggle_sim(self):
        on = bool(self.sim_var.get())
        self.config["sim_mode"] = on
        if on:
            self.sim_source.reset()
            self._last_sim_ts = 0.0
            self._reset_display()
            self.events.add(SEV_INFO, "sim", "Simulation mode ENABLED")
        else:
            self.events.add(SEV_INFO, "sim", "Simulation mode disabled")

    # ── New: RSSI filter controls ───────────────────────────────
    def _apply_rssi_threshold(self):
        try:
            val = int(self.rssi_entry.get().strip())
            self.config["min_rssi_dbm"] = val
            self.events.add(SEV_INFO, "filter",
                            f"Min valid RSSI set to {val} dBm")
        except ValueError:
            self.events.add(SEV_WARN, "filter",
                            f"Bad RSSI value: {self.rssi_entry.get()!r}")

    def _toggle_reject(self):
        self.config["reject_garbage"] = bool(self.reject_var.get())
        state = "ENABLED" if self.config["reject_garbage"] else "DISABLED"
        self.events.add(SEV_INFO, "filter", f"Garbage rejection {state}")

    # ── New: units toggle ────────────────────────────────────────
    def _apply_units(self):
        self.config["units"] = self.units_var.get()
        unit = self.config["units"]
        self.card_labels["alt"][1].configure(text=unit) if "alt" in self.card_labels else None
        if "maxalt" in self.card_labels:
            self.card_labels["maxalt"][1].configure(text=unit)
        self.events.add(SEV_INFO, "ui", f"Units set to {unit}")

    # ── New: preflight manual toggle ─────────────────────────────
    def _toggle_manual_check(self, key: str):
        cur_bypassed = self.preflight.items[key].get("bypassed", False)
        new = not cur_bypassed
        self.preflight.set_manual(key, new)
        self.events.add(SEV_INFO, "preflight",
                        f"{key}: {'BYPASSED' if new else 'cleared'}")
        self._refresh_preflight()

    def _bypass_all(self):
        for key in self.preflight.items.keys():
            self.preflight.set_manual(key, True)
        self.events.add(SEV_WARN, "preflight", "ALL checks bypassed manually")
        self._refresh_preflight()

    def _clear_all_bypass(self):
        for key in self.preflight.items.keys():
            self.preflight.set_manual(key, False)
        self.events.add(SEV_INFO, "preflight", "All bypasses cleared")
        self._refresh_preflight()

    def _refresh_preflight(self):
        for key, (st_lbl, btn) in self._check_rows.items():
            item = self.preflight.items[key]
            bypassed = item.get("bypassed", False)
            status = item["status"]
            if bypassed:
                st_lbl.configure(text=" ✓ ", fg="#ffaa00")
                if btn:
                    btn.configure(bg="#aa6600", text=" Clear ")
            elif status is True:
                st_lbl.configure(text=" ✓ ", fg="#00ff88")
                if btn:
                    btn.configure(bg="#2196F3", text="Mark OK")
            elif status is False:
                st_lbl.configure(text=" ✗ ", fg="#ff4444")
                if btn:
                    btn.configure(bg="#2196F3", text="Mark OK")
            else:
                st_lbl.configure(text=" ? ", fg="#888888")
                if btn:
                    btn.configure(bg="#2196F3", text="Mark OK")

        passed, total = self.preflight.summary()
        self.preflight_summary.configure(
            text=f"Required passed: {passed}/{total}",
            fg="#00ff88" if passed == total else "#ff8800")

        if self.preflight.all_required_passed():
            self.btn_arm_gated.configure(
                state=tk.NORMAL, bg="#cc7700", fg="white",
                text="ARM (ready)")
        else:
            self.btn_arm_gated.configure(
                state=tk.DISABLED, bg="#333333", fg="#888888",
                text="ARM (gated)")

    # ── New: gated ARM with two-step confirm ─────────────────────
    def _arm_with_confirm(self):
        if not self.preflight.all_required_passed():
            messagebox.showerror("ARM blocked",
                                 "Required preflight checks are not passed.")
            return
        typed = simpledialog.askstring(
            "Confirm ARM",
            "Type ARM to confirm arming the rocket:",
            parent=self.root)
        if typed is None:
            return
        if typed.strip().upper() != "ARM":
            self.events.add(SEV_WARN, "ui", "ARM cancelled (wrong confirm)")
            messagebox.showinfo("ARM cancelled", "Confirmation text did not match.")
            return
        self._send_arm()
        self.events.add(SEV_WARN, "cmd", "ARM confirmed and sent")

    # ── New: generic command sender ──────────────────────────────
    def _send_cmd(self, cmd: str):
        if self.config.get("sim_mode"):
            self.events.add(SEV_INFO, "sim", f"[sim] would send: {cmd}")
            return
        if not self.reader.connected:
            self.events.add(SEV_WARN, "cmd", f"Not connected; dropped: {cmd}")
            return
        if self.reader.send_command(cmd):
            self.events.add(SEV_INFO, "cmd", f"Sent: {cmd}")
        else:
            self.events.add(SEV_FAULT, "cmd", f"Send failed: {cmd}")

    # ── New: config apply (upload) ───────────────────────────────
    def _apply_config(self):
        for key, entry in self.cfg_entries.items():
            txt = entry.get().strip()
            try:
                val = float(txt) if "." in txt else int(txt)
            except ValueError:
                self.events.add(SEV_WARN, "config",
                                f"Bad value for {key}: {txt!r}")
                continue
            self.config[key] = val
            self._send_cmd(f"CFG,{key},{val}")
        self.events.add(SEV_INFO, "config", "Config applied")

    # ── New: events panel ────────────────────────────────────────
    def _refresh_events(self):
        flt = self.ev_filter.get() if hasattr(self, "ev_filter") else "ALL"
        min_sev = None if flt == "ALL" else flt
        evs = self.events.list(min_sev)
        self.events_text.configure(state=tk.NORMAL)
        self.events_text.delete("1.0", tk.END)
        for e in evs[-400:]:
            line = (f"[{e['t_wall']}] T+{e['t_mission']:6.2f}s  "
                    f"{e['severity']:5s}  {e['source']:9s}  {e['message']}\n")
            self.events_text.insert(tk.END, line, e["severity"])
        self.events_text.see(tk.END)
        self.events_text.configure(state=tk.DISABLED)

    def _clear_events(self):
        self.events.clear()
        self._refresh_events()

    def _export_events(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv")],
            title="Export events")
        if not path:
            return
        try:
            self.events.export_csv(path)
            self.events.add(SEV_INFO, "system", f"Events exported: {path}")
        except Exception as e:
            self.events.add(SEV_FAULT, "system", f"Events export failed: {e}")

    # ── New: review scrubber ─────────────────────────────────────
    def _on_scrub(self, _val):
        if not self.t_hist:
            return
        frac = float(self._scrub_var.get())
        t_list = list(self.t_hist)
        alt_list = list(self.alt_hist)
        vel_list = list(self.vel_hist)
        acc_list = list(self.acc_hist)
        if not t_list:
            return
        t_min, t_max = t_list[0], t_list[-1]
        t_target = t_min + frac * (t_max - t_min)
        idx = min(range(len(t_list)), key=lambda i: abs(t_list[i] - t_target))
        self.scrub_readout.configure(
            text=f"T+{t_list[idx]:.1f}s  {self._fmt_alt(alt_list[idx])}")

    def _update_review_summary(self):
        if not self.alt_hist:
            self.review_summary.configure(text="No flight loaded.")
            return
        t_list = list(self.t_hist)
        alt_list = list(self.alt_hist)
        vel_list = list(self.vel_hist)
        acc_list = list(self.acc_hist)
        max_alt = max(alt_list)
        apogee_idx = alt_list.index(max_alt)
        t_apogee = t_list[apogee_idx]
        max_vel = max(abs(v) for v in vel_list) if vel_list else 0
        max_acc = max(acc_list) if acc_list else 0
        duration = t_list[-1] - t_list[0]
        descent = 0.0
        if apogee_idx < len(t_list) - 1:
            dt = t_list[-1] - t_apogee
            if dt > 0:
                descent = (max_alt - alt_list[-1]) / dt
        summary = (f"Max altitude:  {self._fmt_alt(max_alt)}\n"
                   f"Time to apogee: {t_apogee:.2f} s\n"
                   f"Max velocity:  {max_vel:.2f} m/s\n"
                   f"Max accel:     {max_acc:.2f} g\n"
                   f"Flight duration: {duration:.2f} s\n"
                   f"Avg descent rate: {descent:.2f} m/s")
        self.review_summary.configure(text=summary)

    # ── New: apogee marker on graph ──────────────────────────────
    def _update_apogee_marker(self):
        if self._apogee_marker is not None:
            try:
                self._apogee_marker.remove()
            except Exception:
                pass
            self._apogee_marker = None
        if self.alt_hist and self.t_hist:
            alt_list = list(self.alt_hist)
            t_list = list(self.t_hist)
            max_alt = max(alt_list)
            idx = alt_list.index(max_alt)
            self._apogee_marker = self.ax_alt.axvline(
                t_list[idx], color="#ffff00", ls=":", lw=1, alpha=0.7)

    # ── New: diagnostics update ──────────────────────────────────
    def _update_diag(self, t: "Telemetry | None", dropped: int):
        age = (time.monotonic() - self._last_packet_ts) if self._last_packet_ts else 0
        rssi = t.rssi if t else "--"
        self.diag_stats.configure(
            text=f"Packets: {self.reader.packet_count}  |  "
                 f"Dropped: {self._dropped_total}  |  "
                 f"Filtered: {self._filtered_count}  |  "
                 f"Last age: {age:.2f}s  |  "
                 f"RSSI: {rssi} dBm")
        if t is None:
            return
        self.diag_decoded.configure(state=tk.NORMAL)
        self.diag_decoded.delete("1.0", tk.END)
        fields = [
            ("packet_type", t.packet_type), ("time_s", f"{t.time_s:.3f}"),
            ("state", f"{t.state} ({STATE_NAMES.get(t.state, '?')})"),
            ("alt", f"{t.alt:.2f}"), ("max_alt", f"{t.max_alt:.2f}"),
            ("vel", f"{t.vel:.2f}"), ("accel", f"{t.accel:.2f}"),
            ("rssi", t.rssi), ("snr", f"{t.snr:.1f}"),
            ("pyro", t.pyro), ("remote_safe", t.remote_safe),
            ("vbat", f"{t.vbat:.2f}"), ("cont1", t.cont1), ("cont2", t.cont2),
            ("temp_c", f"{t.temp_c:.2f}"), ("pres_hpa", f"{t.pres_hpa:.1f}"),
            ("ax", f"{t.ax:.2f}"), ("ay", f"{t.ay:.2f}"), ("az", f"{t.az:.2f}"),
            ("gx", f"{t.gx:.2f}"), ("gy", f"{t.gy:.2f}"), ("gz", f"{t.gz:.2f}"),
        ]
        for name, val in fields:
            self.diag_decoded.insert(tk.END, f"  {name:14s} = {val}\n")
        self.diag_decoded.configure(state=tk.DISABLED)


# ── Entry point ────────────────────────────────────────────────
def main():
    root = tk.Tk()
    app = GroundStationApp(root)
    root.protocol("WM_DELETE_WINDOW", lambda: (
        app._stop_recording(), app.reader.disconnect(), root.destroy()))
    root.mainloop()


if __name__ == "__main__":
    main()
