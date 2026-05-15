# %%
import tkinter as tk
from tkinter import ttk, messagebox
import threading
import time
import csv
import datetime
from collections import deque
from tkinter import filedialog
from pump_helpers import open_comm, close_comm, get_pressure_reading, get_pressure_units, get_turbo_speed, get_turbo_power, get_turbo_current, get_turbo_voltage, start_pump, stop_pump, get_tipseal_life, get_pump_status
from scroll_relay_helpers import (
    init_relay_comm,
    close_relay_comm,
    send_command as send_relay_command,
    turn_on_relay,
    turn_off_relay,
    read_relay_state
)
import queue
try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    HAS_MPL = True
except Exception:
    HAS_MPL = False


class PumpReader(threading.Thread):
    def __init__(self, ser, serial_lock):
        super().__init__(daemon=True)
        self.ser = ser
        self.serial_lock = serial_lock
        self.running = True
        self.lock = threading.Lock()
        self.data = {
            'pressure': None,
            'units': None,
            'turbo': None,
            'power': None,
            'current': None,
            'voltage': None,
            'tip_life': None,
            'timestamp': None,
            'error': None,
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
                    if (self.tip_last_sample_ts is None) or (now_ts - self.tip_last_sample_ts >= self.tip_sample_interval):
                        tip_life = get_tipseal_life(self.ser)
                        self.tip_last_sample_ts = now_ts
                    else:
                        tip_life = self.data.get('tip_life')

                with self.lock:
                    self.data['error'] = None
                    self.data['timestamp'] = time.time()
                    self.data['units'] = units
                    self.data['pressure'] = pressure
                    self.data['turbo'] = turbo
                    self.data['power'] = power
                    self.data['current'] = current
                    self.data['voltage'] = voltage
                    self.data['tip_life'] = tip_life

            except Exception as e:
                with self.lock:
                    self.data['error'] = str(e)

            time.sleep(0.5)

    def get_data(self):
        with self.lock:
            return dict(self.data)

    def stop(self):
        self.running = False


class PumpGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Cryostation Pump Monitor")
        self.root.state('zoomed')  # Maximize window on startup
        self.root.resizable(True, True)

        self.ser = None
        self.relay_ser = None
        self.serial_lock = threading.Lock()
        self.relay_lock = threading.Lock()
        self.pump_reader = None
        self.monitoring = False
        self.update_interval = 1000  # milliseconds
        self.plot_interval = 5000  # milliseconds (5 seconds)
        # compute deque sizes so they represent ~24 hours of data
        # plot samples are taken every `plot_interval`; hr samples every `update_interval`
        try:
            self.plot_maxlen = int(24 * 3600 / (self.plot_interval / 1000.0))
        except Exception:
            # fallback to 5s-sampled 24h (~17280)
            self.plot_maxlen = 17280
        self.times = deque(maxlen=self.plot_maxlen)
        self.prices = deque(maxlen=self.plot_maxlen)
        self.turbo_values = deque(maxlen=self.plot_maxlen)
        # high-resolution sample buffers (collected every update_interval)
        try:
            hr_maxlen = int(24 * 3600 / (self.update_interval / 1000.0))
        except Exception:
            hr_maxlen = 86400
        self.hr_times = deque(maxlen=hr_maxlen)
        self.hr_pressures = deque(maxlen=hr_maxlen)
        self.hr_turbos = deque(maxlen=hr_maxlen)
        # tip seal sampling: sample interval (seconds) and last sample timestamp
        self.tip_sample_interval = 3600  # 1 hour
        self.tip_last_sample_ts = None
        self.tip_seal_warning_shown = False
        self.last_pressure_value = None
        self.plot_callback = None
        self.pending_callback = None  # Track pending callbacks
        self.start_wait_dialog = None
        self.start_wait_label = None
        self.start_wait_callback = None
        self.start_wait_deadline = None
        self.live_pressure_value = None
        self.turbo_start_time = None  # Track when turbo was last started
        
        self.setup_ui()
        self.connect_pump()
        self.root.after(2000, self._initial_display_update)
        self.root.protocol("WM_DELETE_WINDOW", self.close_app)

        
    def setup_ui(self):
        """Create the user interface"""
        # Configure ttk style for larger button fonts
        style = ttk.Style()
        style.configure('TButton', font=('Arial', 12))
        
        # Main split: left = controls/display, right = plot
        main_frame = ttk.Frame(self.root)
        main_frame.pack(fill="both", expand=True)

        left_frame = ttk.Frame(main_frame)
        left_frame.pack(side="left", fill="both", expand=True, padx=8, pady=8)

        right_frame = ttk.Frame(main_frame)
        right_frame.pack(side="right", fill="both", expand=True, padx=8, pady=8)

        # Title frame
        title_frame = ttk.Frame(left_frame)
        title_frame.pack(pady=10)

        title_label = ttk.Label(title_frame, text="Pump Pressure Monitor", 
                                font=("Arial", 16, "bold"))
        title_label.pack()
        author_label = ttk.Label(title_frame, text="Written by: Jerry A. Yang",
                     font=("Arial", 10), foreground="gray")
        author_label.pack()
        date_label = ttk.Label(title_frame, text="Date: 2026-02-06",
                     font=("Arial", 10), foreground="gray")
        date_label.pack()

        # Status frame
        status_frame = ttk.LabelFrame(left_frame, text="Connection Status", padding=10)
        status_frame.pack(padx=10, pady=10, fill="x")

        # Container frame to center the status displays
        status_container = ttk.Frame(status_frame)
        status_container.pack(expand=True)

        # Turbo pump status
        turbo_status_frame = ttk.Frame(status_container)
        turbo_status_frame.pack(side="left", pady=5, padx=(0, 20))
        ttk.Label(turbo_status_frame, text="Turbo Pump:").pack(side="left")
        self.status_label = ttk.Label(turbo_status_frame, text="Disconnected",
                                      foreground="red", font=("Arial", 10))
        self.status_label.pack(side="left", padx=(10, 0))

        # Scroll relay status
        relay_status_frame = ttk.Frame(status_container)
        relay_status_frame.pack(side="left", pady=5)
        ttk.Label(relay_status_frame, text="Scroll Relay:").pack(side="left")
        self.relay_status_label = ttk.Label(relay_status_frame, text="Disconnected",
                                           foreground="red", font=("Arial", 10))
        self.relay_status_label.pack(side="left", padx=(10, 0))

        # Pressure display frame
        pressure_frame = ttk.LabelFrame(left_frame, text="Pressure Reading", padding=20)
        pressure_frame.pack(padx=10, pady=10, fill="both", expand=True, side="top")

        # Pressure value
        self.pressure_label = ttk.Label(pressure_frame, text="-- ", 
                                        font=("Arial", 36, "bold"), foreground="blue")
        self.pressure_label.pack()

        # Pressure units
        self.units_label = ttk.Label(pressure_frame, text="--", 
                                     font=("Arial", 14))
        self.units_label.pack()

        # Turbo pump speed + status
        turbo_frame = ttk.Frame(pressure_frame)
        turbo_frame.pack()

        self.turbo_label = ttk.Label(turbo_frame, text="Turbo: -- rpm", 
                 font=("Arial", 12))
        self.turbo_label.pack(side="left")

        self.turbo_status_label = ttk.Label(turbo_frame, text="--",
                 font=("Arial", 12), foreground="gray")
        self.turbo_status_label.pack(side="left", padx=(8, 0))

        self.power_label = ttk.Label(pressure_frame, text="Power: -- W",
                   font=("Arial", 12))
        self.power_label.pack()

        self.current_label = ttk.Label(pressure_frame, text="Current: -- mA",
                     font=("Arial", 12))
        self.current_label.pack()

        self.voltage_label = ttk.Label(pressure_frame, text="Voltage: -- V",
                     font=("Arial", 12))
        self.voltage_label.pack()

        # Tip seal life (hours)
        self.tipseal_label = ttk.Label(pressure_frame, text="Tip Seal Life: -- hr",
                           font=("Arial", 12))
        self.tipseal_label.pack()

        # Chart area on right_frame (matplotlib)
        self.plot_canvas = None
        if HAS_MPL:
            self.fig, self.ax = plt.subplots(figsize=(5, 4))
            self.line, = self.ax.plot([], [], '-o', markersize=4)
            self.ax.set_title('Pressure vs Time')
            self.ax.set_xlabel('Time')
            self.ax.set_ylabel('Pressure')
            # format x-axis as time stamps (hours:minutes)
            try:
                self.ax.xaxis_date()
                self.ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M:%S'))
                self.ax.xaxis.set_major_locator(mdates.AutoDateLocator())
            except Exception:
                pass
            # use logarithmic scale for pressure axis
            try:
                self.ax.set_yscale('log')
                self.ax.set_ylim(2e-7, 1e3)
            except Exception:
                pass
            self.ax.grid(True)

            self.canvas = FigureCanvasTkAgg(self.fig, master=right_frame)
            
            self.canvas_widget = self.canvas.get_tk_widget()
            self.canvas_widget.pack(fill='both', expand=True)
        else:
            msg = ttk.Label(right_frame, text='matplotlib not installed; plot unavailable', foreground='gray')
            msg.pack(padx=10, pady=10)
        
        # Pump start/stop controls (above monitoring buttons)
        pump_control_frame = ttk.Frame(left_frame)
        pump_control_frame.pack(pady=10, side="bottom", fill="both", expand=True, padx=10)

        self.start_pump_button = ttk.Button(pump_control_frame, text="Start Pump",
                            command=self.do_start_pump)
        self.start_pump_button.pack(side="left", padx=5, fill="both", expand=True, ipady=15)

        self.stop_pump_button = ttk.Button(pump_control_frame, text="Stop Pump",
                           command=self.do_stop_pump)
        self.stop_pump_button.pack(side="left", padx=5, fill="both", expand=True, ipady=15)

        # Control frame (monitoring buttons)
        control_frame = ttk.Frame(left_frame)
        control_frame.pack(pady=10, side="bottom", fill="both", expand=True, padx=10)
        
        self.start_button = ttk.Button(control_frame, text="Start Monitoring", 
                           command=self.start_monitoring)
        self.start_button.pack(side="left", padx=5, fill="both", expand=True, ipady=15)
        
        self.stop_button = ttk.Button(control_frame, text="Stop Monitoring", 
                          command=self.stop_monitoring, state="disabled")
        self.stop_button.pack(side="left", padx=5, fill="both", expand=True, ipady=15)
        
        close_button = ttk.Button(control_frame, text="Close", 
                      command=self.close_app)
        close_button.pack(side="left", padx=5, fill="both", expand=True, ipady=15)
        
        save_button = ttk.Button(control_frame, text="Save Plot CSV",
                     command=self.save_plot_csv)
        save_button.pack(side="left", padx=5, fill="both", expand=True, ipady=15)
        
    def connect_pump(self):
        """Establish serial connection to pump and relay"""
        try:
            self.ser = open_comm()
            units = get_pressure_units(self.ser)
            units_norm = str(units).strip().lower().rstrip('.')
            if units_norm == "get units failed":
                self.status_label.config(text="Disconnected", foreground="red")
                messagebox.showwarning("Connection Status", "Pump not detected (units read failed).")
                return

            self.status_label.config(text="Connected", foreground="green")

            self.pump_reader = PumpReader(self.ser, self.serial_lock)
            self.pump_reader.start()

            time.sleep(1.5)
        except Exception as e:
            messagebox.showerror("Connection Error", f"Failed to connect to pump:\n{str(e)}")
            self.status_label.config(text="Connection Failed", foreground="red")

        # Initialize scroll relay connection
        try:
            self.relay_ser = init_relay_comm(port_name="COM2", baud_rate=19200, timeout=1)
            if self.relay_ser is None:
                self.relay_status_label.config(text="Connection Failed", foreground="red")
                messagebox.showwarning("Relay Connection", "Failed to connect to scroll relay.")
            else:
                self.relay_status_label.config(text="Connected", foreground="green")
        except Exception as e:
            messagebox.showerror("Relay Connection Error", f"Failed to connect to relay:\n{str(e)}")
            self.relay_status_label.config(text="Connection Failed", foreground="red")

    def _initial_display_update(self):
        """Update UI with initial data from background thread"""
        if self.pump_reader and self.ser:
            try:
                data = self.pump_reader.get_data()
                tip_life = data.get('tip_life')
                if tip_life is not None:
                    tip_value = self._parse_pressure_value(tip_life)
                    self.tipseal_label.config(text=f"Tip Seal Life: {tip_life} hr")
                    if tip_value is not None and tip_value > 5000:
                        self.tipseal_label.config(foreground="red")
                        if not self.tip_seal_warning_shown:
                            messagebox.showwarning("Tip Seal Warning", "Tip seal life is over 5000 hours. Please change the tip seal.")
                            self.tip_seal_warning_shown = True
                    else:
                        self.tipseal_label.config(foreground="black")
            except Exception:
                pass

    def start_monitoring(self):
        """Start continuous pressure monitoring"""
        if self.ser is None:
            messagebox.showwarning("Warning", "Pump not connected")
            return
        
        self.monitoring = True
        self.start_button.config(state="disabled")
        self.stop_button.config(state="normal")
        # clear plot data so plot starts fresh on each monitoring session
        try:
            self.times.clear()
            self.prices.clear()
            self.hr_times.clear()
            self.hr_pressures.clear()
            self.hr_turbos.clear()
            self.last_pressure_value = None
            self.tip_last_sample_ts = None
            if HAS_MPL:
                self.line.set_data([], [])
                self.ax.relim()
                self.ax.autoscale_view()
                try:
                    self.canvas.draw_idle()
                except Exception:
                    pass
        except Exception:
            pass

        self.update_pressure()
        # start plot sampling loop (5s)
        if HAS_MPL:
            # cancel existing if present
            if self.plot_callback:
                try:
                    self.root.after_cancel(self.plot_callback)
                except Exception:
                    pass
            self.update_plot()
        
    def stop_monitoring(self):
        """Stop continuous pressure monitoring"""
        self.monitoring = False
        self.start_button.config(state="normal")
        self.stop_button.config(state="disabled")
        # cancel plot callback
        if self.plot_callback:
            try:
                self.root.after_cancel(self.plot_callback)
            except Exception:
                pass
            self.plot_callback = None

    def _is_live_updating(self):
        """Return True when pressure/plot loops should keep running."""
        return self.monitoring or (self.start_wait_dialog is not None)

    def _ensure_live_updates(self):
        """Start update loops if needed (used for turbo-start wait mode)."""
        if self.ser is None:
            return
        if self.pending_callback is None:
            self.update_pressure()
        if HAS_MPL and self.plot_callback is None:
            self.update_plot()
        
    def update_pressure(self):
        """Update pressure reading from pump (non-blocking via background thread)"""
        self.pending_callback = None
        if self._is_live_updating() and self.ser and self.pump_reader:
            try:
                data = self.pump_reader.get_data()

                if data.get('error'):
                    self.status_label.config(text="Disconnected", foreground="red")
                    self.pressure_label.config(text="--", foreground="red")
                    self.units_label.config(text="--")
                    self.turbo_label.config(text="Turbo: -- rpm")
                    self.turbo_status_label.config(text="--", foreground="gray")
                    self.power_label.config(text="Power: -- W")
                    self.current_label.config(text="Current: -- mA")
                    self.voltage_label.config(text="Voltage: -- V")
                    if self.monitoring:
                        self.pending_callback = self.root.after(self.update_interval, self.update_pressure)
                    return

                units = data.get('units')
                units_norm = str(units).strip().lower().rstrip('.') if units else ""

                if units_norm == "get units failed":
                    self.status_label.config(text="Disconnected", foreground="red")
                    self.pressure_label.config(text="--", foreground="red")
                    self.units_label.config(text="--")
                    self.turbo_label.config(text="Turbo: -- rpm")
                    self.turbo_status_label.config(text="--", foreground="gray")
                    self.power_label.config(text="Power: -- W")
                    self.current_label.config(text="Current: -- mA")
                    self.voltage_label.config(text="Voltage: -- V")
                    if self.monitoring:
                        self.pending_callback = self.root.after(self.update_interval, self.update_pressure)
                    return

                self.status_label.config(text="Connected", foreground="green")

                pressure = data.get('pressure')
                turbo = data.get('turbo')
                power = data.get('power')
                current = data.get('current')
                voltage = data.get('voltage')
                tip_life = data.get('tip_life')

                self.pressure_label.config(text=pressure, foreground="blue")
                self.units_label.config(text=units)
                self.turbo_label.config(text=f"Turbo: {turbo} rpm")
                self.power_label.config(text=f"Power: {power} W")
                self.current_label.config(text=f"Current: {current} mA")
                self.voltage_label.config(text=f"Voltage: {voltage} V")

                turbo_value = self._parse_pressure_value(turbo)
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
                    tip_value = self._parse_pressure_value(tip_life)
                    if tip_value is not None and tip_value > 5000:
                        self.tipseal_label.config(foreground="red")
                        if not self.tip_seal_warning_shown:
                            messagebox.showwarning("Tip Seal Warning", "Tip seal life is over 5000 hours. Please change the tip seal.")
                            self.tip_seal_warning_shown = True
                    else:
                        self.tipseal_label.config(foreground="black")

                num = self._parse_pressure_value(pressure)
                if num is not None:
                    self.last_pressure_value = num
                    self.live_pressure_value = num
                    if self.start_wait_dialog is not None:
                        self._update_start_wait_message(num)
                    ts = time.time()
                    self.hr_times.append(ts)
                    self.hr_pressures.append(num)
                    tnum = self._parse_pressure_value(turbo)
                    if tnum is not None:
                        self.hr_turbos.append(tnum)
                    else:
                        self.hr_turbos.append(None)

            except Exception as e:
                self.pressure_label.config(text="Error", foreground="red")
                self.units_label.config(text=str(e))
                self.turbo_label.config(text="Turbo: Error")
                self.power_label.config(text="Power: Error")
                self.current_label.config(text="Current: Error")
                self.voltage_label.config(text="Voltage: Error")
                self.turbo_status_label.config(text="--", foreground="red")
                print(f"Error reading pressure: {e}")

            if self._is_live_updating():
                self.pending_callback = self.root.after(self.update_interval, self.update_pressure)

    def do_start_pump(self):
        """Gate turbo start on pressure < 5e-1 Torr before sending start command."""
        if self.ser is None:
            messagebox.showwarning("Warning", "Pump not connected")
            return
        if self.relay_ser is None:
            messagebox.showwarning("Warning", "Scroll relay not connected")
            return
        if self.start_wait_dialog is not None:
            messagebox.showinfo("Pump Command", "Already waiting for pressure <5e-1 Torr.")
            return

        # Confirm valve states before proceeding
        if not messagebox.askyesno("Valve Confirmation", "Are all valves in their correct state (open/closed)?"):
            return

        # Check turbo speed is 0 rpm
        try:
            if self.pump_reader:
                data = self.pump_reader.get_data()
                turbo = data.get('turbo')
            else:
                with self.serial_lock:
                    turbo = get_turbo_speed(self.ser)
            turbo_num = self._parse_pressure_value(turbo)
        except Exception as e:
            messagebox.showerror("Turbo Read Error", f"Failed to read turbo speed:\n{e}")
            return

        if turbo_num is None or turbo_num != 0:
            messagebox.showerror("Cannot Start Pump", f"Turbo speed must be 0 rpm before starting. Current speed: {turbo} rpm")
            return

        # Check that turbo is not in starting/stopping state
        if 0 < turbo_num <= 70000:
            messagebox.showerror("Cannot Start Pump", f"Turbo is currently starting/stopping. Please wait for it to reach 0 rpm or at speed (>70000 rpm)")
            return

        # Check relay status and turn on if needed
        try:
            relay_number = 0
            with self.relay_lock:
                relay_state = read_relay_state(self.relay_ser, relay_number)

            if relay_state is not None:
                relay_state_normalized = relay_state.strip().lower()
                if relay_state_normalized == "off":
                    with self.relay_lock:
                        turn_on_relay(self.relay_ser, relay_number)
                    messagebox.showinfo("Relay", "Relay was off. Turned it on.")
        except Exception as e:
            messagebox.showerror("Relay Error", f"Failed to check/control relay:\n{e}")
            return

        # Continue with normal pressure reading and wait procedure
        try:
            if self.pump_reader:
                data = self.pump_reader.get_data()
                pressure = data.get('pressure')
            else:
                with self.serial_lock:
                    pressure = get_pressure_reading(self.ser)
            pnum = self._parse_pressure_value(pressure)
        except Exception as e:
            messagebox.showerror("Pressure Read Error", f"Failed to read pressure:\n{e}")
            return

        threshold = 5e-1
        if pnum is not None and pnum < threshold:
            self._send_start_command()
            return

        self.start_wait_deadline = time.time() + (10 * 60)
        self._show_start_wait_dialog()
        self._ensure_live_updates()
        self._poll_pressure_then_start()

    def _send_start_command(self):
        """Check turbo state and send start command."""
        if self.ser is None:
            messagebox.showwarning("Warning", "Pump not connected")
            return
        # Check pump status via get_pump_status() for diagnostics
        try:
            with self.serial_lock:
                try:
                    status = get_pump_status(self.ser)
                except Exception as e:
                    messagebox.showerror("Pump Status Error", f"Failed to read pump status:\n{e}")
                    return

                # Check turbo speed equals 0
                try:
                    turbo = get_turbo_speed(self.ser)
                    tnum = self._parse_pressure_value(turbo)
                except Exception as e:
                    messagebox.showerror("Turbo Read Error", f"Failed to read turbo speed:\n{e}")
                    return

            is_turbo_zero = (tnum is not None and tnum == 0)

            if is_turbo_zero:
                try:
                    with self.serial_lock:
                        if not start_pump(self.ser):
                            raise Exception("Pump did not acknowledge start command")
                    self.turbo_start_time = time.time()
                    messagebox.showinfo("Pump Command", "Start command sent")
                except Exception as e:
                    messagebox.showerror("Pump Error", f"Failed to send start command:\n{e}")
            else:
                messagebox.showwarning("Cannot Start Pump",
                                       f"Pump not started because conditions not met:\nstatus='{status}'\nturbo='{turbo}'\nExpected: status='stopped' and turbo=0")
        except Exception as e:
            messagebox.showerror("Pump Error", f"Unexpected error:\n{e}")

    def _show_start_wait_dialog(self):
        """Show modal dialog while waiting for pressure to reach safe turbo-start threshold."""
        if self.start_wait_dialog is not None:
            return

        dlg = tk.Toplevel(self.root)
        dlg.title("Waiting for Pressure")
        dlg.transient(self.root)
        dlg.grab_set()
        dlg.resizable(False, False)
        dlg.protocol("WM_DELETE_WINDOW", lambda: None)

        self.start_wait_label = ttk.Label(dlg, text="Waiting for pressure <5e-1 Torr for 10 min...", padding=16)
        self.start_wait_label.pack()

        # Center dialog over root window.
        try:
            self.root.update_idletasks()
            rw = self.root.winfo_width()
            rh = self.root.winfo_height()
            rx = self.root.winfo_rootx()
            ry = self.root.winfo_rooty()
            ww = dlg.winfo_reqwidth()
            wh = dlg.winfo_reqheight()
            x = rx + max((rw - ww) // 2, 0)
            y = ry + max((rh - wh) // 2, 0)
            dlg.geometry(f"+{x}+{y}")
        except Exception:
            pass

        self.start_wait_dialog = dlg
        self._update_start_wait_message(self.live_pressure_value)

    def _update_start_wait_message(self, pressure_value=None):
        """Refresh waiting-dialog text with latest pressure and remaining time."""
        if self.start_wait_label is None:
            return

        remaining_text = "--"
        if self.start_wait_deadline is not None:
            remaining = max(int(self.start_wait_deadline - time.time()), 0)
            mins = remaining // 60
            secs = remaining % 60
            remaining_text = f"{mins:02d}:{secs:02d}"

        if pressure_value is None:
            pressure_text = "--"
        else:
            pressure_text = f"{pressure_value:.3e}"

        self.start_wait_label.config(
            text=(
                "Waiting for pressure <5e-1 Torr before turbo start\n"
                f"Current pressure: {pressure_text} Torr\n"
                f"Time remaining: {remaining_text}"
            )
        )

    def _close_start_wait_dialog(self):
        """Close waiting dialog and clear pending polling callback."""
        if self.start_wait_callback:
            try:
                self.root.after_cancel(self.start_wait_callback)
            except Exception:
                pass
        self.start_wait_callback = None
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
        """Poll pressure until threshold is met or timeout occurs."""
        if self.ser is None:
            self._close_start_wait_dialog()
            messagebox.showerror("Pump Error", "Pump disconnected while waiting to start turbo")
            return

        threshold = 5e-1
        pnum = self.live_pressure_value
        if pnum is None:
            try:
                if self.pump_reader:
                    data = self.pump_reader.get_data()
                    pressure = data.get('pressure')
                else:
                    pressure = get_pressure_reading(self.ser)
                pnum = self._parse_pressure_value(pressure)
                if pnum is not None:
                    self.live_pressure_value = pnum
            except Exception as e:
                self._close_start_wait_dialog()
                messagebox.showerror("Pressure Read Error", f"Failed to read pressure:\n{e}")
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

        self.start_wait_callback = self.root.after(1000, self._poll_pressure_then_start)

    def do_stop_pump(self):
        """Check relay status and turn off if needed, then send stop command to the pump"""
        if self.ser is None:
            messagebox.showwarning("Warning", "Pump not connected")
            return
        if self.relay_ser is None:
            messagebox.showwarning("Warning", "Scroll relay not connected")
            return

        # Confirm valve states before proceeding
        if not messagebox.askyesno("Valve Confirmation", "Are all valves in their correct state (open/closed)?"):
            return

        # Check turbo speed is either at speed or at 0 rpm (not starting/stopping)
        try:
            if self.pump_reader:
                data = self.pump_reader.get_data()
                turbo = data.get('turbo')
            else:
                with self.serial_lock:
                    turbo = get_turbo_speed(self.ser)
            turbo_num = self._parse_pressure_value(turbo)
        except Exception as e:
            messagebox.showerror("Turbo Read Error", f"Failed to read turbo speed:\n{e}")
            return

        # Check that turbo is not in starting/stopping state
        if turbo_num is not None and 0 < turbo_num <= 70000:
            messagebox.showerror("Cannot Stop Pump", f"Turbo is currently starting/stopping. Please wait for it to reach at speed (>70000 rpm) or 0 rpm")
            return

        # Check if turbo was started less than 10 minutes ago
        if self.turbo_start_time is not None:
            elapsed_time = time.time() - self.turbo_start_time
            if elapsed_time < 600:  # 600 seconds = 10 minutes
                minutes_remaining = int((600 - elapsed_time) / 60)
                seconds_remaining = int((600 - elapsed_time) % 60)
                messagebox.showerror("Cannot Stop Pump",
                    f"Turbo cannot be stopped within 10 minutes of starting.\n"
                    f"Time remaining: {minutes_remaining:02d}:{seconds_remaining:02d}")
                return

        # Check relay status and turn off if needed
        try:
            relay_number = 0
            with self.relay_lock:
                relay_state = read_relay_state(self.relay_ser, relay_number)

            if relay_state is not None:
                relay_state_normalized = relay_state.strip().lower()
                if relay_state_normalized == "on":
                    with self.relay_lock:
                        turn_off_relay(self.relay_ser, relay_number)
                    messagebox.showinfo("Relay", "Relay was on. Turned it off.")
                    return
        except Exception as e:
            messagebox.showerror("Relay Error", f"Failed to check/control relay:\n{e}")
            return

        # Continue with normal turbo control logic
        try:
            with self.serial_lock:
                stop_pump(self.ser)
            messagebox.showinfo("Pump Command", "Stop command sent")
        except Exception as e:
            messagebox.showerror("Pump Error", f"Failed to send stop command:\n{e}")
    
    def close_app(self):
        """Close the application"""
        self.stop_monitoring()
        self._close_start_wait_dialog()
        if self.pending_callback:
            self.root.after_cancel(self.pending_callback)
        if self.plot_callback:
            try:
                self.root.after_cancel(self.plot_callback)
            except Exception:
                pass
        if self.pump_reader:
            self.pump_reader.stop()
            self.pump_reader.join(timeout=2)
        if self.ser:
            try:
                close_comm(self.ser)
            except Exception as e:
                print(f"Error closing serial connection: {e}")
        if self.relay_ser:
            try:
                close_relay_comm(self.relay_ser)
            except Exception as e:
                print(f"Error closing relay connection: {e}")
        self.root.destroy()

    def save_plot_csv(self):
        """Save the current pressure vs time data to a CSV file."""
        if not self.times or not self.prices:
            messagebox.showwarning("No Data", "No plot data available to save.")
            return

        path = filedialog.asksaveasfilename(defaultextension='.csv',
                                            filetypes=[('CSV files', '*.csv')],
                                            initialfile='pressure_plot.csv')
        if not path:
            return

        try:
            with open(path, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(['timestamp_iso', 'seconds_since_start', 'pressure', 'units'])
                t0 = self.times[0]
                units = self.units_label.cget('text')
                for t, p in zip(self.times, self.prices):
                    iso = datetime.datetime.fromtimestamp(t).isoformat()
                    seconds = t - t0
                    writer.writerow([iso, f"{seconds:.3f}", p, units])

            messagebox.showinfo("Saved", f"Saved CSV to {path}")
        except Exception as e:
            messagebox.showerror("Save Error", f"Failed to save CSV:\n{e}")

    def _parse_pressure_value(self, text):
        """Attempt to extract a float from the pressure string."""
        import re
        if not text:
            return None
        m = re.search(r'[-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?', str(text))
        if not m:
            return None
        try:
            return float(m.group(0))
        except Exception:
            return None

    def update_plot(self):
        """Sample current pressure and update the matplotlib plot."""
        if not HAS_MPL:
            return
        if not self._is_live_updating():
            self.plot_callback = None
            return
        # aggregate high-resolution samples from the last plot interval
        now = time.time()
        cutoff = now - (self.plot_interval / 1000.0)
        # collect samples in hr arrays newer than cutoff
        values = [v for (t, v) in zip(self.hr_times, self.hr_pressures) if t >= cutoff]
        turbo_avg = None
        if values:
            avg = sum(values) / len(values)
            # compute turbo average for the same samples (ignore None)
            tvals = [v for (t, v) in zip(self.hr_times, self.hr_turbos) if t >= cutoff and v is not None]
            if tvals:
                turbo_avg = sum(tvals) / len(tvals)
            self.times.append(now)
            self.prices.append(avg)
            self.turbo_values.append(turbo_avg)
        else:
            # fallback to last value if no high-res samples
            if self.last_pressure_value is not None:
                self.times.append(now)
                self.prices.append(self.last_pressure_value)
                self.turbo_values.append(None)

        if len(self.times) > 0:
            # convert timestamps to matplotlib date numbers for x axis
            try:
                xs = mdates.date2num([datetime.datetime.fromtimestamp(t) for t in self.times])
            except Exception:
                # fallback to relative seconds if date conversion fails
                t0 = self.times[0]
                xs = [t - t0 for t in self.times]
            ys = list(self.prices)
            # filter non-positive values for log scale: replace with NaN so matplotlib skips them
            ys_filtered = [v if (v is not None and v > 0) else float('nan') for v in ys]
            # only update plot if there is at least one positive sample
            if not any((v > 0) for v in ys if v is not None):
                # schedule next plot update before returning so updates continue
                try:
                    self.plot_callback = self.root.after(self.plot_interval, self.update_plot)
                except Exception:
                    self.plot_callback = None
                return
            self.line.set_data(xs, ys_filtered)
            self.ax.relim()
            self.ax.autoscale_view()
            self.ax.set_xlabel('Time')
            try:
                # rotate labels for readability
                for label in self.ax.get_xticklabels():
                    label.set_rotation(30)
                    label.set_ha('right')
            except Exception:
                pass
            self.canvas.draw_idle()

        # schedule next plot update
        try:
            self.plot_callback = self.root.after(self.plot_interval, self.update_plot)
        except Exception:
            self.plot_callback = None


if __name__ == "__main__":
    root = tk.Tk()
    app = PumpGUI(root)
    root.mainloop()
