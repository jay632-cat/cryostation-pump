<!-- Copilot instructions for cryostation-pump -->
# cryostation-pump — Copilot instructions

Purpose: help an AI contributor quickly understand how the pump monitor app works, what hardware it integrates with, and where to make safe changes.

- **Quick start (dev machine with Python >= 3.10):**
  - Install deps: `pip install pyserial keyboard` (Tkinter is usually included with Python on Windows).
  - Run the GUI: `python pump_gui.py` from the `cryostation-pump` directory.

- **Big picture:**
  - `pump_gui.py` is a small Tkinter app that opens a serial connection and repeatedly polls the pump for pressure.
  - `pump_helpers.py` implements low-level serial commands and helpers (`open_comm`, `close_comm`, `get_pressure_reading`, `get_pressure_units`, `calculate_crc`).
  - Communication is RS-232 over a COM port (the current code opens `COM6` in `open_comm()` by default).

- **Key files / where to look first:**
  - `pump_gui.py` — UI, lifecycle, and polling loop (see `PumpGUI.update_pressure()` and `update_interval`).
  - `pump_helpers.py` — serial command construction/parse and CRC logic. Use `calculate_crc()` when crafting new commands.

- **Hardware & integration notes:**
  - The code expects a serial (RS-232) pump; default port is `COM6`. Search for actual port on target machine and update `open_comm()` accordingly.
  - Expect binary command frames (hex strings) and small response payloads; many helper functions slice responses (e.g., `data[6:-6]`). Keep these offsets when modifying parsing unless you verify with the device.

- **Project-specific conventions & gotchas:**
  - Uses Python structural pattern matching (`match`) — requires Python 3.10+.
  - Serial reads are performed with `ser.read(100)` and then sliced — tests with a live device are the primary verification.
  - GUI uses `root.after()` for scheduling; cancel pending callbacks (`after_cancel`) before closing to avoid race conditions.

- **Common edits examples:**
  - Change poll frequency: update `self.update_interval` in `PumpGUI.__init__`.
  - Change COM port: edit `open_comm()` in `pump_helpers.py` or replace with a port-selection UI.
  - Add a new command: add a hex command string in `pump_helpers.py`, use `calculate_crc()` to validate, write with `ser.write(bytes.fromhex(...))`, and parse with `ser.read()`.

- **Testing & debugging tips:**
  - If the GUI shows "Connection Failed", call `open_comm()` in a small REPL to print available `serial.tools.list_ports.comports()`.
  - Use a USB-to-RS232 loopback or sniffer to inspect raw bytes when testing parsing changes.

- **Examples of good prompts for the agent:**
  - "Add a dropdown to `pump_gui.py` to choose the COM port and persist the choice."  — target: modify `open_comm()` and the GUI setup.
  - "Implement exponential backoff on serial reconnect attempts in `PumpGUI.connect_pump()`." — target: `connect_pump()` and error handling.

If anything is unclear about the hardware protocol, ask for a device manual or a sample device response hex dump.
