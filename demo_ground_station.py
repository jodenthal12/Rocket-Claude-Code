"""
Standalone fake ground station GUI for the water rocket.

Runs a self-contained 22.7 m flight simulation with realistic noise.
No Arduino, no serial port — just `python3 demo_ground_station.py`.

Flow:
  Boot -> READY (sitting on pad)
  Press ARM   -> ARMED, auto-launches in 3 s
  BOOST -> COAST -> APOGEE 22.7 m (pyro fires) -> DESCENT -> LANDED
  Press RESET to fly again

Requires: Python 3 (tkinter is in the stdlib).
"""

import math
import random
import time
import tkinter as tk
from tkinter import ttk

# ── Flight states ────────────────────────────────────────────────
ST_IDLE, ST_READY, ST_ARMED, ST_BOOST, ST_COAST, ST_DESCENT, ST_LANDED = range(7)
STATE_NAMES = {
    ST_IDLE: "IDLE", ST_READY: "READY", ST_ARMED: "ARMED",
    ST_BOOST: "BOOST", ST_COAST: "COAST", ST_DESCENT: "DESCENT",
    ST_LANDED: "LANDED",
}
STATE_COLORS = {
    ST_IDLE: "#888888", ST_READY: "#00cc88", ST_ARMED: "#ffaa00",
    ST_BOOST: "#ff4444", ST_COAST: "#ff8800", ST_DESCENT: "#4488ff",
    ST_LANDED: "#888888",
}

# ── Flight profile (22.7 m apogee) ───────────────────────────────
ARM_TO_LAUNCH_S = 3.0
BOOST_DUR_S     = 0.25
BURN_VEL        = 19.9        # m/s at burnout
BURN_ALT        = 2.49        # m at burnout
COAST_DUR_S     = 2.03        # to apogee
APOGEE_M        = 22.7
DESCENT_DUR_S   = 5.04
DESCENT_RATE    = 4.5         # m/s


class FlightSim:
    def __init__(self):
        self.reset()

    def reset(self):
        self.state = ST_READY
        self.t_arm = None
        self.t_launch = None
        self.t_burnout = None
        self.t_apogee = None
        self.max_alt = 0.0
        self.pyro = False
        self.remote_safe = False
        self.arm_switch = False
        self.boot_t = time.monotonic()

    def arm(self):
        if self.state in (ST_READY, ST_LANDED):
            self.reset()
            self.state = ST_ARMED
            self.t_arm = time.monotonic()
            self.arm_switch = True

    def safe(self):
        self.remote_safe = True
        if self.state == ST_ARMED:
            self.state = ST_READY
            self.arm_switch = False

    def unsafe(self):
        self.remote_safe = False

    def tick(self):
        """Advance state machine, return current telemetry dict."""
        now = time.monotonic()

        if self.state == ST_ARMED and not self.remote_safe:
            if (now - self.t_arm) >= ARM_TO_LAUNCH_S:
                self.state = ST_BOOST
                self.t_launch = now
        elif self.state == ST_BOOST:
            if (now - self.t_launch) >= BOOST_DUR_S:
                self.state = ST_COAST
                self.t_burnout = now
        elif self.state == ST_COAST:
            if (now - self.t_burnout) >= COAST_DUR_S:
                self.state = ST_DESCENT
                self.t_apogee = now
                self.pyro = True
        elif self.state == ST_DESCENT:
            if (now - self.t_apogee) >= DESCENT_DUR_S:
                self.state = ST_LANDED

        # Compute physics
        alt = 0.0
        vel = 0.0
        acc = 1.0
        gx = gy = gz = 0.0

        if self.state == ST_READY:
            alt = random.uniform(-0.1, 0.1)
            vel = random.uniform(-0.02, 0.02)
            acc = 1.0 + random.uniform(-0.02, 0.02)
            gx, gy, gz = (random.uniform(-0.5, 0.5) for _ in range(3))
        elif self.state == ST_ARMED:
            alt = random.uniform(-0.1, 0.1)
            vel = random.uniform(-0.02, 0.02)
            acc = 1.0 + random.uniform(-0.03, 0.03)
            gx, gy, gz = (random.uniform(-0.6, 0.6) for _ in range(3))
        elif self.state == ST_BOOST:
            t_sec = now - self.t_launch
            boost_acc = BURN_VEL / BOOST_DUR_S        # ~79.6 m/s²
            vel = boost_acc * t_sec
            alt = 0.5 * boost_acc * t_sec * t_sec
            acc = (boost_acc / 9.81) + random.uniform(-0.6, 0.6)
            gx = random.uniform(-15, 15); gy = random.uniform(-15, 15)
            gz = random.uniform(-8, 8)
        elif self.state == ST_COAST:
            dt = now - self.t_burnout
            vel = BURN_VEL - 9.81 * dt
            alt = BURN_ALT + BURN_VEL * dt - 0.5 * 9.81 * dt * dt
            acc = 1.0 + random.uniform(-0.15, 0.15)
            gx = random.uniform(-4, 4); gy = random.uniform(-4, 4)
            gz = 22.0 + random.uniform(-4, 4)
        elif self.state == ST_DESCENT:
            dt = now - self.t_apogee
            vel = -DESCENT_RATE + random.uniform(-0.3, 0.3)
            alt = max(0.0, APOGEE_M - DESCENT_RATE * dt)
            acc = 1.0 + random.uniform(-0.25, 0.25)
            gx = random.uniform(-50, 50); gy = random.uniform(-50, 50)
            gz = random.uniform(-30, 30)
        elif self.state == ST_LANDED:
            alt = random.uniform(-0.1, 0.1)
            vel = random.uniform(-0.05, 0.05)
            acc = 1.0 + random.uniform(-0.03, 0.03)
            gx, gy, gz = (random.uniform(-0.5, 0.5) for _ in range(3))

        alt += random.uniform(-0.15, 0.15)
        if alt > self.max_alt:
            self.max_alt = alt

        return {
            "t":     now - self.boot_t,
            "state": self.state,
            "alt":   alt,
            "max":   self.max_alt,
            "vel":   vel,
            "acc":   acc,
            "pyro":  self.pyro,
            "safe":  self.remote_safe,
            "arm":   self.arm_switch,
            "vbat":  8.05 + random.uniform(-0.05, 0.05),
            "cont1": 1500 + int(random.uniform(-30, 30)),
            "cont2": 1500 + int(random.uniform(-30, 30)),
            "temp":  22.0 + random.uniform(-0.5, 0.5),
            "rssi":  -62 + int(random.uniform(-4, 4)),
            "snr":   9.5 + random.uniform(-1.5, 1.5),
            "gx": gx, "gy": gy, "gz": gz,
        }


# ── GUI ──────────────────────────────────────────────────────────
class GroundStation:
    def __init__(self, root):
        self.root = root
        root.title("Water Rocket Ground Station")
        root.configure(bg="#0a0a14")
        root.geometry("900x680")

        self.sim = FlightSim()
        self.alt_history: list[tuple[float, float]] = []
        self.history_start = time.monotonic()

        self._build_ui()
        self._tick()

    def _mk_label(self, parent, text, font_sz=11, fg="#e0e0e0", bg="#0a0a14"):
        return tk.Label(parent, text=text, font=("Consolas", font_sz),
                        fg=fg, bg=bg)

    def _build_ui(self):
        # ── Header ──
        hdr = tk.Frame(self.root, bg="#0a0a14")
        hdr.pack(fill=tk.X, padx=10, pady=(10, 4))
        tk.Label(hdr, text="WATER ROCKET TELEMETRY",
                 font=("Consolas", 16, "bold"),
                 fg="#00ddff", bg="#0a0a14").pack(side=tk.LEFT)
        self.status_lbl = tk.Label(hdr, text="LIVE",
                                   font=("Consolas", 12, "bold"),
                                   fg="#00ff88", bg="#0a0a14")
        self.status_lbl.pack(side=tk.RIGHT)

        # ── Main row: cards + plot ──
        main = tk.Frame(self.root, bg="#0a0a14")
        main.pack(fill=tk.BOTH, expand=True, padx=10, pady=4)

        # Left side: telemetry cards
        cards = tk.Frame(main, bg="#0a0a14")
        cards.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))

        self.cards = {}
        for label, key in [
            ("STATE",     "state"),
            ("ALT (m)",   "alt"),
            ("MAX (m)",   "max"),
            ("VEL (m/s)", "vel"),
            ("ACCEL (g)", "acc"),
            ("PYRO",      "pyro"),
            ("VBAT (V)",  "vbat"),
            ("RSSI",      "rssi"),
        ]:
            f = tk.Frame(cards, bg="#14142a", bd=1, relief=tk.SOLID)
            f.pack(fill=tk.X, pady=2)
            tk.Label(f, text=label, font=("Consolas", 9),
                     fg="#888888", bg="#14142a").pack(anchor=tk.W, padx=8, pady=(4, 0))
            val = tk.Label(f, text="—", font=("Consolas", 18, "bold"),
                           fg="#00ddff", bg="#14142a")
            val.pack(anchor=tk.W, padx=8, pady=(0, 6))
            self.cards[key] = val

        # Right side: altitude plot
        plot_frame = tk.Frame(main, bg="#14142a", bd=1, relief=tk.SOLID)
        plot_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        tk.Label(plot_frame, text="ALTITUDE", font=("Consolas", 10),
                 fg="#888888", bg="#14142a").pack(anchor=tk.W, padx=8, pady=4)
        self.canvas = tk.Canvas(plot_frame, bg="#0a0a14", highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))

        # ── Bottom: control buttons ──
        ctl = tk.Frame(self.root, bg="#0a0a14")
        ctl.pack(fill=tk.X, padx=10, pady=10)

        for txt, color, cmd in [
            ("ARM",         "#cc8800", self._arm),
            ("SAFE PYROS",  "#cc0000", self._safe),
            ("UNSAFE PYROS","#cc6600", self._unsafe),
            ("RESET",       "#444444", self._reset),
        ]:
            tk.Button(ctl, text=txt, font=("Consolas", 11, "bold"),
                      bg=color, fg="white", bd=0, padx=18, pady=10,
                      activebackground=color,
                      command=cmd).pack(side=tk.LEFT, padx=4)

        # ── Bottom status line ──
        self.status_line = tk.Label(self.root, text="",
                                    font=("Consolas", 9),
                                    fg="#666666", bg="#0a0a14",
                                    anchor=tk.W)
        self.status_line.pack(fill=tk.X, padx=10, pady=(0, 6))

    def _arm(self):    self.sim.arm()
    def _safe(self):   self.sim.safe()
    def _unsafe(self): self.sim.unsafe()
    def _reset(self):
        self.sim.reset()
        self.alt_history.clear()
        self.history_start = time.monotonic()

    def _tick(self):
        t = self.sim.tick()

        # Update cards
        self.cards["state"].configure(
            text=STATE_NAMES[t["state"]], fg=STATE_COLORS[t["state"]])
        self.cards["alt"].configure(text=f"{t['alt']:6.2f}")
        self.cards["max"].configure(text=f"{t['max']:6.2f}")
        self.cards["vel"].configure(text=f"{t['vel']:+6.2f}")
        self.cards["acc"].configure(text=f"{t['acc']:5.2f}")
        self.cards["pyro"].configure(
            text="FIRED" if t["pyro"] else "SAFE" if t["safe"] else "READY",
            fg="#ff4444" if t["pyro"] else ("#ffaa00" if t["safe"] else "#00cc88"))
        self.cards["vbat"].configure(text=f"{t['vbat']:5.2f}")
        self.cards["rssi"].configure(text=f"{t['rssi']:+4d} dB")

        # Update plot
        rel_t = time.monotonic() - self.history_start
        self.alt_history.append((rel_t, t["alt"]))
        # Keep last 20 seconds
        cutoff = rel_t - 20.0
        self.alt_history = [(x, y) for (x, y) in self.alt_history if x >= cutoff]
        self._draw_plot()

        # Status line
        self.status_line.configure(
            text=f"t={t['t']:6.2f}s  SNR={t['snr']:+4.1f}  "
                 f"cont1={t['cont1']}  cont2={t['cont2']}  "
                 f"temp={t['temp']:4.1f}°C  "
                 f"gx={t['gx']:+6.1f}  gy={t['gy']:+6.1f}  gz={t['gz']:+6.1f}")

        # 100 ms tick (10 Hz refresh, matches realistic LoRa cadence)
        self.root.after(100, self._tick)

    def _draw_plot(self):
        c = self.canvas
        c.delete("all")
        w = c.winfo_width()
        h = c.winfo_height()
        if w < 50 or h < 30 or not self.alt_history:
            return

        # Axes scaling
        max_y = max((a for _, a in self.alt_history), default=1.0)
        max_y = max(max_y, 25.0)   # always show at least 0-25m
        t_min = self.alt_history[0][0]
        t_max = max(self.alt_history[-1][0], t_min + 1.0)
        span_t = t_max - t_min

        # Gridlines
        for m in range(0, int(max_y) + 1, 5):
            y = h - (m / max_y) * (h - 20) - 10
            c.create_line(40, y, w - 10, y, fill="#222244")
            c.create_text(34, y, text=f"{m}", fill="#666688",
                          font=("Consolas", 8), anchor=tk.E)

        # Plot line
        pts = []
        for (ti, ai) in self.alt_history:
            x = 40 + (ti - t_min) / span_t * (w - 50)
            y = h - (max(0, ai) / max_y) * (h - 20) - 10
            pts.extend((x, y))
        if len(pts) >= 4:
            c.create_line(*pts, fill="#00ddff", width=2, smooth=True)

        # Current value marker
        last_x, last_y = pts[-2], pts[-1]
        c.create_oval(last_x - 4, last_y - 4, last_x + 4, last_y + 4,
                      fill="#00ddff", outline="")


if __name__ == "__main__":
    root = tk.Tk()
    GroundStation(root)
    root.mainloop()
