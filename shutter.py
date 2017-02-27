#!/usr/bin/python
#
# Features:
#
#    * Controls the movements of one shutter with end detectors
#    * Reads commands from stdin
#    * Add a command to get the shutter state (not precise)
#
# To be implemented:
#
#    * Add support for an external command via GPIO
#    * Handle multiple shutters
#    * Read commands from sockets (for i2c)
#    * Port to Arduino

import RPi.GPIO as gpio
import time
import sys
import select
import argparse

MOTOR_UP = 3
MOTOR_DOWN = 4
END_HIGH = 27
END_LOW = 17

# Motor states
STATE_STOP = 0
STATE_UP = 1
STATE_DOWN = 2

TIMEOUT = 0.1
DETECTOR_ON = 0
    
pin_names = ["MOTOR_UP", "MOTOR_DOWN",
             "END_HIGH", "END_LOW"]

verbose = False

# State computing variables
max_time = -1
state = -1
measure_start = 0
measure_end = 0
measuring = False

def debug(msg):
    if verbose:
        print msg

def get_pin_name(pin):
    for pin_name in pin_names:
        if globals()[pin_name] == pin:
            return pin_name
    return ""

def set_motor_pin_on(pin, on):
    low_level_values = {True: 0, False: 1}
    high_level_values = {True: 1, False: 0}

    value = high_level_values[on]

    # In the prototype, the motor up relay is
    # controlled by a PNP... thus low level
    if pin == MOTOR_UP:
        value =  low_level_values[on]

    gpio.output(pin, value)

def is_up():
    return gpio.input(END_HIGH) == DETECTOR_ON

def is_down():
    return gpio.input(END_LOW) == DETECTOR_ON

def get_motor_state():
    motor_state = -1

    if gpio.input(MOTOR_UP) == 1 and gpio.input(MOTOR_DOWN) == 0:
        motor_state = STATE_STOP
    elif gpio.input(MOTOR_UP) == 1 and gpio.input(MOTOR_DOWN) == 1:
        motor_state = STATE_DOWN
    elif gpio.input(MOTOR_UP) == 0 and gpio.input(MOTOR_DOWN) == 0:
        motor_state = STATE_UP
    else:
        debug ("Weird motor state, check the gpio status")

    return motor_state

def update_state():
    global state

    # What can we do if we don't know either
    # the initial position or the maximum opening time ?
    if state < 0 or max_time < 0:
        return

    direction = 0
    old_state = get_motor_state()
    if old_state == STATE_UP:
        direction = 1
    elif old_state == STATE_DOWN:
        direction = -1

    action_time = measure_end - measure_start
    delta_opening = 100 * direction * action_time / max_time

    new_state = state + delta_opening

    debug ("Initial state: %f, delta: %f, new_state: %f" % (state, delta_opening, new_state))

    # Fix potential rounding issues
    if new_state < 0:
        new_state = 0
    elif new_state > 100:
        new_state = 100

    # Safety checks
    if (new_state == 0 and not is_down()) or (new_state == 100 and not is_up()):
       debug ("We somehow lost the track of the shutter")
       state = -1

    state = new_state

def change_motor_state(state):
    global measure_start
    global measure_end

    measure_end = time.time()
    update_state()

    # Stop the motor before doing anything else
    set_motor_pin_on(MOTOR_UP, False)
    set_motor_pin_on(MOTOR_DOWN, False)
    debug ("Stopped")

    if state == STATE_UP:
        debug ("Opening...")
        measure_start = time.time()
        set_motor_pin_on(MOTOR_UP, True)
        set_motor_pin_on(MOTOR_DOWN, False)

    elif state == STATE_DOWN:
        debug ("Closing...")
        measure_start = time.time()
        set_motor_pin_on(MOTOR_UP, False)
        set_motor_pin_on(MOTOR_DOWN, True)

def reached_end(detector):
    global state

    # Give time for the value to be stable
    time.sleep(0.1)

    if gpio.input(detector) == DETECTOR_ON:
        debug ("Detector on: %s (%d)" % (get_pin_name(detector), detector))

        # When reaching the down state we may need
        # to wait some more time before stopping
        # While measuring we want to stop ASAP
        if detector == END_LOW and not measuring:
            time.sleep(1.5)

        # Do another test, as the shutter may have moved during the sleep
        if gpio.input(detector) == DETECTOR_ON:
            state = 0.0
            if detector == END_HIGH:
                state = 100.0
            change_motor_state(STATE_STOP)


def measure_speed(height):
    global max_time
    global measuring

    measuring = True

    # Move the shutter to the bottom
    change_motor_state(STATE_DOWN)
    while not (get_motor_state() == STATE_STOP and is_down()):
        time.sleep(2)
    
    # TODO When the manual button is implemented, inhibit it here.

    # Make sure that we got the reached_end stop
    time.sleep(3)

    change_motor_state(STATE_UP)
    while not (get_motor_state() == STATE_STOP and is_up()):
        time.sleep(2)

    measuring = False

    # Remove one second: the motor is maybe not at full speed all time
    max_time = measure_end - measure_start - 1
    speed = float(height) / max_time

    print speed

def get_shutter_state():
    if state >= 0:
        print state
    else:
        print "Unknown"

def print_help():
    print """------------------------------------------------------
Type one of the following commands followed by ENTER
to control the window shutter:

 up       : moves the shutter up

 down     : moves the shutter down

 stop     : stop any movement of the shutter

 state    : returns the percent of opening of
            the shutter.

 speed h  : measures the speed of the shutter with
            h being the height of the shutter

 time t   : set the time to fully open the shutter with
            t being the time in seconds.
            Using this command, can save running 'speed'

 debug    : show the state of the GPIO pins and globals

 help     : print this help

 exit     : exit this shutter control program
 quit
------------------------------------------------------"""

def print_debug_state():
    print "  Name (pin): Value "
    print "------------------------"

    for pin_name in pin_names:
        pin = globals()[pin_name]
        value = gpio.input(pin)
        print "  %s (%d): %d " % (pin_name, pin, value)

    print ""
    print "State    : %f" % state
    print "Max time : %f" % max_time

def main_loop():
    global max_time

    keepRunning = True
    while keepRunning:
        ready = select.select([sys.stdin], [], [], TIMEOUT) [0]
        if ready:
            line = sys.stdin.readline()
            parts = line.strip().split()

            command = parts[0]
            args = []
            if len(parts) > 1:
                args = parts[1:]

            if command == "up":
                change_motor_state(STATE_UP) 
            elif command == "down":
                change_motor_state(STATE_DOWN)
            elif command == "stop":
                change_motor_state(STATE_STOP)
            elif command == "state":
                get_shutter_state()
            elif command == "speed":
                if len(args) != 1:
                    print "Missing height parameter"
                else:
                    measure_speed(args[0])
            elif command == "time":
                if len(args) != 1:
                    print "Missing time parameter"
                else:
                    max_time = float(args[0])
            elif command == "debug":
                print_debug_state()
            elif command == "help":
                print_help()
            elif command == "exit" or command == "quit":
                keepRunning = False

def main():
    global verbose

    parser = argparse.ArgumentParser(description="Window shutter control tool")
    parser.add_argument("-v","--verbose", action='store_true')


    gpio.setmode(gpio.BCM)

    gpio.setup([MOTOR_UP, MOTOR_DOWN], gpio.OUT)
    gpio.setup([END_HIGH, END_LOW], gpio.IN, pull_up_down=gpio.PUD_UP)
    gpio.add_event_detect(END_HIGH, gpio.FALLING, callback=reached_end, bouncetime=200)
    gpio.add_event_detect(END_LOW, gpio.FALLING, callback=reached_end, bouncetime=200)
    
    # Make sure the shutter is stopped when starting
    change_motor_state(STATE_STOP)

    try:
        args = parser.parse_args()
        verbose = args.verbose
        main_loop()
    except KeyboardInterrupt:
        pass

    gpio.cleanup()


if __name__ == '__main__':
   main()
   sys.exit(0)
