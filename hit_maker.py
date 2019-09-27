#!/usr/bin/python3

import sys
import numpy as np
import socket
import math
import lappd
import random

# Event maker, event maker, make me an event
def linearTestEvent(maxchan, samples, resolution):
    # Do channels
    chan_list = range(0, maxchan)
    print(len(chan_list))
    
    # Do even samples
    sample_list = [samples] * len(chan_list)

    # Make some linear offsets that scale evenly with the channel 
    offset_list = [math.floor(samples / len(chan_list)) * x for x in chan_list]
    print(offset_list, file=sys.stderr)
    
    #offset_list = [0] * len(chan_list)
    
    # Make some ramp amplitudes (ramplitudes)
    ampl_list = []

    for chan, samples, offset in zip(chan_list, sample_list, offset_list):

        # Reset
        # amplitudes = []
    
        # Make a line with (chan+1) slope and 0 intercept
        dom = np.linspace(0, 1, samples)
        ran = [(chan + 1) * t for t in dom]

        # Rescale to the resolution and crop if maxxed out
        ran = [math.floor(y * (2**(2**resolution) - 1)) if y <= 1 else (2**(2**resolution) - 1) for y in ran]
        print(ran)
        
        # List out the offset amplitudes
        amplitudes = [ ran[(offset + i) % samples] for i in range(0, samples) ]

        # Add it
        ampl_list.append(amplitudes)

    # Produce the event
    rawpackets = lappd.event.generateEvent(666, resolution, chan_list, offset_list, ampl_list)

    return rawpackets

# Parse params
if len(sys.argv) < 3:
    print("Usage: %s <host> <port>" % sys.argv[0])
    exit(1)
    
# Open a connection to the intake system
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.connect((socket.gethostbyname(sys.argv[1]), int(sys.argv[2])))

#
# TEST 1 -
#   Single channel
#   No compression (8 bit resolution, so 2^3)
#   No fragmentation (payload fits within an 1400 byte MTU)
#
# --> PASSED
############################################
# run = linearTestEvent(1, 1024, 3)

# for packet in run:
#     s.send(packet)

#
# TEST 2 -
#   Two channels
#   No compression (8 bit resolution, so 2^3)
#   No fragmentation (payload fits within an 1400 byte MTU)
#
# --> PASSED
############################################
# run = linearTestEvent(2, 1024, 3)

# for packet in run:
#     s.send(packet)

#
# TEST 3 -
#   Three channels
#   No compression (8 bit resolution, so 2^3)
#   No fragmentation (payload fits within an 1400 byte MTU)
#
# --> PASSED
############################################
# run = linearTestEvent(3, 1024, 3)

# for packet in run:
#     s.send(packet)

#
# XXX
#   div by zero in the generator, which suggests that the receiving code will
#   also be broken
#
# TEST 4 -
#   One channel
#   Bit compression (4 bit resolution, so 2^2)
#   No fragmentation (payload fits within an 1400 byte MTU)
#
############################################
run = linearTestEvent(1, 2048, 2)

for packet in run:
    s.send(packet)

################## SPANNING TESTS

# TEST 5 -
#   One channel
#   Byte spanning (16 bit resolution, so 2^4)
#   No fragmentation (payload fits within an 1400 byte MTU)
#
# --> PASSED
############################################
# run = linearTestEvent(1, 512, 4)

# for packet in run:
#     s.send(packet)

# TEST 6 -
#   Three channels
#   Byte spanning (16 bit resolution, so 2^4)
#   No fragmentation (payload fits within an 1400 byte MTU)
#
# --> PASSED
############################################
# run = linearTestEvent(3, 512, 4)

# for packet in run:
#     s.send(packet)

#################### FRAGMENTATION

# TEST 7 -
#   Two channels
#   Byte spanning (16 bit resolution, so 2^4)
#   Fragmentation, with non-zero remainder
#
# --> PASSED 
############################################
# run = linearTestEvent(2, 4000, 4)

# for packet in run:
#     s.send(packet)

# TEST 8 -
#   One channel
#   Byte packing (4 bit resolution, so 2^2)
#   Fragmentation
#
############################################
# run = linearTestEvent(1, 3749, 2)

# for packet in run:
#     s.send(packet)


