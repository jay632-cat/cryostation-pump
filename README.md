# cryostation-pump
```markdown
# Cryostation Pump Monitor

A Python-based GUI application for monitoring and controlling a cryostation pump via RS-232 serial communication. The application displays real-time pressure readings, pump status, turbo speed, and tip seal life, with graphical visualization of pressure trends over time.

## Quick Start
For users:
1. Double-click `pump_gui.py` from the `cryostation_pump` folder on the computer desktop. The GUI should open along with a command line window.
2. The command line window monitors the RS232 communication with the pump. Do NOT close or touch this window. Close the GUI with the "Close" button in the GUI or the red X in the top right corner. (This is to ensure that the RS232 serial connection is fully closed upon GUI exit.)

For superusers (and anyone editing the codebase):
1. Reference the Agilent TPS-compact manual p. 214 for RS232 command structure.
2. When tip seal is changed, be sure to reset the tip seal life with `reset_tipseal_life()` in pump_helpers.py. 


## Author
Written by Jerry A. Yang (2026-02-06)
