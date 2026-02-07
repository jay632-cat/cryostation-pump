# %%
import tkinter as tk
from tkinter import ttk, messagebox
import threading
from pump_helpers import open_comm, close_comm, get_pressure_reading, get_pressure_units


class PumpGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Cryostation Pump Monitor")
        self.root.geometry("400x400")
        self.root.resizable(False, False)
        
        self.ser = None
        self.monitoring = False
        self.update_interval = 1000  # milliseconds
        self.pending_callback = None  # Track pending callbacks
        
        self.setup_ui()
        self.connect_pump()

        
    def setup_ui(self):
        """Create the user interface"""

        # Title frame
        title_frame = ttk.Frame(self.root)
        title_frame.pack(pady=10)
        
        title_label = ttk.Label(title_frame, text="Pump Pressure Monitor", 
                                font=("Arial", 16, "bold"))
        title_label.pack()
        
        # Status frame
        status_frame = ttk.LabelFrame(self.root, text="Connection Status", padding=10)
        status_frame.pack(padx=10, pady=10, fill="x")
        
        self.status_label = ttk.Label(status_frame, text="Disconnected", 
                                      foreground="red", font=("Arial", 10))
        self.status_label.pack()
        
        # Pressure display frame
        pressure_frame = ttk.LabelFrame(self.root, text="Pressure Reading", padding=20)
        pressure_frame.pack(padx=10, pady=10, fill="both", expand=True, side="top")
        
        # Pressure value
        self.pressure_label = ttk.Label(pressure_frame, text="-- ", 
                                        font=("Arial", 36, "bold"), foreground="blue")
        self.pressure_label.pack()
        
        # Pressure units
        self.units_label = ttk.Label(pressure_frame, text="--", 
                                     font=("Arial", 14))
        self.units_label.pack()
        
        # Control frame
        control_frame = ttk.Frame(self.root)
        control_frame.pack(pady=10, side="bottom", fill="x", padx=10)
        
        self.start_button = ttk.Button(control_frame, text="Start Monitoring", 
                                       command=self.start_monitoring)
        self.start_button.pack(side="left", padx=5, fill="x", expand=True)
        
        self.stop_button = ttk.Button(control_frame, text="Stop Monitoring", 
                                      command=self.stop_monitoring, state="disabled")
        self.stop_button.pack(side="left", padx=5, fill="x", expand=True)
        
        close_button = ttk.Button(control_frame, text="Close", 
                                  command=self.close_app)
        close_button.pack(side="left", padx=5, fill="x", expand=True)
        
    def connect_pump(self):
        """Establish serial connection to pump"""
        try:
            self.ser = open_comm()
            self.status_label.config(text="Connected", foreground="green")
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
        self.update_pressure()
        
    def stop_monitoring(self):
        """Stop continuous pressure monitoring"""
        self.monitoring = False
        self.start_button.config(state="normal")
        self.stop_button.config(state="disabled")
        
    def update_pressure(self):
        """Update pressure reading from pump"""
        self.pending_callback = None  # Clear callback reference
        if self.monitoring and self.ser:
            try:
                pressure = get_pressure_reading(self.ser)
                units = get_pressure_units(self.ser)
                
                self.pressure_label.config(text=pressure, foreground="blue")
                self.units_label.config(text=units)
                
            except Exception as e:
                self.pressure_label.config(text="Error", foreground="red")
                self.units_label.config(text=str(e))
                print(f"Error reading pressure: {e}")
            
            # Schedule next update only if still monitoring
            if self.monitoring:
                self.pending_callback = self.root.after(self.update_interval, self.update_pressure)
    
    def close_app(self):
        """Close the application"""
        self.stop_monitoring()
        # Cancel any pending callbacks
        if self.pending_callback:
            self.root.after_cancel(self.pending_callback)
        if self.ser:
            try:
                close_comm(self.ser)
            except Exception as e:
                print(f"Error closing serial connection: {e}")
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = PumpGUI(root)
    root.mainloop()
