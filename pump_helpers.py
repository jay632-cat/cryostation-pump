#%%
import serial
import serial.tools.list_ports
import sys
import re
import keyboard
from datetime import datetime

def open_comm():
    """Opens an RS-232 connection to pump"""
    ports = serial.tools.list_ports.comports()
    for port in ports:
        print(f"Port: {port.device}, Description: {port.description}, HWID: {port.hwid}")

    # Open a serial port
    ser = serial.Serial('COM6', 9600, timeout=1)

def close_comm(ser):
    print("Closing serial connection.")
    ser.close()
    
def get_pump_status(ser):
    """Sends a command to the pump to get its status and returns the response."""
    ser.write(b'STATUS\n')  # Send a command to get status
    response = ser.readline().decode('utf-8').strip()  # Read the response
    return response

def read_pump_status(ser):
    # Command: 02 80 32 30 35 30 03 38 37 ("read pump status" according to manual)
    # Command: 02 80 32 32 34 30 03 (for pump pressure)
    print(ser)

def set_pressure_units(ser, units = "Torr"):
    # Command: 02 80 31 36 33 (window: 163) 31 (write mode) 00/01/02 (data) 03 CRC
    print(ser)

def get_pressure_reading(ser):
    # Command: 02 80 32 32 34 (window: 224) 30 (read mode) 03 87 (CRC)
    
    print(ser)

def start_pump(ser):
    # Command: 02 80 30 30 30 31 31 03 42 33
    print(ser)

def calculate_crc(hex_str):
    # Convert hex string to bytes (handles 2-char chunks automatically)
    data = bytes.fromhex(hex_str)
    
    # Initialize result with 0 (XORing with 0 is a no-op)
    result = 0
    for byte in data:
        result ^= byte
        
    # Return result as a hex string (e.g., '0x1a')
    return hex(result)


if __name__ == "__main__":
    print("Hello World")
    print(calculate_crc("803232343003"))


# %%
