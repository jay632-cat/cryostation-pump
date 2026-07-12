#%% Run this GUI script to control the Lakeshore 335 temperature controller
"""
Simple tkinter GUI to connect to a Lakeshore 335 (via pyvisa) and monitor temperature.
- Enter a resource string (default: common GPIB form).
- Click Connect, then Start Monitor to poll temperature every second.
- If a local ls336_helpers.py exposes helper functions, those will be used.
"""
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import math
import threading
import time
from collections import deque
from datetime import datetime
import tkinter.font as tkfont
import csv
from threading import Event

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import matplotlib.ticker as mticker
# prefer Arial for matplotlib plots
try:
    matplotlib.rcParams["font.family"] = "Arial"
except Exception:
    pass

# try to use ls336_helpers if present in the project
try:
    import ls336_helpers  # type: ignore
    _HAS_HELPERS = True
except Exception:
    ls336_helpers = None
    _HAS_HELPERS = False

# try to import pyvisa for direct connection fallback
try:
    import pyvisa
    _HAS_PYVISA = True
except Exception:
    pyvisa = None
    _HAS_PYVISA = False

class LS336GUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("LS336 Monitor")
        self.resizable(True, True)
        self.base_font = ("Arial", 12)
        self.small_font = ("Arial", 11)
        self.title_font = ("Arial", 16, "bold")
        # set Tk default fonts to Arial
        try:
            tkfont.nametofont("TkDefaultFont").configure(family="Arial", size=12)
            tkfont.nametofont("TkTextFont").configure(family="Arial", size=12)
            tkfont.nametofont("TkMenuFont").configure(family="Arial", size=12)
            tkfont.nametofont("TkHeadingFont").configure(family="Arial", size=12, weight="bold")
        except Exception:
            pass

        try:
            style = ttk.Style(self)
            style.configure("TLabel", font=self.base_font)
            style.configure("TButton", font=self.base_font)
            style.configure("TEntry", font=self.base_font)
            style.configure("TLabelframe.Label", font=self.base_font)
        except Exception:
            pass

        # header (left column)
        hdr = ttk.Frame(self, padding=(10, 8, 10, 0))
        hdr.grid(column=0, row=0, columnspan=1, sticky="w")
        ttk.Label(hdr, text="Lake Shore 336 Heater Control Panel", font=self.title_font).grid(column=0, row=0, sticky="w")
        ttk.Label(hdr, text="Author: Jerry A. Yang", font=self.small_font).grid(column=0, row=1, sticky="w", pady=(2, 0))
        try:
            hdr.columnconfigure(0, weight=1)
        except Exception:
            pass
        # date under the author
        try:
            today = "July 10, 2026"
        except Exception:
            today = ''
        ttk.Label(hdr, text=f"Date: {today}", font=self.small_font).grid(column=0, row=2, sticky="w", pady=(0,2))

        # right-side plot frame spans header + main form rows so it fills full height
        plot_frame = ttk.Frame(self, padding=0)
        plot_frame.grid(row=0, column=1, rowspan=2, sticky="nsew")

        # main left form (below header)
        frm = ttk.Frame(self, padding=10)
        frm.grid(row=1, column=0, sticky="nsew")

        # connection group
        conn_box = ttk.LabelFrame(frm, text="Connection", padding=6)
        conn_box.grid(column=0, row=0, columnspan=3, sticky="ew")
        ttk.Label(conn_box, text="Resource:").grid(column=0, row=0, sticky="w")
        self.resource_var = tk.StringVar(value="GPIB0::12::INSTR")
        self.resource_entry = ttk.Entry(conn_box, textvariable=self.resource_var)
        self.resource_entry.grid(column=1, row=0, sticky="ew", padx=(6, 6))
        try:
            conn_box.columnconfigure(1, weight=1)
        except Exception:
            pass

        self.connect_btn = ttk.Button(conn_box, text="Connect", command=self.connect)
        self.connect_btn.grid(column=0, row=1, padx=(0, 6), pady=(6, 0), sticky="w")

        self.disconnect_btn = ttk.Button(conn_box, text="Disconnect", command=self.disconnect, state="disabled")
        self.disconnect_btn.grid(column=1, row=1, padx=(6, 0), pady=(6, 0), sticky="w")


        # temperature group
        temp_box = ttk.LabelFrame(frm, text="Temperature", padding=6)
        temp_box.grid(column=0, row=1, columnspan=3, sticky="ew", pady=(8,0))
        self.temp_channels = [
            ("A", "Sample (A)"),
            ("B", "Rad Shield (B)"),
            ("C", "Arm (C)"),
            ("D", "CCR (D)"),
        ]
        self.temp_colors = {
            "A": "#1f77b4",
            "B": "#ff7f0e",
            "C": "#2ca02c",
            "D": "#d62728",
        }
        self.temp_vars = {}
        for row_index, (channel, label_text) in enumerate(self.temp_channels):
            ttk.Label(temp_box, text=f"{label_text}:").grid(column=0, row=row_index, sticky="w")
            self.temp_vars[channel] = tk.StringVar(value="---")
            tk.Label(
                temp_box,
                textvariable=self.temp_vars[channel],
                font=("Arial", 16),
                fg=self.temp_colors.get(channel, "black"),
            ).grid(column=1, row=row_index, sticky="w", padx=(6,6))

        self.heater_status_labels = {
            1: "Heater 1",
            2: "Heater 2",
        }
        self.heater_status_vars = {}
        for offset, heater_channel in enumerate((1, 2)):
            ttk.Label(temp_box, text=f"{self.heater_status_labels[heater_channel]}:").grid(column=2, row=offset, sticky="w", padx=(12, 0))
            self.heater_status_vars[heater_channel] = tk.StringVar(value="---")
            tk.Label(
                temp_box,
                textvariable=self.heater_status_vars[heater_channel],
                font=("Arial", 13),
                fg="black",
            ).grid(column=3, row=offset, sticky="w", padx=(6, 0))

        try:
            temp_box.columnconfigure(1, weight=1)
        except Exception:
            pass

        self.conn_status_var = tk.StringVar(value="Disconnected")
        # place connection status inside the Connection box
        self.conn_status_label = tk.Label(conn_box, textvariable=self.conn_status_var, fg="red")
        self.conn_status_label.grid(column=0, row=2, columnspan=4, sticky="w", pady=(6, 0))

        # plot controls group (below Temperature)
        plot_box = ttk.LabelFrame(frm, text="Plot Controls", padding=6)
        plot_box.grid(column=0, row=2, columnspan=3, sticky="ew", pady=(8,0))

        self.start_btn = ttk.Button(plot_box, text="Start Monitor", command=self.start_monitor, state="disabled")
        self.start_btn.grid(column=0, row=0, padx=(0,6), sticky="w")

        self.stop_btn = ttk.Button(plot_box, text="Stop Monitor", command=self.stop_monitor, state="disabled")
        self.stop_btn.grid(column=1, row=0, padx=(0,6), sticky="w")

        self.clear_plot_btn = ttk.Button(plot_box, text="Clear Plot", command=self._on_clear_plot)
        self.clear_plot_btn.grid(column=2, row=0, padx=(0,6), sticky="w")
        self.save_plot_btn = ttk.Button(plot_box, text="Save Plot", command=self._on_save_plot)
        self.save_plot_btn.grid(column=3, row=0, padx=(0,0), sticky="w")

        try:
            plot_box.columnconfigure(4, weight=1)
        except Exception:
            pass

        # Set Temperature group (between Temperature and Recipe)
        set_temp_box = ttk.LabelFrame(frm, text="Set Temperature", padding=6)
        set_temp_box.grid(column=0, row=3, columnspan=3, sticky="ew", pady=(8,0))
        ttk.Label(set_temp_box, text="Set (K):").grid(column=0, row=0, sticky="w")
        self.set_temp_var = tk.StringVar(value="0")
        self.set_temp_entry = ttk.Entry(set_temp_box, textvariable=self.set_temp_var, width=12)
        self.set_temp_entry.grid(column=1, row=0, sticky="w", padx=(6,6))
        self.set_temp_btn = ttk.Button(set_temp_box, text="Set Temperature", command=self._on_set_temperature)
        self.set_temp_btn.grid(column=2, row=0, padx=(12,0))
        self.stop_heater_btn = ttk.Button(set_temp_box, text="Stop Heater", command=self._on_stop_heater)
        self.stop_heater_btn.grid(column=3, row=0, padx=(6,0))
        self.return_rt_btn = ttk.Button(set_temp_box, text="Return to RT for sample exchange", command=self._on_return_to_rt)
        self.return_rt_btn.grid(column=0, row=1, columnspan=4, sticky="ew", pady=(8,0))

        self.status_var = tk.StringVar(value="")
        self.status_label = ttk.Label(frm, textvariable=self.status_var)
        self.status_label.grid(column=1, row=4, columnspan=2, pady=(6, 0), sticky="ew")

        # connection objects
        self.instrument = None
        # polling continuously updates the Temperature label (runs while connected)
        self._polling = False
        self._poll_job = None
        # plotting/recording state (started/stopped by Start Monitor button)
        self._plotting = False

        # plotting buffers
        self._start_time = None
        self._times = deque(maxlen=86400)
        self._temp_buffers = {channel: deque(maxlen=86400) for channel, _ in self.temp_channels}

        # Matplotlib figure
        self.plot_fig = Figure(figsize=(5, 3), dpi=100)
        self.plot_ax = self.plot_fig.add_subplot(111)
        self.plot_ax.set_title("Temperature vs Time")
        self.plot_ax.set_xlabel("Time")
        self.plot_ax.set_ylabel("Temperature (K)")
        self.plot_lines = {}
        line_styles = {
            "A": {"color": "tab:blue", "label": "Sample (A)"},
            "B": {"color": "tab:orange", "label": "Rad Shield (B)"},
            "C": {"color": "tab:green", "label": "Arm (C)"},
            "D": {"color": "tab:red", "label": "CCR (D)"},
        }
        for channel, _label_text in self.temp_channels:
            style = line_styles.get(channel, {})
            line, = self.plot_ax.plot([], [], '-o', markersize=2, linewidth=1, **style)
            self.plot_lines[channel] = line
        self.plot_ax.legend(loc="best")
        self.plot_ax.grid(True)
        try:
            self.plot_ax.xaxis.set_major_formatter(mticker.FuncFormatter(self._format_time))
        except Exception:
            pass

        self.canvas = FigureCanvasTkAgg(self.plot_fig, master=plot_frame)
        self.canvas.draw()
        try:
            self.canvas.get_tk_widget().grid(row=0, column=0, sticky="nsew")
            plot_frame.columnconfigure(0, weight=1)
            plot_frame.rowconfigure(0, weight=1)
        except Exception:
            self.canvas.get_tk_widget().pack(fill="both", expand=True)
        # configure root grid so plot column expands and main row expands vertically
        try:
            self.columnconfigure(0, weight=0)
            self.columnconfigure(1, weight=1)
            self.rowconfigure(0, weight=0)
            self.rowconfigure(1, weight=1)
        except Exception:
            pass

        # start background silent connect
        try:
            threading.Thread(target=self._startup_connect, daemon=True).start()
        except Exception:
            pass

        # maximize window on startup (Windows: 'zoomed')
        try:
            self.state('zoomed')
        except Exception:
            try:
                # fallback to fullscreen
                self.attributes('-fullscreen', True)
            except Exception:
                pass

    def connect(self, silent: bool = False):
        resource = self.resource_var.get().strip()
        if _HAS_HELPERS and hasattr(ls336_helpers, "open_connection"):
            # prefer project helper connection if it is available
            try:
                helper_connection = ls336_helpers.open_connection()
                if isinstance(helper_connection, tuple) and len(helper_connection) >= 2:
                    self.instrument = helper_connection[1]
                else:
                    self.instrument = helper_connection
                helper_id = None
                try:
                    helper_id = self.instrument.query("*IDN?")
                except Exception:
                    helper_id = None
                # schedule UI update on main thread
                self.after(0, lambda: self._after_connected(helper_id.strip() if helper_id else "ls336_helpers"))
                return
            except Exception as e:
                self.instrument = None
                # fall back to pyvisa below

        if not _HAS_PYVISA:
            if not silent:
                # ensure messagebox shown on main thread
                self.after(0, lambda: messagebox.showerror("Missing dependency", "pyvisa is required for direct connection."))
            return
            

        try:
            rm = pyvisa.ResourceManager()
            inst = rm.open_resource(resource)
            # common termination settings for Lakeshore
            inst.write_termination = "\n"
            inst.read_termination = "\n"
            inst.timeout = 3000
            # quick id check
            try:
                _id = inst.query("*IDN?")
            except Exception:
                _id = None
            self.instrument = inst
            # schedule UI update on main thread
            self.after(0, lambda: self._after_connected(_id.strip() if _id else resource))
        except Exception as e:
            if not silent:
                # show error on main thread
                self.after(0, lambda: messagebox.showerror("Connection error", f"Failed to open resource:\n{e}"))
            self.instrument = None

    def _after_connected(self, id_or_resource: str):
        # must run on main thread
        self.conn_status_var.set(f"Connected ({id_or_resource})")
        try:
            self.conn_status_label.config(fg="green")
        except Exception:
            pass
        self._on_connected()

    def _startup_connect(self):
        # small delay to let UI finish initializing, then try connecting silently
        time.sleep(0.1)
        try:
            self.connect(silent=True)
        except Exception:
            pass

    def _on_connected(self):
        self.connect_btn.config(state="disabled")
        self.disconnect_btn.config(state="normal")
        self.start_btn.config(state="normal")
        # start continuous temperature polling when connected
        try:
            self.start_polling()
        except Exception:
            pass

    def _on_set_temperature(self):
        # validate input and send setpoint to instrument
        try:
            temp = float(self.set_temp_var.get())
        except Exception:
            messagebox.showerror("Invalid input", "Setpoint must be a number (K).")
            return

        if self.instrument is None:
            messagebox.showwarning("Not connected", "Connect to the instrument before setting temperature.")
            return

        if not messagebox.askyesno("Confirm CCR", "Is the CCR on?\n\nSelect No to cancel without changing anything.\n\nALL NON-RT samples, INCLUDING >300 K temps, require FULL cooldown to base pressure before heating up to desired temp!"):
            messagebox.showwarning("CCR required", "Temperature change canceled because the CCR is not confirmed on.")
            return

        try:
            if not _HAS_HELPERS:
                messagebox.showerror("Missing helper", "ls336_helpers is required to send commands to the controller.")
                return

            if hasattr(ls336_helpers, "set_chuck_temp"):
                ls336_helpers.set_chuck_temp(self.instrument, temp)
            else:
                messagebox.showerror("Missing helper", "ls336_helpers must provide set_chuck_temp().")
                return

            self.status_var.set(f"Setpoint sent: {temp:.3f} K")
            # Do not start plot recording automatically; temperature display polls continuously
        except Exception as e:
            messagebox.showerror("Error", f"Failed to set temperature: {e}")

    def _on_return_to_rt(self):
        if self.instrument is None:
            messagebox.showwarning("Not connected", "Connect to the instrument before returning to room temperature.")
            return

        if not _HAS_HELPERS or not hasattr(ls336_helpers, "go_to_room_temp"):
            messagebox.showerror("Missing helper", "ls336_helpers must provide go_to_room_temp().")
            return

        try:
            ls336_helpers.go_to_room_temp(self.instrument)
            self.status_var.set("Return-to-room-temperature command sent")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to return to room temperature: {e}")

    def _on_stop_heater(self):
        # Stop heater by setting heater range to 0 and set setpoint to 295 K via helpers only
        if not _HAS_HELPERS:
            messagebox.showerror("Missing helper", "ls336_helpers is required to send commands to the controller.")
            return

        if self.instrument is None:
            messagebox.showwarning("Not connected", "Connect to the instrument before stopping the heater.")
            return

        try:
            # set heater range to off (0)
            if hasattr(ls336_helpers, "set_heater_range"):
                ls336_helpers.set_heater_range(self.instrument, 0)
            elif hasattr(ls336_helpers, "write"):
                ls336_helpers.write("RANGE 1,0")
            else:
                messagebox.showerror("Missing helper", "ls336_helpers must provide `set_heater_range` or `write` to change heater range.")
                return

            # set setpoint to 295 K using helper
            if hasattr(ls336_helpers, "set_temp_setpt"):
                ls336_helpers.set_temp_setpt(self.instrument, 295)
            elif hasattr(ls336_helpers, "write"):
                ls336_helpers.write("SETP 1,295")
            else:
                messagebox.showerror("Missing helper", "ls336_helpers must provide `set_temp_setpt` or `write` to set setpoint.")
                return

            self.status_var.set("Heater stopped; setpoint set to 295 K")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to stop heater: {e}")

    def disconnect(self):
        # stop polling and plotting on disconnect
        try:
            self.stop_polling()
        except Exception:
            pass
        try:
            self.stop_monitor()
        except Exception:
            pass
        if self.instrument is not None:
            try:
                # if instrument from pyvisa, close resource
                if _HAS_PYVISA and hasattr(self.instrument, "close"):
                    self.instrument.close()
            except Exception:
                pass
        self.instrument = None
        self.connect_btn.config(state="normal")
        self.disconnect_btn.config(state="disabled")
        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="disabled")
        self.conn_status_var.set("Disconnected")
        try:
            self.conn_status_label.config(fg="red")
        except Exception:
            pass
        for var in getattr(self, "temp_vars", {}).values():
            try:
                var.set("---")
            except Exception:
                pass

    def _read_channel_temp(self, channel):
        if not self.instrument:
            return None
        try:
            if _HAS_HELPERS and hasattr(ls336_helpers, "get_temp"):
                return float(ls336_helpers.get_temp(self.instrument, channel))
        except Exception:
            pass
        try:
            raw = self.instrument.query(f"KRDG? {channel}")
            return float(str(raw).split(",")[0].strip())
        except Exception:
            return None

    def read_temp(self):
        # read temperature if instrument available; used by polling loop
        if not self.instrument:
            return
        try:
            readings = {}
            for channel, _label_text in self.temp_channels:
                readings[channel] = self._read_channel_temp(channel)

            for channel, value in readings.items():
                try:
                    if value is None or not math.isfinite(float(value)):
                        self.temp_vars[channel].set("Read error")
                    else:
                        self.temp_vars[channel].set(f"{float(value):.3f} K")
                except Exception:
                    pass

            heater_status_map = {
                0: "Off",
                1: "Low",
                2: "Medium",
                3: "High",
            }
            for heater_channel in (1, 2):
                try:
                    if _HAS_HELPERS and hasattr(ls336_helpers, "get_heater_status"):
                        raw_status = ls336_helpers.get_heater_status(self.instrument, heater_channel)
                    else:
                        raw_status = self.instrument.query(f"HTRST? {heater_channel}")
                    normalized = int(raw_status)
                    self.heater_status_vars[heater_channel].set(heater_status_map.get(normalized, str(normalized)))
                except Exception:
                    self.heater_status_vars[heater_channel].set("Read error")

            if getattr(self, "_plotting", False):
                now = datetime.now()
                if self._start_time is None:
                    self._start_time = now
                t = (now - self._start_time).total_seconds()
                try:
                    self._times.append(t)
                    for channel, _label_text in self.temp_channels:
                        value = readings.get(channel)
                        try:
                            self._temp_buffers[channel].append(float(value) if value is not None and math.isfinite(float(value)) else float("nan"))
                        except Exception:
                            self._temp_buffers[channel].append(float("nan"))
                    self._update_plot()
                except Exception:
                    pass
        except Exception as e:
            self.status_var.set(f"Read failed: {e}")

    def _update_plot(self):
        # update the matplotlib line with current buffers
        try:
            xs = list(self._times)
            if not xs:
                return
            all_y_values = []
            for channel, line in self.plot_lines.items():
                ys = list(self._temp_buffers.get(channel, []))
                line.set_data(xs[:len(ys)], ys)
                all_y_values.extend([value for value in ys if value is not None and math.isfinite(value)])
            min_x = min(xs)
            max_x = max(xs)
            self.plot_ax.set_xlim(max(0, min_x - 1), max_x + 1)
            if all_y_values:
                ymin = min(all_y_values)
                ymax = max(all_y_values)
                yrange = ymax - ymin if ymax > ymin else 1.0
                self.plot_ax.set_ylim(ymin - 0.1 * yrange, ymax + 0.1 * yrange)
            self.canvas.draw_idle()
        except Exception:
            pass

    def _format_time(self, x, pos=None):
        # x is seconds since start; format as hh:mm:ss
        try:
            h = int(x // 3600)
            m = int((x % 3600) // 60)
            s = int(x % 60)
            return f"{h:02d}:{m:02d}:{s:02d}"
        except Exception:
            return ""

    def _on_clear_plot(self):
        # Clear plotting buffers and redraw an empty plot
        try:
            self._start_time = None
            try:
                self._times.clear()
            except Exception:
                self._times = deque(maxlen=86400)
            try:
                self._temp_buffers = {channel: deque(maxlen=86400) for channel, _ in self.temp_channels}
            except Exception:
                pass
            try:
                for line in self.plot_lines.values():
                    line.set_data([], [])
                self.canvas.draw_idle()
            except Exception:
                pass
            try:
                self.status_var.set("Plot cleared")
            except Exception:
                pass
        except Exception:
            pass

    def _on_save_plot(self):
        # Save current plot data to CSV via a save dialog
        try:
            xs = list(self._times)
            if not xs:
                messagebox.showinfo("No data", "No plot data to save.")
                return

            fname = filedialog.asksaveasfilename(defaultextension=".csv",
                                                 filetypes=(("CSV files", "*.csv"), ("All files", "*.*")),
                                                 initialfile="temperature_plot.csv")
            if not fname:
                return

            try:
                with open(fname, "w", newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow(["time_s", "sample_A_K", "rad_shield_B_K", "arm_C_K", "ccr_D_K"])
                    channel_series = {channel: list(self._temp_buffers.get(channel, [])) for channel, _label_text in self.temp_channels}
                    for index, t in enumerate(xs):
                        row = [f"{t:.3f}"]
                        for channel, _label_text in self.temp_channels:
                            series = channel_series.get(channel, [])
                            value = series[index] if index < len(series) else float("nan")
                            row.append("" if value is None or not math.isfinite(value) else f"{value:.6f}")
                        writer.writerow(row)
                messagebox.showinfo("Saved", f"Plot data saved to {fname}")
            except Exception as e:
                messagebox.showerror("Save error", f"Failed to save CSV: {e}")
        except Exception:
            pass

    def _monitor_loop(self):
        # kept for compatibility; delegate to polling loop
        if getattr(self, "_polling", False):
            return
        # otherwise perform a single read
        self.read_temp()

    def start_monitor(self):
        # Start plot recording only (temperature polling runs continuously while connected)
        if not self.instrument:
            messagebox.showwarning("Not connected", "Connect first.")
            return
        if getattr(self, "_plotting", False):
            return
        self._plotting = True
        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        # reset plot buffers for a fresh recording
        try:
            self._start_time = None
            try:
                self._times.clear()
            except Exception:
                self._times = deque(maxlen=86400)
            try:
                self._temp_buffers = {channel: deque(maxlen=86400) for channel, _ in self.temp_channels}
            except Exception:
                pass
            try:
                for line in self.plot_lines.values():
                    line.set_data([], [])
                self.canvas.draw_idle()
            except Exception:
                pass
        except Exception:
            pass

    def stop_monitor(self):
        if not getattr(self, "_plotting", False):
            return
        self._plotting = False
        self.start_btn.config(state="normal")
        self.stop_btn.config(state="disabled")

    def _poll_loop(self):
        # continuous polling loop to update temperature label
        if not getattr(self, "_polling", False):
            return
        try:
            self.read_temp()
        except Exception:
            pass
        try:
            self._poll_job = self.after(1000, self._poll_loop)
        except Exception:
            pass

    def start_polling(self):
        if not self.instrument:
            return
        if getattr(self, "_polling", False):
            return
        self._polling = True
        self._poll_loop()

    def stop_polling(self):
        if not getattr(self, "_polling", False):
            return
        self._polling = False
        if self._poll_job:
            try:
                self.after_cancel(self._poll_job)
            except Exception:
                pass
            self._poll_job = None

if __name__ == "__main__":
    app = LS336GUI()
    app.mainloop()
# %%
