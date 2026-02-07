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
    return ser

def close_comm(ser):
    print("Closing serial connection.")
    ser.close()

def get_pressure_reading(ser):
    # Command: 02 80 32 32 34 (window: 224) 30 (read mode) 03 38 37 (CRC)
    print("Getting pressure reading...")
    cmd_str = "028032323430033837"
    cmd = bytes.fromhex(cmd_str)
    print(cmd)
    ser.write(cmd)
    data = ser.read(100)
    data = data[6:-6]
    pressure = data.decode('utf-8')
    return pressure

def get_pressure_units(ser):
    # Command: 02 80 31 36 33 (window: 163) 30 (read mode) 03 38 35 (CRC)
    print("Getting pressure units...")
    cmd_str = "02 80 31 36 33 30 03 38 37"
    ser.write(bytes.fromhex(cmd_str))
    data = ser.read(100)
    data = data[-4:-3].decode('utf-8')
    match data:
        case '0': return "mBar"
        case '1': return "Pascal"
        case '2': return "Torr"
        case _: return "Get units failed."

def get_turbo_speed(ser):
    # Command: 02 80 32 32 36 30 03 38 35
    print("Getting turbo speed...")
    cmd_str = "028032323630033835"
    cmd = bytes.fromhex(cmd_str)
    print(cmd)
    ser.write(cmd)
    data = ser.read(100)
    data = data[6:-6]
    speed = data.decode('utf-8')
    return speed

def get_tipseal_life(ser):
    # Command: 02 80 33 35 38 30 03 38 43 (CRC = 0x8D)
    print("Getting tip seal life...")
    cmd_str = "028033353830033843"
    cmd = bytes.fromhex(cmd_str)
    print(cmd)
    ser.write(cmd)
    data = ser.read(100)
    # data = data[6:-6]
    life = data.decode('utf-8')
    return life

def start_pump(ser):
    # Command: 02 80 30 30 30 31 31 03 42 33
    print("Starting pump...")
    cmd_str = "02803030303131034233"
    cmd = bytes.fromhex(cmd_str)
    print(cmd)
    ser.write(cmd)
    data = ser.read(100)
    # Check if the response indicates success
    if data == b'\x02\x80\x06\x03\x38\x35':
        success = True
    else:
        success = False
    return success

def stop_pump(ser):
    # Command: 02 80 30 30 30 31 30 03 42 32
    print("Stopping pump...")
    cmd_str = "02803030303130034232"
    cmd = bytes.fromhex(cmd_str)
    print(cmd)
    ser.write(cmd)
    data = ser.read(100)
    # Check if the response indicates success
    if data == b'\x02\x80\x06\x03\x38\x35':
        success = True
    else:
        success = False
    return success

def get_pump_status(ser):
    # Command: 02 80 30 30 30 30 03 38 33
    print("Getting pump status...")
    cmd_str = "02803030303030033833"
    cmd = bytes.fromhex(cmd_str)
    print(cmd)
    ser.write(cmd)
    data = ser.read(100)
    # Check if the response indicates success
    if data[-4:-3] == b'1':
        status = "Running"
    elif data[-4:-3] == b'0':
        status = "Stopped"
    else:
        status = "Unknown"
    return status

def calculate_crc(hex_str):
    # Convert hex string to bytes (handles 2-char chunks automatically)
    data = bytes.fromhex(hex_str)
    
    # Initialize result with 0 (XORing with 0 is a no-op)
    result = 0
    for byte in data:
        result ^= byte
        
    # Return result as a hex string (e.g., '0x1a')
    return hex(result)


# %%
