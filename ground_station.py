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
import threading
import time
import csv
import math
import tkinter as tk
from tkinter import ttk, filedialog
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

        self._build_ui()
        self._tick()

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

        main = ttk.Frame(self.root, style="Dark.TFrame")
        main.pack(fill=tk.BOTH, expand=True, padx=8, pady=6)

        # ── Menu bar ──
        menubar = tk.Menu(self.root)
        filemenu = tk.Menu(menubar, tearoff=0)
        filemenu.add_command(label="Load Flight CSV...", command=self._load_flight)
        filemenu.add_command(label="Load Overlay...", command=self._load_overlay)
        filemenu.add_command(label="Clear Overlays", command=self._clear_overlays)
        filemenu.add_separator()
        filemenu.add_command(label="Exit", command=lambda: (
            self._stop_recording(), self.reader.disconnect(), self.root.destroy()))
        menubar.add_cascade(label="File", menu=filemenu)
        self.root.config(menu=menubar)

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
            name = os.path.basename(path)
            self.safe_status.configure(
                text=f"Loaded: {name} ({len(data['t'])} points)",
                foreground="#00ff88")
            self.conn_status.configure(text=f"REPLAY: {name}",
                                       foreground="#00bcd4")
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
        packets = self.reader.drain()
        log_lines = self.reader.drain_log()

        # Append raw log
        if log_lines:
            self.log_text.configure(state=tk.NORMAL)
            for line in log_lines:
                self.log_text.insert(tk.END, line + "\n")
            lc = int(self.log_text.index("end-1c").split(".")[0])
            if lc > 200:
                self.log_text.delete("1.0", f"{lc - 200}.0")
            self.log_text.see(tk.END)
            self.log_text.configure(state=tk.DISABLED)

        # Process packets
        for t in packets:
            if self.t_offset is None:
                self.t_offset = t.time_s

            ts = t.time_s - self.t_offset
            self.t_hist.append(ts)
            self.alt_hist.append(t.alt)
            self.vel_hist.append(t.vel)
            self.acc_hist.append(t.accel)
            self.rssi_hist.append(t.rssi)
            gyro_mag = math.sqrt(t.gx**2 + t.gy**2 + t.gz**2)
            self.gyro_hist.append(gyro_mag)

            # Peak tracking
            if t.packet_type == "F":
                # Use firmware-tracked max_alt (100 Hz, more accurate)
                self.peak_alt = max(self.peak_alt, t.max_alt, t.alt)
            else:
                self.peak_alt = max(self.peak_alt, t.alt)
            self.peak_vel   = max(self.peak_vel, abs(t.vel))
            self.peak_accel = max(self.peak_accel, t.accel)

            # CSV recording
            self._record_telemetry(t, ts)

            # Audio alerts
            self._check_alerts(t)

            self.last_telem = t

        # Update card displays
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

        # Disconnect detection
        if not self.reader.connected and self.btn_connect.cget("text") == "Disconnect":
            self.btn_connect.configure(text="Connect")
            self.conn_status.configure(text="DISCONNECTED (lost)",
                                       foreground="#ff8800")

        # Graphs (throttled to 5 Hz)
        self._graph_counter += 1
        if self._graph_counter >= 4 and len(self.t_hist) > 1:
            self._graph_counter = 0
            self._redraw_graphs()

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


# ── Entry point ────────────────────────────────────────────────
def main():
    root = tk.Tk()
    app = GroundStationApp(root)
    root.protocol("WM_DELETE_WINDOW", lambda: (
        app._stop_recording(), app.reader.disconnect(), root.destroy()))
    root.mainloop()


if __name__ == "__main__":
    main()
