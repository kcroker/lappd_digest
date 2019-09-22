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

    # Do even samples
    sample_list = [samples] * len(chan_list)

    # Make some linear offsets that scale evenly with the channel 
    offset_list = [math.floor(samples / len(chan_list)) * x for x in chan_list]

    # Make some ramp amplitudes (ramplitudes)
    ampl_list = []

    for chan, samples, offset in zip(chan_list, sample_list, offset_list):

        # Reset
        amplitudes = []
    
        # Make a line with (chan+1) slope and 0 intercept
        dom = np.linspace(0, 1, samples)
        ran = [(chan + 1) * t for t in dom]

        # Rescale to the resolution and crop if maxxed out
        ran = [round(y * (2**(2**resolution) - 1)) if y <= 1 else 1 for y in ran]

        # List out the offset amplitudes
        for i in range(0, samples):
            amplitudes.append(ran[ (offset + i) % samples ])

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
s.bind((socket.gethostbyname(sys.argv[1]), int(sys.argv[2])))

#
# TEST 1 -
#   Single channel
#   No compression (8 bit resolution, so 2^3)
#   No fragmentation (payload fits within an 1400 byte MTU)
#
############################################
run = linearTestEvent(1, 1024, 3)

for packet in run:
    s.send(packet)



