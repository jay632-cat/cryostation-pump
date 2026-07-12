#%%
import csv
import datetime
import math
import re
import threading
import time
from collections import deque
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
import matplotlib.dates as mdates
import matplotlib.ticker as mticker

try:
    import serial.tools.list_ports  # type: ignore
    HAS_PYSERIAL = True
except Exception:
    serial = None
    HAS_PYSERIAL = False

try:
    import ls336_helpers  # type: ignore
    HAS_LS_HELPERS = True
except Exception:
    ls336_helpers = None
    HAS_LS_HELPERS = False

try:
    import pyvisa  # type: ignore
    HAS_PYVISA = True
except Exception:
    pyvisa = None
    HAS_PYVISA = False

try:
    from pump_helpers import (
        open_comm,
        close_comm,
        get_pressure_reading,
        get_pressure_units,
        get_turbo_speed,
        get_turbo_power,
        get_turbo_current,
        get_turbo_voltage,
        start_pump,
        stop_pump,
        get_tipseal_life,
        get_pump_status,
    )
    HAS_PUMP_HELPERS = True
except Exception:
    HAS_PUMP_HELPERS = False


class PumpReader(threading.Thread):
    """Background serial reader so the Tk thread stays responsive."""

    def __init__(self, ser, serial_lock):
        super().__init__(daemon=True)
        self.ser = ser
        self.serial_lock = serial_lock
        self.running = True
        self.lock = threading.Lock()
        self.data = {
            "pressure": None,
            "units": None,
            "turbo": None,
            "power": None,
            "current": None,
            "voltage": None,
            "tip_life": None,
            "timestamp": None,
            "error": None,
        }
        self.tip_last_sample_ts = None
        self.tip_sample_interval = 3600

    def run(self):
        while self.running:
            try:
                with self.serial_lock:
                    units = get_pressure_units(self.ser)
                    pressure = get_pressure_reading(self.ser)
                    turbo = get_turbo_speed(self.ser)
                    power = get_turbo_power(self.ser)
                    current = get_turbo_current(self.ser)
                    voltage = get_turbo_voltage(self.ser)

                    now_ts = time.time()
                    if self.tip_last_sample_ts is None or (now_ts - self.tip_last_sample_ts >= self.tip_sample_interval):
                        tip_life = get_tipseal_life(self.ser)
                        self.tip_last_sample_ts = now_ts
                    else:
                        tip_life = self.data.get("tip_life")

                with self.lock:
                    self.data["error"] = None
                    self.data["timestamp"] = now_ts
                    self.data["units"] = units
                    self.data["pressure"] = pressure
                    self.data["turbo"] = turbo
                    self.data["power"] = power
                    self.data["current"] = current
                    self.data["voltage"] = voltage
                    self.data["tip_life"] = tip_life
            except Exception as exc:
                with self.lock:
                    self.data["error"] = str(exc)
            time.sleep(0.5)

    def stop(self):
        self.running = False

    def get_data(self):
        with self.lock:
            return dict(self.data)


class IntegratedCryoGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Integrated LS336 + Pump Control")
        self.resizable(True, True)
        self._set_initial_window_size()

        self._closing = False

        self.ls_instrument = None
        self.ls_poll_job = None
        self.ls_plotting = False
        self.ls_poll_interval_ms = 1000
        self.ls_plot_start_time = None
        self.room_temp_return_active = False
        self.room_temp_ready_since = None
        self.temp_channels = [
            ("A", "Sample (A)"),
            ("B", "Rad Shield (B)"),
            ("C", "Arm (C)"),
            ("D", "CCR (D)"),
        ]
        self.ls_times = deque(maxlen=86400)
        self.ls_temp_buffers = {channel: deque(maxlen=86400) for channel, _ in self.temp_channels}

        self.ser = None
        self.serial_lock = threading.Lock()
        self.pump_reader = None
        self.pump_monitoring = False
        self.pump_update_job = None
        self.pump_plot_job = None
        self.pump_update_active = False
        self.pump_plot_active = False
        self.pump_update_interval_ms = 1000
        self.pump_plot_interval_ms = 5000

        self.pump_plot_maxlen = max(1, int(24 * 3600 / (self.pump_plot_interval_ms / 1000.0)))
        self.pump_times = deque(maxlen=self.pump_plot_maxlen)
        self.pump_pressures = deque(maxlen=self.pump_plot_maxlen)
        self.pump_turbo_values = deque(maxlen=self.pump_plot_maxlen)

        hr_maxlen = max(1, int(24 * 3600 / (self.pump_update_interval_ms / 1000.0)))
        self.pump_hr_times = deque(maxlen=hr_maxlen)
        self.pump_hr_pressures = deque(maxlen=hr_maxlen)
        self.pump_hr_turbos = deque(maxlen=hr_maxlen)

        self.last_pressure_value = None
        self.live_pressure_value = None
        self.tip_seal_warning_shown = False
        self.turbo_start_time = None

        self.start_wait_job = None
        self.start_wait_deadline = None
        self.start_wait_dialog = None
        self.start_wait_label = None
        self.pump_port_var = tk.StringVar(value="COM6")

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self.close_app)

        # Auto-connect attempts are scheduled to avoid blocking startup.
        self.after(150, self.ls_connect_silent)
        self.after(250, self.pump_connect)

    def _set_initial_window_size(self):
        # Prefer a large usable window while keeping the title bar and taskbar behavior predictable.
        try:
            screen_w = self.winfo_screenwidth()
            screen_h = self.winfo_screenheight()
            width = max(1280, int(screen_w * 0.95))
            height = max(820, int(screen_h * 0.92))
            x = max((screen_w - width) // 2, 0)
            y = max((screen_h - height) // 2, 0)
            self.geometry(f"{width}x{height}+{x}+{y}")
            self.minsize(1280, 820)
        except Exception:
            pass

    def _build_ui(self):
        root = ttk.Frame(self, padding=8)
        root.grid(row=0, column=0, sticky="nsew")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        root.columnconfigure(0, weight=0)
        root.columnconfigure(1, weight=1)
        root.rowconfigure(0, weight=1)

        left = ttk.Frame(root)
        left.grid(row=0, column=0, sticky="nsw", padx=(0, 8))

        right = ttk.Frame(root)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)

        header = ttk.Frame(left)
        header.pack(fill="x", pady=(0, 6))
        ttk.Label(header, text="Integrated Cryostation Panel", font=("Arial", 16, "bold")).pack(anchor="w")
        ttk.Label(header, text="LS336 + Pump Controller", font=("Arial", 11)).pack(anchor="w")

        self._build_pump_controls(left)
        self._build_ls_controls(left)

        pump_plot_box = ttk.LabelFrame(right, text="Pressure Plot", padding=6)
        pump_plot_box.grid(row=0, column=0, sticky="nsew", pady=(0, 6))
        pump_plot_box.rowconfigure(0, weight=1)
        pump_plot_box.columnconfigure(0, weight=1)

        ls_plot_box = ttk.LabelFrame(right, text="Temperature Plot", padding=6)
        ls_plot_box.grid(row=1, column=0, sticky="nsew")
        ls_plot_box.rowconfigure(0, weight=1)
        ls_plot_box.columnconfigure(0, weight=1)

        self._build_pump_plot(pump_plot_box)
        self._build_ls_plot(ls_plot_box)

    def _build_ls_controls(self, parent):
        ls_box = ttk.LabelFrame(parent, text="LS336 Temp Controller Controls", padding=6)
        ls_box.pack(fill="x", pady=(0, 8))

        conn_box = ttk.LabelFrame(ls_box, text="Connection", padding=6)
        conn_box.pack(fill="x")
        conn_box.columnconfigure(1, weight=1)

        ttk.Label(conn_box, text="Resource:").grid(row=0, column=0, sticky="w")
        self.ls_resource_var = tk.StringVar(value="GPIB0::12::INSTR")
        ttk.Entry(conn_box, textvariable=self.ls_resource_var).grid(row=0, column=1, sticky="ew", padx=(6, 6))

        self.ls_connect_btn = ttk.Button(conn_box, text="Connect", command=self.ls_connect)
        self.ls_connect_btn.grid(row=1, column=0, pady=(6, 0), sticky="w")
        self.ls_disconnect_btn = ttk.Button(conn_box, text="Disconnect", command=self.ls_disconnect, state="disabled")
        self.ls_disconnect_btn.grid(row=1, column=1, pady=(6, 0), sticky="w")

        self.ls_conn_status_var = tk.StringVar(value="Disconnected")
        self.ls_conn_status_label = ttk.Label(conn_box, textvariable=self.ls_conn_status_var, foreground="red")
        self.ls_conn_status_label.grid(row=2, column=0, columnspan=2, sticky="w", pady=(6, 0))

        temp_box = ttk.LabelFrame(ls_box, text="Temperature", padding=6)
        temp_box.pack(fill="x", pady=(6, 0))

        self.ls_temp_vars = {}
        for idx, (channel, label_text) in enumerate(self.temp_channels):
            ttk.Label(temp_box, text=f"{label_text}:").grid(row=idx, column=0, sticky="w")
            var = tk.StringVar(value="---")
            self.ls_temp_vars[channel] = var
            ttk.Label(temp_box, textvariable=var, font=("Arial", 12, "bold")).grid(row=idx, column=1, sticky="w", padx=(6, 0))

        self.ls_heater_status_vars = {}
        for offset, heater_channel in enumerate((1, 2)):
            ttk.Label(temp_box, text=f"Heater {heater_channel}:").grid(row=offset, column=2, sticky="w", padx=(12, 0))
            var = tk.StringVar(value="---")
            self.ls_heater_status_vars[heater_channel] = var
            ttk.Label(temp_box, textvariable=var).grid(row=offset, column=3, sticky="w", padx=(6, 0))

        plot_controls = ttk.LabelFrame(ls_box, text="Monitor", padding=6)
        plot_controls.pack(fill="x", pady=(6, 0))

        self.ls_start_btn = ttk.Button(plot_controls, text="Start Monitor", command=self.ls_start_monitor, state="disabled")
        self.ls_start_btn.grid(row=0, column=0, padx=(0, 6), sticky="w")
        self.ls_stop_btn = ttk.Button(plot_controls, text="Stop Monitor", command=self.ls_stop_monitor, state="disabled")
        self.ls_stop_btn.grid(row=0, column=1, padx=(0, 6), sticky="w")
        ttk.Button(plot_controls, text="Clear Plot", command=self.ls_clear_plot).grid(row=0, column=2, padx=(0, 6), sticky="w")
        ttk.Button(plot_controls, text="Save Plot CSV", command=self.ls_save_plot_csv).grid(row=0, column=3, sticky="w")

        set_box = ttk.LabelFrame(ls_box, text="Set Temperature", padding=6)
        set_box.pack(fill="x", pady=(6, 0))

        ttk.Label(set_box, text="Set (K):").grid(row=0, column=0, sticky="w")
        self.ls_set_temp_var = tk.StringVar(value="0")
        ttk.Entry(set_box, textvariable=self.ls_set_temp_var, width=10).grid(row=0, column=1, padx=(6, 6), sticky="w")

        ttk.Button(set_box, text="Set Temperature", command=self.ls_set_temperature).grid(row=0, column=2, padx=(6, 0))
        ttk.Button(set_box, text="Stop Heater", command=self.ls_stop_heater).grid(row=0, column=3, padx=(6, 0))
        ttk.Button(set_box, text="Return to RT for sample exchange", command=self.ls_return_to_rt).grid(
            row=1, column=0, columnspan=4, sticky="ew", pady=(8, 0)
        )

        self.ls_status_var = tk.StringVar(value="")
        ttk.Label(ls_box, textvariable=self.ls_status_var).pack(anchor="w", pady=(4, 0))

    def _build_pump_controls(self, parent):
        pump_box = ttk.LabelFrame(parent, text="Pump Controls", padding=6)
        pump_box.pack(fill="x")

        port_box = ttk.LabelFrame(pump_box, text="Serial Port", padding=6)
        port_box.pack(fill="x")
        ttk.Label(port_box, text="Pump COM Port:").pack(side="left")
        self.pump_port_combo = ttk.Combobox(port_box, textvariable=self.pump_port_var, state="normal", width=16)
        self.pump_port_combo.pack(side="left", padx=(6, 6))
        ttk.Button(port_box, text="Refresh Ports", command=self.refresh_pump_ports).pack(side="left")

        status_box = ttk.LabelFrame(pump_box, text="Connection Status", padding=6)
        status_box.pack(fill="x")

        row = ttk.Frame(status_box)
        row.pack(fill="x")
        ttk.Label(row, text="Turbo Pump:").pack(side="left")
        self.pump_conn_label = ttk.Label(row, text="Disconnected", foreground="red")
        self.pump_conn_label.pack(side="left", padx=(6, 0))

        pressure_box = ttk.LabelFrame(pump_box, text="Pressure Reading", padding=8)
        pressure_box.pack(fill="x", pady=(6, 0))

        self.pressure_label = ttk.Label(pressure_box, text="--", font=("Arial", 28, "bold"), foreground="blue")
        self.pressure_label.pack()
        self.units_label = ttk.Label(pressure_box, text="--", font=("Arial", 12))
        self.units_label.pack()

        turbo_row = ttk.Frame(pressure_box)
        turbo_row.pack()
        self.turbo_label = ttk.Label(turbo_row, text="Turbo: -- rpm")
        self.turbo_label.pack(side="left")
        self.turbo_status_label = ttk.Label(turbo_row, text="--", foreground="gray")
        self.turbo_status_label.pack(side="left", padx=(6, 0))

        self.power_label = ttk.Label(pressure_box, text="Power: -- W")
        self.power_label.pack()
        self.current_label = ttk.Label(pressure_box, text="Current: -- mA")
        self.current_label.pack()
        self.voltage_label = ttk.Label(pressure_box, text="Voltage: -- V")
        self.voltage_label.pack()
        self.tipseal_label = ttk.Label(pressure_box, text="Tip Seal Life: -- hr")
        self.tipseal_label.pack()

        controls_top = ttk.Frame(pump_box)
        controls_top.pack(fill="x", pady=(6, 0))
        ttk.Button(controls_top, text="Connect Pump", command=self.pump_connect).pack(side="left", padx=(0, 6))
        ttk.Button(controls_top, text="Disconnect Pump", command=self.pump_disconnect).pack(side="left", padx=(0, 6))
        ttk.Button(controls_top, text="Start Pump", command=self.do_start_pump).pack(side="left", padx=(0, 6))
        ttk.Button(controls_top, text="Stop Pump", command=self.do_stop_pump).pack(side="left")

        controls_bottom = ttk.Frame(pump_box)
        controls_bottom.pack(fill="x", pady=(6, 0))
        self.pump_start_button = ttk.Button(controls_bottom, text="Start Monitoring", command=self.pump_start_monitoring)
        self.pump_start_button.pack(side="left", padx=(0, 6))
        self.pump_stop_button = ttk.Button(controls_bottom, text="Stop Monitoring", command=self.pump_stop_monitoring, state="disabled")
        self.pump_stop_button.pack(side="left", padx=(0, 6))
        ttk.Button(controls_bottom, text="Save Plot CSV", command=self.pump_save_plot_csv).pack(side="left")

        self.refresh_pump_ports()

    def refresh_pump_ports(self):
        if not HAS_PYSERIAL:
            self.pump_port_combo["values"] = ()
            return
        try:
            ports = [p.device for p in serial.tools.list_ports.comports()]
        except Exception:
            ports = []

        if not ports:
            ports = [self.pump_port_var.get() or "COM6"]

        self.pump_port_combo["values"] = ports
        current = self.pump_port_var.get().strip()
        if current not in ports:
            self.pump_port_var.set(ports[0])

    def _build_ls_plot(self, parent):
        self.ls_fig = Figure(figsize=(7, 4), dpi=100)
        self.ls_ax = self.ls_fig.add_subplot(111)
        self.ls_ax.set_title("Temperature vs Time")
        self.ls_ax.set_xlabel("Time")
        self.ls_ax.set_ylabel("Temperature (K)")
        self.ls_ax.grid(True)
        self.ls_ax.xaxis.set_major_formatter(mticker.FuncFormatter(self._format_seconds))

        self.ls_plot_lines = {}
        colors = {
            "A": "tab:blue",
            "B": "tab:orange",
            "C": "tab:green",
            "D": "tab:red",
        }
        labels = {
            "A": "Sample (A)",
            "B": "Rad Shield (B)",
            "C": "Arm (C)",
            "D": "CCR (D)",
        }
        for channel, _ in self.temp_channels:
            line, = self.ls_ax.plot([], [], "-o", markersize=2, linewidth=1, color=colors[channel], label=labels[channel])
            self.ls_plot_lines[channel] = line
        self.ls_ax.legend(loc="best")

        self.ls_canvas = FigureCanvasTkAgg(self.ls_fig, master=parent)
        self.ls_canvas.get_tk_widget().grid(row=0, column=0, sticky="nsew")

    def _build_pump_plot(self, parent):
        self.pump_fig = Figure(figsize=(7, 4), dpi=100)
        self.pump_ax = self.pump_fig.add_subplot(111)
        self.pump_ax.set_title("Pressure vs Time")
        self.pump_ax.set_xlabel("Time")
        self.pump_ax.set_ylabel("Pressure")
        self.pump_ax.grid(True)
        self.pump_ax.xaxis_date()
        self.pump_ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
        self.pump_ax.xaxis.set_major_locator(mdates.AutoDateLocator())
        try:
            self.pump_ax.set_yscale("log")
            self.pump_ax.set_ylim(2e-7, 1e3)
        except Exception:
            pass
        self.pump_line, = self.pump_ax.plot([], [], "-o", markersize=3)

        self.pump_canvas = FigureCanvasTkAgg(self.pump_fig, master=parent)
        self.pump_canvas.get_tk_widget().grid(row=0, column=0, sticky="nsew")

    def _format_seconds(self, x, pos=None):
        try:
            h = int(x // 3600)
            m = int((x % 3600) // 60)
            s = int(x % 60)
            return f"{h:02d}:{m:02d}:{s:02d}"
        except Exception:
            return ""

    def _parse_float(self, value):
        if value is None:
            return None
        m = re.search(r"[-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?", str(value))
        if not m:
            return None
        try:
            return float(m.group(0))
        except Exception:
            return None

    # ------------------------- LS336 Logic -------------------------

    def ls_connect_silent(self):
        if self._closing:
            return
        self.ls_connect(silent=True)

    def ls_connect(self, silent=False):
        if self._closing:
            return

        if HAS_LS_HELPERS and hasattr(ls336_helpers, "open_connection"):
            try:
                helper_connection = ls336_helpers.open_connection()
                if isinstance(helper_connection, tuple) and len(helper_connection) >= 2:
                    self.ls_instrument = helper_connection[1]
                else:
                    self.ls_instrument = helper_connection

                helper_id = None
                try:
                    helper_id = self.ls_instrument.query("*IDN?")
                except Exception:
                    pass
                self._ls_after_connected((helper_id or "ls336_helpers").strip())
                return
            except Exception:
                self.ls_instrument = None

        if not HAS_PYVISA:
            if not silent:
                messagebox.showerror("Missing dependency", "pyvisa is required for direct LS336 connection.")
            return

        try:
            rm = pyvisa.ResourceManager()
            inst = rm.open_resource(self.ls_resource_var.get().strip())
            inst.write_termination = "\n"
            inst.read_termination = "\n"
            inst.timeout = 3000
            ident = None
            try:
                ident = inst.query("*IDN?")
            except Exception:
                pass
            self.ls_instrument = inst
            self._ls_after_connected((ident or self.ls_resource_var.get().strip()).strip())
        except Exception as exc:
            self.ls_instrument = None
            if not silent:
                messagebox.showerror("Connection error", f"Failed to open LS336 resource:\n{exc}")

    def _ls_after_connected(self, ident):
        self.ls_conn_status_var.set(f"Connected ({ident})")
        self.ls_conn_status_label.config(foreground="green")
        self.ls_connect_btn.config(state="disabled")
        self.ls_disconnect_btn.config(state="normal")
        self.ls_start_btn.config(state="normal")
        self.ls_start_polling()

    def ls_disconnect(self):
        self.ls_stop_polling()
        self.ls_stop_monitor()
        self._ls_reset_room_temp_return()
        if self.ls_instrument is not None:
            try:
                if hasattr(self.ls_instrument, "close"):
                    self.ls_instrument.close()
            except Exception:
                pass
        self.ls_instrument = None

        self.ls_connect_btn.config(state="normal")
        self.ls_disconnect_btn.config(state="disabled")
        self.ls_start_btn.config(state="disabled")
        self.ls_stop_btn.config(state="disabled")
        self.ls_conn_status_var.set("Disconnected")
        self.ls_conn_status_label.config(foreground="red")

        for var in self.ls_temp_vars.values():
            var.set("---")
        for var in self.ls_heater_status_vars.values():
            var.set("---")

    def _ls_read_channel_temp(self, channel):
        if self.ls_instrument is None:
            return None
        try:
            if HAS_LS_HELPERS and hasattr(ls336_helpers, "get_temp"):
                return float(ls336_helpers.get_temp(self.ls_instrument, channel))
        except Exception:
            pass
        try:
            raw = self.ls_instrument.query(f"KRDG? {channel}")
            return float(str(raw).split(",")[0].strip())
        except Exception:
            return None

    def _ls_read_once(self):
        if self._closing or self.ls_instrument is None:
            return

        try:
            readings = {}
            for channel, _ in self.temp_channels:
                readings[channel] = self._ls_read_channel_temp(channel)

            for channel, value in readings.items():
                if value is None or not math.isfinite(value):
                    self.ls_temp_vars[channel].set("Read error")
                else:
                    self.ls_temp_vars[channel].set(f"{value:.3f} K")

            heater_status_map = {0: "Off", 1: "Low", 2: "Medium", 3: "High"}
            for heater_channel in (1, 2):
                try:
                    if HAS_LS_HELPERS and hasattr(ls336_helpers, "get_heater_status"):
                        raw = ls336_helpers.get_heater_status(self.ls_instrument, heater_channel)
                    else:
                        raw = self.ls_instrument.query(f"HTRST? {heater_channel}")
                    value = int(raw)
                    self.ls_heater_status_vars[heater_channel].set(heater_status_map.get(value, str(value)))
                except Exception:
                    self.ls_heater_status_vars[heater_channel].set("Read error")

            self._ls_update_room_temp_return(readings)

            if self.ls_plotting:
                now = datetime.datetime.now()
                if self.ls_plot_start_time is None:
                    self.ls_plot_start_time = now
                seconds = (now - self.ls_plot_start_time).total_seconds()
                self.ls_times.append(seconds)
                for channel, _ in self.temp_channels:
                    value = readings.get(channel)
                    self.ls_temp_buffers[channel].append(value if value is not None else float("nan"))
                self._ls_update_plot()
        except Exception as exc:
            self.ls_status_var.set(f"Read failed: {exc}")

    def _ls_update_plot(self):
        if not self.ls_times:
            return
        xs = list(self.ls_times)
        all_values = []
        for channel, line in self.ls_plot_lines.items():
            ys = list(self.ls_temp_buffers[channel])
            line.set_data(xs[: len(ys)], ys)
            all_values.extend([v for v in ys if v is not None and math.isfinite(v)])

        self.ls_ax.set_xlim(max(0.0, min(xs) - 1.0), max(xs) + 1.0)
        if all_values:
            ymin = min(all_values)
            ymax = max(all_values)
            yrange = ymax - ymin if ymax > ymin else 1.0
            self.ls_ax.set_ylim(ymin - 0.1 * yrange, ymax + 0.1 * yrange)
        self.ls_canvas.draw_idle()

    def ls_start_polling(self):
        if self._closing or self.ls_instrument is None:
            return
        if self.ls_poll_job is not None:
            return

        def _loop():
            self.ls_poll_job = None
            if self._closing or self.ls_instrument is None:
                return
            self._ls_read_once()
            self.ls_poll_job = self.after(self.ls_poll_interval_ms, _loop)

        self.ls_poll_job = self.after(0, _loop)

    def ls_stop_polling(self):
        if self.ls_poll_job is not None:
            try:
                self.after_cancel(self.ls_poll_job)
            except Exception:
                pass
            self.ls_poll_job = None

    def ls_start_monitor(self):
        if self.ls_instrument is None:
            messagebox.showwarning("Not connected", "Connect LS336 first.")
            return
        if self.ls_plotting:
            return
        self.ls_plotting = True
        self.ls_start_btn.config(state="disabled")
        self.ls_stop_btn.config(state="normal")
        self.ls_clear_plot()

    def ls_stop_monitor(self):
        if not self.ls_plotting:
            return
        self.ls_plotting = False
        self.ls_start_btn.config(state="normal")
        self.ls_stop_btn.config(state="disabled")

    def ls_clear_plot(self):
        self.ls_plot_start_time = None
        self.ls_times.clear()
        for channel, _ in self.temp_channels:
            self.ls_temp_buffers[channel].clear()
            self.ls_plot_lines[channel].set_data([], [])
        self.ls_canvas.draw_idle()
        self.ls_status_var.set("Temperature plot cleared")

    def ls_save_plot_csv(self):
        xs = list(self.ls_times)
        if not xs:
            messagebox.showinfo("No data", "No LS336 plot data to save.")
            return

        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=(("CSV files", "*.csv"), ("All files", "*.*")),
            initialfile="temperature_plot.csv",
        )
        if not path:
            return

        try:
            with open(path, "w", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(["time_s", "sample_A_K", "rad_shield_B_K", "arm_C_K", "ccr_D_K"])
                series = {channel: list(self.ls_temp_buffers[channel]) for channel, _ in self.temp_channels}
                for idx, t in enumerate(xs):
                    row = [f"{t:.3f}"]
                    for channel, _ in self.temp_channels:
                        v = series[channel][idx] if idx < len(series[channel]) else float("nan")
                        row.append("" if v is None or not math.isfinite(v) else f"{v:.6f}")
                    writer.writerow(row)
            messagebox.showinfo("Saved", f"LS336 CSV saved to {path}")
        except Exception as exc:
            messagebox.showerror("Save error", f"Failed to save LS336 CSV:\n{exc}")

    def ls_set_temperature(self):
        if self.ls_instrument is None:
            messagebox.showwarning("Not connected", "Connect to LS336 before setting temperature.")
            return

        try:
            temp = float(self.ls_set_temp_var.get())
        except Exception:
            messagebox.showerror("Invalid input", "Setpoint must be a number (K).")
            return

        if not messagebox.askyesno(
            "Confirm CCR",
            "Is the CCR on?\n\nSelect No to cancel.\n\nALL NON-RT samples, INCLUDING >300 K temps, require full cooldown to base pressure before heating.",
        ):
            return

        try:
            if not HAS_LS_HELPERS or not hasattr(ls336_helpers, "set_chuck_temp"):
                messagebox.showerror("Missing helper", "ls336_helpers.set_chuck_temp() is required.")
                return
            ls336_helpers.set_chuck_temp(self.ls_instrument, temp)
            self.ls_status_var.set(f"Setpoint sent: {temp:.3f} K")
        except Exception as exc:
            messagebox.showerror("Error", f"Failed to set temperature:\n{exc}")

    def ls_return_to_rt(self):
        if self.ls_instrument is None:
            messagebox.showwarning("Not connected", "Connect to LS336 before returning to room temperature.")
            return
        if not HAS_LS_HELPERS or not hasattr(ls336_helpers, "go_to_room_temp"):
            messagebox.showerror("Missing helper", "ls336_helpers.go_to_room_temp() is required.")
            return

        if not messagebox.askyesno("Confirm CCR", "Is the CCR off?\n\nSelect No to cancel."):
            return

        try:
            self.room_temp_return_active = True
            self.room_temp_ready_since = None
            ls336_helpers.go_to_room_temp(self.ls_instrument)
            self.ls_status_var.set("Return-to-room-temperature routine started")
        except Exception as exc:
            self._ls_reset_room_temp_return()
            messagebox.showerror("Error", f"Failed to return to room temperature:\n{exc}")

    def _ls_reset_room_temp_return(self):
        self.room_temp_return_active = False
        self.room_temp_ready_since = None

    def _ls_turn_off_room_temp_heaters(self):
        if self.ls_instrument is None:
            raise RuntimeError("LS336 connection is unavailable")
        if not HAS_LS_HELPERS or not hasattr(ls336_helpers, "set_heater_range"):
            raise RuntimeError("ls336_helpers.set_heater_range() is required.")

        ls336_helpers.set_heater_range(self.ls_instrument, 1, 0)
        ls336_helpers.set_heater_range(self.ls_instrument, 2, 0)

        if hasattr(ls336_helpers, "set_temp_setpt"):
            ls336_helpers.set_temp_setpt(self.ls_instrument, 1, 295)
            ls336_helpers.set_temp_setpt(self.ls_instrument, 2, 295)

    def _ls_finish_room_temp_return(self):
        self._ls_reset_room_temp_return()
        try:
            self._ls_turn_off_room_temp_heaters()
            self.ls_status_var.set("Chamber is at room temperature; heaters turned off")
            messagebox.showinfo("Room Temperature Reached", "The chamber is at room temperature.")
        except Exception as exc:
            messagebox.showerror("Error", f"Failed to turn off heaters after reaching room temperature:\n{exc}")

    def _ls_update_room_temp_return(self, readings):
        if not self.room_temp_return_active or self.ls_instrument is None:
            return

        sample_temp = readings.get("A")
        rad_temp = readings.get("B")
        in_range = (
            sample_temp is not None and rad_temp is not None and
            295.0 <= sample_temp <= 300.0 and
            295.0 <= rad_temp <= 300.0
        )

        if not in_range:
            self.room_temp_ready_since = None
            return

        now = time.time()
        if self.room_temp_ready_since is None:
            self.room_temp_ready_since = now
            self.ls_status_var.set("Waiting for 15 minutes of stable room temperature")
            return

        if now - self.room_temp_ready_since >= 15 * 60:
            self._ls_finish_room_temp_return()

    def ls_stop_heater(self):
        if self.ls_instrument is None:
            messagebox.showwarning("Not connected", "Connect to LS336 before stopping heater.")
            return

        if not HAS_LS_HELPERS:
            messagebox.showerror("Missing helper", "ls336_helpers is required to stop heater.")
            return

        try:
            if hasattr(ls336_helpers, "set_heater_range"):
                ls336_helpers.set_heater_range(self.ls_instrument, 1, 0)
                ls336_helpers.set_heater_range(self.ls_instrument, 2, 0)
            else:
                messagebox.showerror("Missing helper", "ls336_helpers.set_heater_range() is required.")
                return

            if hasattr(ls336_helpers, "set_temp_setpt"):
                ls336_helpers.set_temp_setpt(self.ls_instrument, 1, 295)
                ls336_helpers.set_temp_setpt(self.ls_instrument, 2, 295)
            self.ls_status_var.set("Heaters stopped; setpoints moved to 295 K")
        except Exception as exc:
            messagebox.showerror("Error", f"Failed to stop heaters:\n{exc}")

    # -------------------------- Pump Logic -------------------------

    def pump_connect(self):
        if self._closing:
            return
        if not HAS_PUMP_HELPERS:
            self.pump_conn_label.config(text="Missing pump_helpers", foreground="red")
            return
        if self.ser is not None:
            return

        try:
            port_name = self.pump_port_var.get().strip() or "COM6"
            self.ser = open_comm(port_name, reply_timeout=0.25)
            units = get_pressure_units(self.ser)
            units_norm = str(units).strip().lower().rstrip(".")
            if units_norm == "get units failed":
                self.pump_conn_label.config(text="Disconnected", foreground="red")
                messagebox.showwarning("Connection Status", "Pump not detected (units read failed).")
                try:
                    close_comm(self.ser)
                except Exception:
                    pass
                self.ser = None
                return

            self.pump_conn_label.config(text=f"Connected ({port_name})", foreground="green")

            self.pump_reader = PumpReader(self.ser, self.serial_lock)
            self.pump_reader.start()
            self.after(1200, self._pump_initial_display_update)
        except Exception as exc:
            self.pump_conn_label.config(text="Connection Failed", foreground="red")
            messagebox.showerror("Connection Error", f"Failed to connect to pump:\n{exc}")
            self.ser = None

    def pump_disconnect(self):
        self.pump_stop_monitoring()
        self._close_start_wait_dialog()
        self.pump_update_active = False
        self.pump_plot_active = False

        if self.pump_reader is not None:
            self.pump_reader.stop()
            self.pump_reader.join(timeout=2)
            self.pump_reader = None

        if self.ser is not None:
            try:
                close_comm(self.ser)
            except Exception:
                pass
            self.ser = None

        self.pump_conn_label.config(text="Disconnected", foreground="red")

    def _pump_initial_display_update(self):
        if self._closing or self.pump_reader is None or self.ser is None:
            return
        try:
            data = self.pump_reader.get_data()
            tip_life = data.get("tip_life")
            if tip_life is not None:
                self.tipseal_label.config(text=f"Tip Seal Life: {tip_life} hr")
                tip_value = self._parse_float(tip_life)
                if tip_value is not None and tip_value > 5000:
                    self.tipseal_label.config(foreground="red")
                    if not self.tip_seal_warning_shown:
                        messagebox.showwarning("Tip Seal Warning", "Tip seal life is over 5000 hours. Please change the tip seal.")
                        self.tip_seal_warning_shown = True
                else:
                    self.tipseal_label.config(foreground="black")
        except Exception:
            pass

    def pump_start_monitoring(self):
        if self.ser is None:
            messagebox.showwarning("Warning", "Pump not connected")
            return

        self.pump_monitoring = True
        self.pump_start_button.config(state="disabled")
        self.pump_stop_button.config(state="normal")

        self.pump_times.clear()
        self.pump_pressures.clear()
        self.pump_turbo_values.clear()
        self.pump_hr_times.clear()
        self.pump_hr_pressures.clear()
        self.pump_hr_turbos.clear()
        self.last_pressure_value = None

        self.pump_line.set_data([], [])
        self.pump_canvas.draw_idle()

        self._pump_schedule_update_loop()
        self._pump_schedule_plot_loop()

    def pump_stop_monitoring(self):
        self.pump_monitoring = False
        self.pump_start_button.config(state="normal")
        self.pump_stop_button.config(state="disabled")

        if self.pump_update_job is not None:
            try:
                self.after_cancel(self.pump_update_job)
            except Exception:
                pass
            self.pump_update_job = None
        self.pump_update_active = False

        if self.pump_plot_job is not None:
            try:
                self.after_cancel(self.pump_plot_job)
            except Exception:
                pass
            self.pump_plot_job = None
        self.pump_plot_active = False

    def _pump_is_live(self):
        return self.pump_monitoring or (self.start_wait_dialog is not None)

    def _pump_schedule_update_loop(self):
        if self._closing:
            return
        if self.pump_update_active:
            return
        if self.pump_update_job is None:
            self.pump_update_active = True
            self.pump_update_job = self.after(0, self._pump_update_loop)

    def _pump_update_loop(self):
        self.pump_update_job = None
        if self._closing or not self._pump_is_live() or self.ser is None or self.pump_reader is None:
            self.pump_update_active = False
            return

        try:
            data = self.pump_reader.get_data()
            if data.get("error"):
                self._pump_show_disconnected_state()
            else:
                units = data.get("units")
                units_norm = str(units).strip().lower().rstrip(".") if units else ""
                if units_norm == "get units failed":
                    self._pump_show_disconnected_state()
                else:
                    self.pump_conn_label.config(text="Connected", foreground="green")
                    pressure = data.get("pressure")
                    turbo = data.get("turbo")
                    power = data.get("power")
                    current = data.get("current")
                    voltage = data.get("voltage")
                    tip_life = data.get("tip_life")

                    self.pressure_label.config(text=pressure, foreground="blue")
                    self.units_label.config(text=units)
                    self.turbo_label.config(text=f"Turbo: {turbo} rpm")
                    self.power_label.config(text=f"Power: {power} W")
                    self.current_label.config(text=f"Current: {current} mA")
                    self.voltage_label.config(text=f"Voltage: {voltage} V")

                    turbo_value = self._parse_float(turbo)
                    if turbo_value is not None and turbo_value > 70000:
                        self.turbo_status_label.config(text="At Speed", foreground="green")
                    elif turbo_value is not None and turbo_value == 0:
                        self.turbo_status_label.config(text="Stopped", foreground="red")
                    elif turbo_value is not None and 0 < turbo_value <= 70000:
                        self.turbo_status_label.config(text="Starting/Stopping", foreground="goldenrod")
                    else:
                        self.turbo_status_label.config(text="--", foreground="gray")

                    if tip_life is not None:
                        self.tipseal_label.config(text=f"Tip Seal Life: {tip_life} hr")
                        tip_value = self._parse_float(tip_life)
                        if tip_value is not None and tip_value > 5000:
                            self.tipseal_label.config(foreground="red")
                            if not self.tip_seal_warning_shown:
                                messagebox.showwarning("Tip Seal Warning", "Tip seal life is over 5000 hours. Please change the tip seal.")
                                self.tip_seal_warning_shown = True
                        else:
                            self.tipseal_label.config(foreground="black")

                    pressure_num = self._parse_float(pressure)
                    if pressure_num is not None:
                        self.last_pressure_value = pressure_num
                        self.live_pressure_value = pressure_num
                        if self.start_wait_dialog is not None:
                            self._update_start_wait_message(pressure_num)

                        ts = time.time()
                        self.pump_hr_times.append(ts)
                        self.pump_hr_pressures.append(pressure_num)
                        self.pump_hr_turbos.append(turbo_value)
        except Exception:
            self._pump_show_disconnected_state()

        if self._pump_is_live() and not self._closing:
            self.pump_update_job = self.after(self.pump_update_interval_ms, self._pump_update_loop)
        else:
            self.pump_update_active = False

    def _pump_show_disconnected_state(self):
        self.pump_conn_label.config(text="Disconnected", foreground="red")
        self.pressure_label.config(text="--", foreground="red")
        self.units_label.config(text="--")
        self.turbo_label.config(text="Turbo: -- rpm")
        self.turbo_status_label.config(text="--", foreground="gray")
        self.power_label.config(text="Power: -- W")
        self.current_label.config(text="Current: -- mA")
        self.voltage_label.config(text="Voltage: -- V")

    def _pump_schedule_plot_loop(self):
        if self._closing:
            return
        if self.pump_plot_active:
            return
        if self.pump_plot_job is None:
            self.pump_plot_active = True
            self.pump_plot_job = self.after(0, self._pump_plot_loop)

    def _pump_plot_loop(self):
        self.pump_plot_job = None
        if self._closing or not self._pump_is_live():
            self.pump_plot_active = False
            return

        now = time.time()
        cutoff = now - (self.pump_plot_interval_ms / 1000.0)
        values = [v for t, v in zip(self.pump_hr_times, self.pump_hr_pressures) if t >= cutoff]

        if values:
            avg = sum(values) / len(values)
            turbo_values = [v for t, v in zip(self.pump_hr_times, self.pump_hr_turbos) if t >= cutoff and v is not None]
            turbo_avg = sum(turbo_values) / len(turbo_values) if turbo_values else None
            self.pump_times.append(now)
            self.pump_pressures.append(avg)
            self.pump_turbo_values.append(turbo_avg)
        elif self.last_pressure_value is not None:
            self.pump_times.append(now)
            self.pump_pressures.append(self.last_pressure_value)
            self.pump_turbo_values.append(None)

        if self.pump_times:
            xs = mdates.date2num([datetime.datetime.fromtimestamp(t) for t in self.pump_times])
            ys = [v if (v is not None and v > 0) else float("nan") for v in self.pump_pressures]
            if any((v > 0) for v in self.pump_pressures if v is not None):
                self.pump_line.set_data(xs, ys)
                self.pump_ax.relim()
                self.pump_ax.autoscale_view()
                for label in self.pump_ax.get_xticklabels():
                    label.set_rotation(30)
                    label.set_ha("right")
                self.pump_canvas.draw_idle()

        if self._pump_is_live() and not self._closing:
            self.pump_plot_job = self.after(self.pump_plot_interval_ms, self._pump_plot_loop)
        else:
            self.pump_plot_active = False

    def do_start_pump(self):
        if self.ser is None:
            messagebox.showwarning("Warning", "Pump not connected")
            return
        if self.start_wait_dialog is not None:
            messagebox.showinfo("Pump Command", "Already waiting for pressure <5e-1 Torr.")
            return

        if not messagebox.askyesno("Valve Confirmation", "Are all valves in their correct state (open/closed)?"):
            return

        try:
            data = self.pump_reader.get_data() if self.pump_reader else {}
            turbo = data.get("turbo") if data else None
            if turbo is None:
                with self.serial_lock:
                    turbo = get_turbo_speed(self.ser)
            turbo_num = self._parse_float(turbo)
        except Exception as exc:
            messagebox.showerror("Turbo Read Error", f"Failed to read turbo speed:\n{exc}")
            return

        if turbo_num is None or turbo_num != 0:
            messagebox.showerror("Cannot Start Pump", f"Turbo speed must be 0 rpm before starting. Current speed: {turbo} rpm")
            return

        try:
            data = self.pump_reader.get_data() if self.pump_reader else {}
            pressure = data.get("pressure") if data else None
            if pressure is None:
                with self.serial_lock:
                    pressure = get_pressure_reading(self.ser)
            pnum = self._parse_float(pressure)
        except Exception as exc:
            messagebox.showerror("Pressure Read Error", f"Failed to read pressure:\n{exc}")
            return

        threshold = 5e-1
        if pnum is not None and pnum < threshold:
            self._send_start_command()
            return

        self.start_wait_deadline = time.time() + 10 * 60
        self._show_start_wait_dialog()
        self._pump_schedule_update_loop()
        self._pump_schedule_plot_loop()
        self._poll_pressure_then_start()

    def _send_start_command(self):
        if self.ser is None:
            messagebox.showwarning("Warning", "Pump not connected")
            return

        try:
            with self.serial_lock:
                status = get_pump_status(self.ser)
                turbo = get_turbo_speed(self.ser)
                turbo_num = self._parse_float(turbo)

            if turbo_num is not None and turbo_num == 0:
                with self.serial_lock:
                    ok = start_pump(self.ser)
                if not ok:
                    raise RuntimeError("Pump did not acknowledge start command")
                self.turbo_start_time = time.time()
                messagebox.showinfo("Pump Command", "Start command sent")
            else:
                messagebox.showwarning(
                    "Cannot Start Pump",
                    f"Pump not started because conditions not met:\nstatus='{status}'\nturbo='{turbo}'\nExpected: status='stopped' and turbo=0",
                )
        except Exception as exc:
            messagebox.showerror("Pump Error", f"Failed to send start command:\n{exc}")

    def do_stop_pump(self):
        if self.ser is None:
            messagebox.showwarning("Warning", "Pump not connected")
            return

        if not messagebox.askyesno("Valve Confirmation", "Are all valves in their correct state (open/closed)?"):
            return

        try:
            data = self.pump_reader.get_data() if self.pump_reader else {}
            turbo = data.get("turbo") if data else None
            if turbo is None:
                with self.serial_lock:
                    turbo = get_turbo_speed(self.ser)
            turbo_num = self._parse_float(turbo)
        except Exception as exc:
            messagebox.showerror("Turbo Read Error", f"Failed to read turbo speed:\n{exc}")
            return

        if turbo_num is not None and 0 < turbo_num <= 70000:
            messagebox.showerror("Cannot Stop Pump", "Turbo is currently starting/stopping. Wait until it reaches at speed or 0 rpm.")
            return

        if self.turbo_start_time is not None:
            elapsed = time.time() - self.turbo_start_time
            if elapsed < 600:
                remain = int(600 - elapsed)
                messagebox.showerror("Cannot Stop Pump", f"Turbo cannot be stopped within 10 minutes of starting.\nTime remaining: {remain // 60:02d}:{remain % 60:02d}")
                return

        try:
            with self.serial_lock:
                stop_pump(self.ser)
            messagebox.showinfo("Pump Command", "Stop command sent")
        except Exception as exc:
            messagebox.showerror("Pump Error", f"Failed to send stop command:\n{exc}")

    def _show_start_wait_dialog(self):
        if self.start_wait_dialog is not None or self._closing:
            return

        dlg = tk.Toplevel(self)
        dlg.title("Waiting for Pressure")
        dlg.transient(self)
        dlg.grab_set()
        dlg.resizable(False, False)
        dlg.protocol("WM_DELETE_WINDOW", lambda: None)

        self.start_wait_label = ttk.Label(dlg, text="Waiting for pressure <5e-1 Torr for 10 min...", padding=16)
        self.start_wait_label.pack()

        self.start_wait_dialog = dlg
        self._update_start_wait_message(self.live_pressure_value)

    def _update_start_wait_message(self, pressure_value=None):
        if self.start_wait_label is None:
            return

        if self.start_wait_deadline is None:
            remaining_text = "--"
        else:
            remaining = max(int(self.start_wait_deadline - time.time()), 0)
            remaining_text = f"{remaining // 60:02d}:{remaining % 60:02d}"

        pressure_text = "--" if pressure_value is None else f"{pressure_value:.3e}"

        self.start_wait_label.config(
            text=(
                "Waiting for pressure <5e-1 Torr before turbo start\n"
                f"Current pressure: {pressure_text} Torr\n"
                f"Time remaining: {remaining_text}"
            )
        )

    def _close_start_wait_dialog(self):
        if self.start_wait_job is not None:
            try:
                self.after_cancel(self.start_wait_job)
            except Exception:
                pass
            self.start_wait_job = None

        self.start_wait_deadline = None

        if self.start_wait_dialog is not None:
            try:
                self.start_wait_dialog.grab_release()
            except Exception:
                pass
            try:
                self.start_wait_dialog.destroy()
            except Exception:
                pass

        self.start_wait_dialog = None
        self.start_wait_label = None

    def _poll_pressure_then_start(self):
        self.start_wait_job = None
        if self._closing:
            return

        if self.ser is None:
            self._close_start_wait_dialog()
            messagebox.showerror("Pump Error", "Pump disconnected while waiting to start turbo")
            return

        threshold = 5e-1
        pnum = self.live_pressure_value
        if pnum is None:
            try:
                data = self.pump_reader.get_data() if self.pump_reader else {}
                pressure = data.get("pressure") if data else None
                if pressure is None:
                    with self.serial_lock:
                        pressure = get_pressure_reading(self.ser)
                pnum = self._parse_float(pressure)
                if pnum is not None:
                    self.live_pressure_value = pnum
            except Exception as exc:
                self._close_start_wait_dialog()
                messagebox.showerror("Pressure Read Error", f"Failed to read pressure:\n{exc}")
                return

        self._update_start_wait_message(pnum)

        if pnum is not None and pnum < threshold:
            self._close_start_wait_dialog()
            self._send_start_command()
            return

        if self.start_wait_deadline is not None and time.time() >= self.start_wait_deadline:
            self._close_start_wait_dialog()
            messagebox.showerror("Pump Error", "Pressure did not reach <5e-1 Torr within 10 min. Start command not sent.")
            return

        if not self._closing:
            self.start_wait_job = self.after(1000, self._poll_pressure_then_start)

    def pump_save_plot_csv(self):
        if not self.pump_times or not self.pump_pressures:
            messagebox.showwarning("No Data", "No pump plot data available to save.")
            return

        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv")],
            initialfile="pressure_plot.csv",
        )
        if not path:
            return

        try:
            with open(path, "w", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(["timestamp_iso", "seconds_since_start", "pressure", "units"])
                t0 = self.pump_times[0]
                units = self.units_label.cget("text")
                for t, p in zip(self.pump_times, self.pump_pressures):
                    iso = datetime.datetime.fromtimestamp(t).isoformat()
                    writer.writerow([iso, f"{t - t0:.3f}", p, units])
            messagebox.showinfo("Saved", f"Saved CSV to {path}")
        except Exception as exc:
            messagebox.showerror("Save Error", f"Failed to save CSV:\n{exc}")

    # ------------------------- App Shutdown ------------------------

    def close_app(self):
        if self._closing:
            return
        self._closing = True

        self.ls_stop_polling()
        self.ls_stop_monitor()
        self.pump_stop_monitoring()
        self._close_start_wait_dialog()

        if self.pump_reader is not None:
            self.pump_reader.stop()
            self.pump_reader.join(timeout=2)
            self.pump_reader = None

        if self.ser is not None:
            try:
                close_comm(self.ser)
            except Exception:
                pass
            self.ser = None

        if self.ls_instrument is not None:
            try:
                if hasattr(self.ls_instrument, "close"):
                    self.ls_instrument.close()
            except Exception:
                pass
            self.ls_instrument = None

        self.destroy()


if __name__ == "__main__":
    app = IntegratedCryoGUI()
    app.mainloop()

# %%
