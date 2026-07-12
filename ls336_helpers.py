#%%
"""
Helper methods for communicating and running the Lakeshore 335 temp controller with GPIB

Make sure to set controller mode to "Remote" before communicating
"""
import pyvisa
import numpy as np
import time
import pandas as pd
import matplotlib.pyplot as plt

def open_connection():
    # Get connected instruments
    rm = pyvisa.ResourceManager()
    print(rm.list_resources())

    # Open connection to Lakeshore 335 temperature controller
    # If there is a connection error, check that the instruments are connected in NI MAX and that the GPIB addresses are correct
    ls336  = rm.open_resource("GPIB0::12::INSTR")
    print(ls336.query("*IDN?"))
    return (rm, ls336)

def close_connection(ls336):
    ls336.close()

def set_chuck_temp_setpt(ls336, temp):
    ls336.write("SETP 1,"+str(temp))

def get_temp(ls336, channel):
    # Channel: 'A' = sample, 'B' = rad shield
    temp =  float(ls336.query("KRDG? "+str(channel)))
    return temp

def set_ramp(ls336, ramp):
    # Used for setpoint ramping NOT for heater ramping, not used if setpoint is fixed
    ls336.write("RAMP 1,1,"+str(ramp))

def set_heater_range(ls336,heater, hrange):
    # Heater channel: 1 = sample, 2 = rad shield
    # Heater range: 0 = off, 1 low, 2 = med, 3 = high
    # Turns on heater
    if heater not in [1,2]:
        raise ValueError("Heater channel must be 1 or 2")
    ls336.write("RANGE "+str(heater)+","+str(hrange))

def set_heater_pid(ls336, heater, p, i, d): 
    # Heater channel: 1 = sample, 2 = rad shield
    # PID values: p, i, d
    if heater not in [1,2]:
        raise ValueError("Heater channel must be 1 or 2")
    ls336.write("PID "+str(heater)+","+str(p)+","+str(i)+","+str(d))

def set_temp_setpt(ls336,channel, temp):
    # Channel: 1 = sample, 2 = rad shield
    if channel not in [1,2]:
        raise ValueError("Channel must be 1 or 2")
    ls336.write("SETP "+str(channel)+","+str(temp))

def lock_front_panel(ls336,code):
    # 0 = unlocked, 1 = locked
    ls336.write("LOCK 1,"+str(code))

def set_remote_mode(ls336, onoff):
    # 0 = local, 1 = remote, 2 = remote with front panel lockout
    ls336.write("MODE "+str(onoff))

def get_heater_status(ls336, channel):
    # Channel: 1 = sample, 2 = rad shield
    if channel not in [1,2]:
        raise ValueError("Channel must be 1 or 2")
    return ls336.query("RANGE? "+str(channel))

def go_to_room_temp(ls336):
    print("Going to room temperature...")
    # Check chuck and rad shield temps, if they are above 300, turn off heaters and wait for cooldown
    chuck_temp = get_temp(ls336, 'A')
    rad_temp = get_temp(ls336, 'B')
    if chuck_temp > 300 or rad_temp > 300:
        print("Chuck or rad shield temp above 300K, turning off heaters...")
        set_heater_range(ls336, 1, 0)
        set_heater_range(ls336, 2, 0)
    else:
        print("Chuck and rad shield temps are below 300K, turning on heaters...")
        set_temp_setpt(ls336, 1, 296)
        set_temp_setpt(ls336, 2, 296)
        set_heater_pid(ls336, 1, 75, 35, 0)
        set_heater_pid(ls336, 2, 100, 20, 0)
        set_heater_range(ls336, 1, 3)
        set_heater_range(ls336, 2, 3)

def set_chuck_temp(ls336, temp):
    curtemp = get_temp(ls336, 'A')
    if temp > 350:
        print("Temperature setpoint too high! Command ignored.")
    elif temp > 300 and temp <= 350:
        print("Setting chuck temp to "+str(temp)+" K...")
        print("Make sure CCR is on!")
        set_heater_pid(ls336, 1, 65, 35, 0)
        set_temp_setpt(ls336, 1, temp)
        set_heater_range(ls336, 1, 3)
    elif temp <= 300 and temp >= 295:
        print("Setting chuck temp to "+str(temp)+" K...")
        print("Make sure CCR is on!")
        set_heater_pid(ls336, 1, 75, 35, 0)
        set_temp_setpt(ls336, 1, temp)
        set_heater_range(ls336, 1, 3)
    elif temp < 295 and temp >= 25:
        print("Setting chuck temp to "+str(temp)+" K...")
        set_heater_pid(ls336, 1, 75, 35, 0)
        set_temp_setpt(ls336, 1, temp)
        set_heater_range(ls336, 1, 3)
    elif temp < 25 and temp >= 15:
        print("Setting chuck temp to "+str(temp)+" K...")
        set_heater_pid(ls336, 1, 75, 35, 0)
        set_temp_setpt(ls336, 1, temp)
        set_heater_range(ls336, 1, 2)
    elif temp < 15 and temp >= 10:
        print("Setting chuck temp to "+str(temp)+" K...")
        set_heater_pid(ls336, 1, 75, 35, 0)
        set_temp_setpt(ls336, 1, temp)
        set_heater_range(ls336, 1, 1)
    elif temp < 10:
        print("Setting chuck temp base temperature...")
        set_heater_pid(ls336, 1, 75, 35, 0)
        set_temp_setpt(ls336, 1, temp)
        set_heater_range(ls336, 1, 0)
        set_heater_range(ls336, 2, 0)
    else:
        print("Temperature setpoint out of range! Command ignored.")
    
# def wait_for_stabilization(ls336, temp, timeout = -1):
#     # Wait for temp to stabilize
#     print("Wait for stabilization...")
#     t = time.localtime()
#     print("Started at: "+time.strftime("%H:%M:%S", t))
#     last5_temps = [25]
#     cur_temp = get_temp(ls336, 'A')  # Assuming 'A' is the sample channel
#     starttime = time.time()
#     endtime = starttime
#     while endtime-starttime < timeout:
#         last5_temps.append(cur_temp)
#         if len(last5_temps) > 5:
#             last5_temps.pop()
#         if len(last5_temps) == 5 and max(last5_temps)-min(last5_temps) <= 4 and last5_temps[4] == temp:
#             break
#         time.sleep(60)
#         endtime = time.time()

#     t = time.localtime()
#     print("Stabilization ended at: " + time.strftime("%H:%M:%S", t))

# # Temp in Kelvin, duration in seconds
# def heat_one_temp(ls336, temp, dwell, stabilize = False, progress_callback=None, abort_event=None):
#     """Heat to `temp` (K), dwell for `dwell` seconds.

#     If `progress_callback` is provided, it will be called periodically during the dwell
#     as: progress_callback(stage, start_ts, remaining_seconds, finish_ts)
#     where `stage` is one of 'start', 'progress', 'end'. Timestamps are epoch floats.
    
#     If `abort_event` is provided, the dwell will be interrupted when the event is set.
#     """
#     if temp <= 300:
#         print("Temperature setpoint too low! Turning heater off...")
#         set_heater_range(ls336, 1, 0)
#         return

#     # Set control to remote and set temp/heater range
#     set_remote_mode(ls336, 2)
#     set_temp_setpt(ls336, 1, temp)
#     set_heater_range(ls336, 1, 3) # Setting heater range turns on the output!
    
#     # Stabilization
#     if stabilize is True:
#         wait_for_stabilization(ls336, temp)

#     # Dwell for set time, in seconds
#     if dwell > 0:
#         start_ts = time.time()
#         finish_ts = start_ts + float(dwell)
#         try:
#             print("Start dwell at:"+time.strftime("%m/%d/%Y %H:%M:%S", time.localtime(start_ts)))
#         except Exception:
#             pass

#         # notify start
#         try:
#             if callable(progress_callback):
#                 try:
#                     progress_callback('start', start_ts, finish_ts - time.time(), finish_ts)
#                 except Exception:
#                     pass
#         except Exception:
#             pass

#         # loop with 1-second resolution to allow progress updates
#         remaining = finish_ts - time.time()
#         while remaining > 0:
#             # Check for abort signal
#             if abort_event is not None and hasattr(abort_event, 'is_set') and abort_event.is_set():
#                 print("Dwell interrupted by abort signal")
#                 break
#             try:
#                 sleep_time = 1.0 if remaining > 1.0 else remaining
#                 time.sleep(sleep_time)
#             except Exception:
#                 # if interrupted, break
#                 break
#             remaining = max(0.0, finish_ts - time.time())
#             try:
#                 if callable(progress_callback):
#                     try:
#                         progress_callback('progress', start_ts, remaining, finish_ts)
#                     except Exception:
#                         pass
#             except Exception:
#                 pass

#         try:
#             print("End dwell at:"+time.strftime("%m/%d/%Y %H:%M:%S", time.localtime()))
#         except Exception:
#             pass

#         # final notify
#         try:
#             if callable(progress_callback):
#                 try:
#                     progress_callback('end', start_ts, 0.0, finish_ts)
#                 except Exception:
#                     pass
#         except Exception:
#             pass

#         # Turn off heater and return to local control
#         set_heater_range(ls336, 1, 0)
#         set_remote_mode(ls336, 0)
    


# # %%

# %%
