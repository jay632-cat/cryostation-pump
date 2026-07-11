#License
#-------
#This code is published and shared by Numato Systems Pvt Ltd under GNU LGPL 
#license with the hope that it may be useful. Read complete license at 
#http://www.gnu.org/licenses/lgpl.html or write to Free Software Foundation,
#51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA
 
#Simplicity and understandability is the primary philosophy followed while
#writing this code. Sometimes at the expence of standard coding practices and
#best practices. It is your responsibility to independantly assess and implement
#coding practices that will satisfy safety and security necessary for your final
#application.
 
#This demo code demonstrates how to turn ON, OFF, read a relay, set, clear, read a GPIO and read an analog channel.


#%%
'''Prerequisites : Python 3.x , install serial module using pip'''

import serial
from scroll_relay_helpers import (
    init_relay_comm,
    close_relay_comm,
    send_command,
    turn_on_relay,
    turn_off_relay,
    read_relay_state
)
 
def main():
    port_name = "COM1"  # Replace with your actual COM port
    baud_rate = 19200
    timeout = 1
 
    try:
        with serial.Serial(port_name, baud_rate, timeout=timeout) as ser_port:
            
            # ADC Channel
            adc_channel = 0  
            
            if isinstance(adc_channel, int) and 0 <= adc_channel <= 5:
            
                # Example 1: Read from ADC channel 0
                adc_command = f"adc read {adc_channel}\r"
                adc_response = send_command(ser_port, adc_command)
                adc_value = adc_response[12:-3]
                print(f"ADC Read {adc_channel} is: {adc_value}")
                
            else:
                print("Error: adc_channel must be one of the digits between 0 and 5.")

            # GPIO number
            gpio_number = 5
            
            if isinstance(gpio_number, int) and 0 <= gpio_number <= 7:
                
                # Example 2: Set GPIO pin 5
                gpio_set_command = f"gpio set {gpio_number}\r"
                send_command(ser_port, gpio_set_command)
                print(f"GPIO {gpio_number} set successfully.")
     
                # Example 3: Read GPIO pin 5
                gpio_read_command = f"gpio read {gpio_number}\r"
                gpio_response = send_command(ser_port, gpio_read_command)
                gpio_state = gpio_response[-4:-3]
                print(f"GPIO {gpio_number} state is: {gpio_state}")
                
                # Example 4: Clear GPIO pin 5
                gpio_clear_command = f"gpio clear {gpio_number}\r"
                send_command(ser_port, gpio_clear_command)
                print(f"GPIO {gpio_number} cleared successfully.")
                
                # Example 5: Read GPIO pin 5
                gpio_read_command = f"gpio read {gpio_number}\r"
                gpio_response = send_command(ser_port, gpio_read_command)
                gpio_state = gpio_response[-4:-3]
                print(f"GPIO {gpio_number} state is: {gpio_state}")
                
            else:
                print("Error: GPIO number must be one of the digits between 0 and 7.")

            # Relay number
            relay_number = 0
            
            if isinstance(relay_number, int) and 0 <= relay_number <= 1:

                # Example 6: ON Relay 0
                relay_on_command = f"relay on {relay_number}\r"
                send_command(ser_port, relay_on_command)
                print(f"Relay {relay_number} ON successfully.")
     
                # Example 7: Read Relay 0
                relay_read_command = f"relay read {relay_number}\r"
                relay_response = send_command(ser_port, relay_read_command)
                relay_state = relay_response[-5:-3]
                print(f"Relay {relay_number} state is: {relay_state}")
                
                # Example 8: OFF Relay 0
                relay_clear_command = f"relay off {relay_number}\r"
                send_command(ser_port, relay_clear_command)
                print(f"Relay {relay_number} OFF successfully.")
                
                # Example 9: Read Relay 0
                relay_read_command = f"relay read {relay_number}\r"
                relay_response = send_command(ser_port, relay_read_command)
                relay_state = relay_response[-6:-3]
                print(f"Relay {relay_number} state is: {relay_state}")
            
            else:
                print("Error: relay_number must be one of the digits between 0 and 1.")
            
    except serial.SerialException as e:
        print(f"Error opening or communicating with serial port: {e}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
 
if __name__ == "__main__":
    main()