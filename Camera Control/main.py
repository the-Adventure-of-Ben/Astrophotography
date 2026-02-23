import micropython
import machine 
import time
import math
from machine import UART 
from machine import Pin 
from machine import PWM

state = "HOMING"
com = UART(0, 9600)
servo = machine.PWM(machine.Pin(12), freq=50)
servo.duty_u16(0)

switch_pin_max = Pin(14, Pin.IN, Pin.PULL_UP)
switch_pin_min = Pin(13, Pin.IN, Pin.PULL_UP)

metric = 0
prev_metric = 0
power = 0
poll = None
timestamps = [0,0]

def limit_callback(pin):
    global state
    if state != "AT_MIN" and state != "AT_MAX":
        pin.irq(handler=None)
        micropython.schedule(limit_handler, pin)
    else:
        pass

def limit_handler(pin):
    global state
    if pin == switch_pin_min:
        state = "AT_MIN"
        
    elif pin == switch_pin_max:
        state = "AT_MAX"

switch_pin_min.irq(trigger=Pin.IRQ_FALLING, handler=limit_callback)
switch_pin_max.irq(trigger=Pin.IRQ_FALLING, handler=limit_callback)

def servo_stop():
    global servo
    servo.duty_u16(0)

def servo_move_in():
    global power, servo
    amount = math.pow(2,(189*power)/2000)+7*power
    amount = math.floor(amount)
    servo.duty_u16(amount)
    
def servo_move_out():
    global power, servo
    amount = (2*math.pow((889*power)/10000)+9*power+3350)/2
    amount = math.floor(amount)
    servo.duty_u16(amount)
    
def min_bounce():
    global servo
    servo.duty_u16(0)
    time.sleep_ms(50)
    servo.duty_u16(2600)
    time.sleep_ms(50)
    servo.duty_u16(0)
    switch_pin_min.irq(trigger=Pin.IRQ_FALLING, handler=limit_callback)
    
def max_bounce():
    global servo
    servo.duty_u16(0)
    time.sleep_ms(50)
    servo.duty_u16(400)
    time.sleep_ms(50)
    servo.duty_u16(0)
    switch_pin_max.irq(trigger=Pin.IRQ_FALLING, handler=limit_callback)

def servo_home():
    global servo
    servo.duty_u16(1000)
    
def servo_power(metric, dt, prev_metric):
    global desired_direction, power
    diff = metric - prev_metric
    power = diff/dt
    if diff > 0:
        desired_direction = "OUT"
    elif diff < 0:
        desired_direction = "IN"

while True:
    try:
        poll = com.any()
    except Exception:
        pass
    if poll:
        timestamps[0] = timestamps[1]
        timestamps[1] = time.ticks_us()
        dt = time.ticks_diff(timestamps[1],timestamps[0])
        comand = com.readline()
        prev_metric = metric
        metric = int(comand.decode('utf-8'))
        servo_power(metric, dt, prev_metric)

    if state == "IDLE":
        servo_stop()

    elif state == "HOMING":
        servo_home()

    elif state == "MOVING_IN":
        servo_move_in()
        time.sleep_ms(50)
        state = "IDLE"

    elif state == "MOVING_OUT":
        servo_move_out()
        time.sleep_ms(50)
        state = "IDLE"

    elif state == "AT_MIN":
        servo_stop()
        min_bounce()
        state = "IDLE"

    elif state == "AT_MAX":
        servo_stop()
        max_bounce()
        state = "IDLE"
        
    else:
        if desired_direction == "IN":
            servo_move_in()
        elif desired_direction == "OUT":
            servo_move_out()
        else:
            servo_stop()
