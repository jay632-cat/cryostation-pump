# %%
import tkinter as tk
from tkinter import ttk, messagebox
import threading
import time
import csv
import datetime
from collections import deque
from tkinter import filedialog
from pump_helpers import open_comm, close_comm, get_pressure_reading, get_pressure_units, get_turbo_speed, start_pump, stop_pump, get_tipseal_life, get_pump_status
try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    HAS_MPL = True
except Exception:
    HAS_MPL = False


class PumpGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Cryostation Pump Monitor")
        self.root.state('zoomed')  # Maximize window on startup
        self.root.resizable(True, True)
        
        self.ser = None
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
        
        self.setup_ui()
        self.connect_pump()
        # Handle window close button (X)
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

        self.status_label = ttk.Label(status_frame, text="Disconnected", 
                                      foreground="red", font=("Arial", 10))
        self.status_label.pack()

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
                self.ax.set_ylim(5e-7, 1e3)
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
        """Establish serial connection to pump"""
        try:
            self.ser = open_comm()
            units = get_pressure_units(self.ser)
            units_norm = str(units).strip().lower().rstrip('.')
            if units_norm == "get units failed":
                self.status_label.config(text="Disconnected", foreground="red")
                messagebox.showwarning("Connection Status", "Pump not detected (units read failed).")
                return

            self.status_label.config(text="Connected", foreground="green")
            # sample tip seal life immediately on successful connection
            try:
                tip_life = get_tipseal_life(self.ser)
                if tip_life is None:
                    self.tipseal_label.config(text="Tip Seal Life: -- hr", foreground="black")
                else:
                    self.tipseal_label.config(text=f"Tip Seal Life: {tip_life} hr")
                    if tip_life > 5000:
                        self.tipseal_label.config(foreground="red")
                        if not self.tip_seal_warning_shown:
                            messagebox.showwarning("Tip Seal Warning", "Tip seal life is over 5000 hours. Please change the tip seal.")
                            self.tip_seal_warning_shown = True
                    else:
                        self.tipseal_label.config(foreground="black")
                self.tip_last_sample_ts = time.time()
            except Exception:
                # leave label as-is on error
                pass
        except Exception as e:
            messagebox.showerror("Connection Error", f"Failed to connect to pump:\n{str(e)}")
            self.status_label.config(text="Connection Failed", foreground="red")
            
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
        
    def update_pressure(self):
        """Update pressure reading from pump"""
        self.pending_callback = None  # Clear callback reference
        if self.monitoring and self.ser:
            try:
                units = get_pressure_units(self.ser)
                units_norm = str(units).strip().lower().rstrip('.')
                if units_norm == "get units failed":
                    self.status_label.config(text="Disconnected", foreground="red")
                    self.pressure_label.config(text="--", foreground="red")
                    self.units_label.config(text="--")
                    self.turbo_label.config(text="Turbo: -- rpm")
                    self.turbo_status_label.config(text="--", foreground="gray")
                    if self.monitoring:
                        self.pending_callback = self.root.after(self.update_interval, self.update_pressure)
                    return

                self.status_label.config(text="Connected", foreground="green")
                pressure = get_pressure_reading(self.ser)
                turbo = get_turbo_speed(self.ser)
                
                self.pressure_label.config(text=pressure, foreground="blue")
                self.units_label.config(text=units)
                self.turbo_label.config(text=f"Turbo: {turbo} rpm")
                turbo_value = self._parse_pressure_value(turbo)
                if turbo_value is not None and turbo_value > 70000:
                    self.turbo_status_label.config(text="At Speed", foreground="green")
                elif turbo_value is not None and turbo_value == 0:
                    self.turbo_status_label.config(text="Stopped", foreground="red")
                elif turbo_value is not None and 0 < turbo_value <= 70000:
                    self.turbo_status_label.config(text="Starting/Stopping", foreground="goldenrod")
                else:
                    self.turbo_status_label.config(text="--", foreground="gray")
                # read tip seal life from device if available (once per hour)
                try:
                    now_ts = time.time()
                    if (self.tip_last_sample_ts is None) or (now_ts - self.tip_last_sample_ts >= self.tip_sample_interval):
                        tip_life = get_tipseal_life(self.ser)
                        if tip_life is None:
                            self.tipseal_label.config(text="Tip Seal Life: -- hr", foreground="black")
                        else:
                            self.tipseal_label.config(text=f"Tip Seal Life: {tip_life} hr")
                            if tip_life > 5000:
                                self.tipseal_label.config(foreground="red")
                                if not self.tip_seal_warning_shown:
                                    messagebox.showwarning("Tip Seal Warning", "Tip seal life is over 5000 hours. Please change the tip seal.")
                                    self.tip_seal_warning_shown = True
                            else:
                                self.tipseal_label.config(foreground="black")
                        self.tip_last_sample_ts = now_ts
                except Exception:
                    # keep previous value on error
                    pass
                # parse numeric pressure for plotting
                num = self._parse_pressure_value(pressure)
                if num is not None:
                    self.last_pressure_value = num
                    # record high-resolution sample
                    ts = time.time()
                    self.hr_times.append(ts)
                    self.hr_pressures.append(num)
                    # parse turbo numeric if possible
                    tnum = self._parse_pressure_value(turbo)
                    # always append to hr_turbos to keep buffers aligned (use None if missing)
                    if tnum is not None:
                        self.hr_turbos.append(tnum)
                    else:
                        self.hr_turbos.append(None)
                
            except Exception as e:
                self.pressure_label.config(text="Error", foreground="red")
                self.units_label.config(text=str(e))
                self.turbo_label.config(text="Turbo: Error")
                self.turbo_status_label.config(text="--", foreground="red")
                print(f"Error reading pressure: {e}")
            
            # Schedule next update only if still monitoring
            if self.monitoring:
                self.pending_callback = self.root.after(self.update_interval, self.update_pressure)

    def do_start_pump(self):
        """Send start command to the pump"""
        if self.ser is None:
            messagebox.showwarning("Warning", "Pump not connected")
            return
        # Check pump status via get_pump_status()
        try:
            try:
                status = get_pump_status(self.ser)
            except Exception as e:
                messagebox.showerror("Pump Status Error", f"Failed to read pump status:\n{e}")
                return

            sstr = '' if status is None else str(status).lower()
            is_stopped = 'stopped' in sstr or sstr.strip() == 'stopped'

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
                    if not start_pump(self.ser):
                        raise Exception("Pump did not acknowledge start command")
                    messagebox.showinfo("Pump Command", "Start command sent")
                except Exception as e:
                    messagebox.showerror("Pump Error", f"Failed to send start command:\n{e}")
            else:
                messagebox.showwarning("Cannot Start Pump",
                                       f"Pump not started because conditions not met:\nstatus='{status}'\nturbo='{turbo}'\nExpected: status='stopped' and turbo=0")
        except Exception as e:
            messagebox.showerror("Pump Error", f"Unexpected error:\n{e}")

    def do_stop_pump(self):
        """Send stop command to the pump"""
        if self.ser is None:
            messagebox.showwarning("Warning", "Pump not connected")
            return
        try:
            stop_pump(self.ser)
            messagebox.showinfo("Pump Command", "Stop command sent")
        except Exception as e:
            messagebox.showerror("Pump Error", f"Failed to send stop command:\n{e}")
    
    def close_app(self):
        """Close the application"""
        self.stop_monitoring()
        # Cancel any pending callbacks
        if self.pending_callback:
            self.root.after_cancel(self.pending_callback)
        if self.plot_callback:
            try:
                self.root.after_cancel(self.plot_callback)
            except Exception:
                pass
        if self.ser:
            try:
                close_comm(self.ser)
            except Exception as e:
                print(f"Error closing serial connection: {e}")
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
