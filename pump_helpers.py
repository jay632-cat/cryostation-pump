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

if __name__ == "__main__":
    print("Hello World")
    open_comm()


