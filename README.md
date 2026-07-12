# Cryostation Integrated Controller

This repository contains GUIs for cryostation control and monitoring.

The default app is the integrated interface that combines LS336 temperature control and pump monitoring in one window.

## Default Launch

Run:

python main.py

The integrated GUI keeps all controls/readouts on the left panel and all plots on the right panel.

## Pump COM Port Selection

In the integrated GUI:

1. Go to Pump Controls -> Serial Port.
2. Click Refresh Ports to populate available COM ports.
3. Select the desired COM port from the dropdown.
4. Click Connect Pump.

If no ports are detected, the selector falls back to COM6.

## Alternate Scripts

- integrated_cryo_gui.py: Combined LS336 + pump app.
- ls336_cryo_gui.py: LS336-only app.
- pump_gui.py: Pump-only app.

## Notes For Developers

1. RS-232 pump command details: see TPS-compact manual.
2. After tip seal replacement, use reset_tipseal_life() in pump_helpers.py.

## Author

Written by Jerry A. Yang
