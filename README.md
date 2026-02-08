# cryostation-pump
```markdown
# Cryostation Pump Monitor

A Python-based GUI application for monitoring and controlling a cryostation pump via RS-232 serial communication. The application displays real-time pressure readings, pump status, turbo speed, and tip seal life, with graphical visualization of pressure trends over time.

## Quick Start

### Prerequisites

- **Python 3.10+** (required for structural pattern matching)
- **Dependencies:** `pyserial`, `keyboard`, and `tkinter` (usually included with Python on Windows)

### Installation

1. Clone or download this repository
2. Install required packages:
   ```bash
   pip install pyserial keyboard
   ```

3. Run the application:
   ```bash
   python pump_gui.py
   ```

The GUI will open and attempt to connect to the pump on `COM6` (default port—see Configuration below if your device is on a different port).

## Overview

### Architecture

The application consists of two main modules:

- **[pump_gui.py](pump_gui.py)** – Tkinter-based graphical user interface, lifecycle management, and real-time monitoring loop
- **[pump_helpers.py](pump_helpers.py)** – Low-level serial communication, command construction, response parsing, and CRC calculations

### Hardware Integration

- **Interface:** RS-232 serial communication
- **Default Port:** `COM6` at 9600 baud
- **Protocol:** Binary hex command frames with small response payloads
- **CRC:** All commands include a checksum calculated via XOR; use `calculate_crc()` when crafting new commands

## Codebase Details

### pump_helpers.py

Provides low-level serial communication functions:

| Function | Purpose |
|----------|---------|
| `open_comm()` | Opens a serial connection to the pump on `COM6` at 9600 baud |
| `close_comm(ser)` | Closes the active serial connection |
| `get_pressure_reading(ser)` | Reads current pressure value from the pump |
| `get_pressure_units(ser)` | Reads pressure units (mBar, Pascal, or Torr) |
| `get_turbo_speed(ser)` | Reads turbo pump speed in RPM |
| `get_tipseal_life(ser)` | Reads tip seal remaining life in hours |
| `get_pump_status(ser)` | Returns "Running" or "Stopped" |
| `start_pump(ser)` | Sends start command to the pump |
| `stop_pump(ser)` | Sends stop command to the pump |
| `calculate_crc(hex_str)` | Calculates XOR checksum for a hex command string |

**Key implementation details:**
- Commands are hex strings converted to bytes via `bytes.fromhex()`
- Response parsing uses fixed slicing offsets (e.g., `data[6:-6]` for pressure)
- All responses are decoded as UTF-8 strings
- Device testing is the primary verification method for parsing correctness

### pump_gui.py

Implements the Tkinter GUI and monitoring logic:

#### Main Components

- **PumpGUI class** – Core application logic
  - `setup_ui()` – Constructs the user interface
  - `connect_pump()` – Establishes serial connection on startup
  - `start_monitoring()` – Begins continuous pressure polling
  - `stop_monitoring()` – Halts the polling loop
  - `update_pressure()` – Called periodically to fetch and display readings
  - `update_plot()` – Refreshes the matplotlib graph (optional)
  - `do_start_pump()` – Button callback that sends start command to pump (validates pump is stopped and turbo = 0)
  - `do_stop_pump()` – Button callback that sends stop command to pump
  - `save_plot_csv()` – Exports pressure history to CSV file

#### Configuration

Key settings in `PumpGUI.__init__()`:

```python
self.update_interval = 1000  # milliseconds between pressure reads
self.plot_interval = 5000    # milliseconds between plot updates
self.plot_maxlen = 360       # retain ~30 minutes of 5s samples
self.tip_sample_interval = 3600  # hours; sample tip seal life once per hour
```

#### Data Storage

- **hr_times, hr_pressures, hr_turbos** – High-resolution buffers (one sample per update)
- **times, prices, turbo_values** – Downsampled plot data (one point per plot interval)

#### Callback Management

- Uses `root.after()` for scheduling periodic updates
- Properly cancels pending callbacks on window close to avoid race conditions
- Maintains `pending_callback` and `plot_callback` references for cleanup

## Using the GUI

### Main Window Layout

The application uses a **two-panel layout:**

- **Left Panel:** Status display, pressure readings, and control buttons
- **Right Panel:** Real-time pressure vs. time graph (logarithmic pressure axis)

### Controls

| Button | Function |
|--------|----------|
| **Start Monitoring** | Begin continuous pressure polling and display updates |
| **Stop Monitoring** | Halt polling and graph updates |
| **Start Pump** | Send start command (only if pump is stopped and turbo = 0 rpm) |
| **Stop Pump** | Send stop command to the pump |
| **Save Plot CSV** | Export pressure history to a CSV file |
| **Close** | Stop monitoring and close the application |

### Display Information

- **Connection Status** – Shows "Connected" (green) or "Connection Failed" (red)
- **Pressure Reading** – Large blue text displaying current pressure value
- **Units** – Current pressure unit (mBar, Pascal, or Torr)
- **Turbo:** Turbo pump speed in RPM
- **Tip Seal Life:** Remaining tip seal life in hours (sampled once per hour)
- **Graph:** Real-time pressure trend with logarithmic y-axis; x-axis shows elapsed seconds since monitoring started

### Workflow Example

1. **Launch the application** – `python pump_gui.py`
2. **Verify connection** – Check that status shows "Connected" in green
3. **Click "Start Monitoring"** – Polling begins; pressure, turbo, and graph update every 1 second
4. **Optionally control the pump:**
   - Click "Start Pump" to start the pump (only if conditions are met)
   - Click "Stop Pump" to stop the pump
5. **View pressure trends** – Monitor the graph on the right panel
6. **Save data (optional)** – Click "Save Plot CSV" to export the pressure history
7. **Stop & Close** – Click "Stop Monitoring" then "Close" to exit

## Configuration

### Changing the COM Port

Edit `pump_helpers.py`, locate the `open_comm()` function (around line 7), and replace `'COM6'` with your device's port:

```python
def open_comm():
    """Opens an RS-232 connection to pump"""
    ports = serial.tools.list_ports.comports()
    for port in ports:
        print(f"Port: {port.device}, Description: {port.description}, HWID: {port.hwid}")
    
    # Change 'COM6' to your device port
    ser = serial.Serial('COM6', 9600, timeout=1)
    return ser
```

To find available ports, run a REPL:
```python
import serial.tools.list_ports
for port in serial.tools.list_ports.comports():
    print(f"Port: {port.device}, Description: {port.description}")
```

### Adjusting Update Intervals

In pump_gui.py, modify `PumpGUI.__init__()`:

- **Pressure poll rate:** Change `self.update_interval` (default 1000 ms)
- **Graph sample rate:** Change `self.plot_interval` (default 5000 ms)
- **Graph history length:** Change `self.plot_maxlen` (default 360 points ≈ 30 minutes at 5s intervals)
- **Tip seal sample rate:** Change `self.tip_sample_interval` (default 3600 seconds = 1 hour)

## CSV Export Format

When you click "Save Plot CSV," the file contains:

```
timestamp_iso,seconds_since_start,pressure,units
2026-02-07T14:23:45.123456,0.000,1.23e-05,mBar
2026-02-07T14:23:50.234567,5.111,1.35e-05,mBar
...
```

- **timestamp_iso** – ISO 8601 formatted timestamp
- **seconds_since_start** – Elapsed seconds since monitoring began (useful for relative time plotting)
- **pressure** – Pressure value at the sample time
- **units** – Pressure unit (mBar, Pascal, or Torr)

## Troubleshooting

### "Connection Failed" Error on Startup

**Cause:** The pump is not on `COM6` or is not connected.

**Solution:** 
1. Run `python -c "import serial.tools.list_ports; [print(f'{p.device}: {p.description}') for p in serial.tools.list_ports.comports()]"` to list available ports
2. Update `open_comm()` in pump_helpers.py with the correct port
3. Verify the USB-to-RS-232 cable is connected and the pump is powered on

### "Pump not connected" Warning

**Cause:** You clicked a monitoring button before the serial connection was established.

**Solution:** Verify that the status shows "Connected" (green). If not, see "Connection Failed" above.

### Cannot Start Pump

**Cause:** The pump is not in the stopped state or turbo pump speed is not zero.

**Solution:** Click "Stop Pump" first, wait for the turbo speed to drop to 0 rpm, then click "Start Pump".

### Graph Not Displaying

**Cause:** matplotlib is not installed.

**Solution:** Install it with `pip install matplotlib`. The GUI will work without matplotlib but will not display the graph.

### No Pressure Reading

**Cause:** Serial communication error or incorrect command/response parsing.

**Solution:** 
1. Enable debug output in the terminal to see raw serial data
2. Verify the device is powered and the RS-232 connection is secure
3. Use a USB-to-RS-232 sniffer to capture raw bytes and validate command/response formats against the pump's manual

## Technical Notes

- **Python 3.10+ Required:** Uses structural pattern matching (`match` statements)
- **Thread Safety:** No explicit threading is used; updates are scheduled via `root.after()`
- **Timeout Handling:** Serial reads timeout after 1 second; reads up to 100 bytes per call
- **Error Tolerance:** The monitoring loop continues on read errors; exceptions are logged to the terminal

## Contributing

When adding new features:

1. **New commands:** Add the hex command string to pump_helpers.py, calculate the CRC with `calculate_crc()`, implement request/response parsing, then expose via a new function
2. **New displays:** Add labels/widgets in `PumpGUI.setup_ui()` and update them in `update_pressure()`
3. **Testing:** Always test with a live pump; use a USB sniffer or loopback for validation

## License

(Add your license here, e.g., MIT, GPL, etc.)

## Author

Written by Jerry A. Yang (2026-02-06)
