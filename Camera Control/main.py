import machine
import time
from machine import UART #type: ignore
from machine import Pin #type: ignore
from machine import PWM #type: ignore

com = UART(0, 9600) #type: ignore
servo = machine.PWM(machine.Pin(12), freq=50)
servo.duty_u16(77)
best = 0
SMOOTHING = 0.8



#FUNCTIONS
def move_amount(direction, dif, best):
    global servo
    dif = int(dif)
    differance = dif - best
    if abs(differance) < 10 and best > 250:
        return
    SMOOTHING = max(0.1, min(0.99, (abs(differance) + 1) ** (-abs(differance)/1000)))
    if best < 200:
        #coarse
        if direction == 'I':
            servo.duty_u16(115)
        elif direction == 'O':
            servo.duty_u16(40)

    elif best > 100:
        #fine
        if direction == 'I':
            servo.duty_u16(max(77 + int(differance * (1 - SMOOTHING)), 115))
        elif direction == 'O':
            servo.duty_u16(min(77 - int(differance * (1 - SMOOTHING)), 40))
    time.sleep(0.5)
    servo.duty_u16(77)
    best = dif if dif > best else best
    return best




# main loop
while True:
    poll = com.any()
    if poll:
        comand = com.readline()
        comand = comand.decode('utf-8')
        direction = comand[-1:]
        dif = comand[:-1]
        best = move_amount(direction, dif, best)
    
    