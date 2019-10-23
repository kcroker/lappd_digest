#!/usr/bin/python3

# Standard imports
import sys
import numpy as np
import socket
import math
import random

# Local imports
import lappd

# Make some subhits
# Lines with different slopes and different intervals
# m \in {0, 1 ,2}
#
# y[0:100] = m * (x - m) + channel
# y[200:300] = m * (x - m) + channel
# etc.
#
def generateSubhits(M, channel, samples, resolution, max_samples):
    subhits = []

    for m in range(0, M):
        dom = np.linspace(0, 1, math.ceil(((m+1)/M)*samples))
        offset = m*samples + 10*m
        subhit = [ math.floor((2 << (1 << resolution) - 1) * ((m+1) * (t - m/M) + channel) / 2.0 / (M + channel)) for t in dom]
        subhits.append((offset, subhit))

    print(subhits)
    return subhits

# Event maker, event maker, make me an event
def linearTestEvent(channels, subhits, samples, resolution):

    chan_list = [i for i in range(0, channels)]
    subhit_list = [generateSubhits(subhits, chan, samples, resolution, 1024) for chan in chan_list]
    
    # Produce the event
    # Packets are in backwards order: all orphaned hits, followed by the event
    rawpackets = lappd.event.generateEvent(666, resolution, chan_list, subhit_list, 1024)

    # Time order the packets?
    #rawpackets = rawpackets.reverse()
    
    # Randomly reorder the packets?
    #random.shuffle(rawpackets)
    
    return rawpackets

# Parse params
if len(sys.argv) < 3:
    print("Usage: %s <host> <port>" % sys.argv[0])
    exit(1)

# Open a connection to the intake system
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.connect((socket.gethostbyname(sys.argv[1]), int(sys.argv[2])))

########################### CHANNELS

# #
# # TEST 0
# #   Single channel
# #   No compression (8 bit resolution, so 2^3)
# #   No fragmentation (payload fits within an 1400 byte MTU)
# #
# # --> PASSED
# ############################################
# run = linearTestEvent(1, 700, 3)

# for packet in run:
#     s.send(packet)

#
# TEST 1-2
#   Two channels
#   No compression (8 bit resolution, so 2^3)
#   No fragmentation (payload fits within an 1400 byte MTU)
#
# --> PASSED
############################################
run = linearTestEvent(2, 4, 200, 4)

for packet in run:
    s.send(packet)

# #
# # TEST 3-5
# #   Three channels
# #   No compression (8 bit resolution, so 2^3)
# #   No fragmentation (payload fits within an 1400 byte MTU)
# #
# # --> PASSED
# ############################################
# run = linearTestEvent(3, 700, 3)

# for packet in run:
#     s.send(packet)

# #
# # TEST 6
# #   One channel
# #   Bit compression (4 bit resolution, so 2^2)
# #   No fragmentation (payload fits within an 1400 byte MTU)
# #
# # --> PASSED
# ############################################
# run = linearTestEvent(1, 2048, 2)

# for packet in run:
#     s.send(packet)

# ################## SPANNING TESTS

# # TEST 7 -
# #   One channel
# #   Byte spanning (16 bit resolution, so 2^4)
# #   No fragmentation (payload fits within an 1400 byte MTU)
# #
# # --> PASSED
# ############################################
# run = linearTestEvent(1, 512, 4)

# for packet in run:
#     s.send(packet)

# # TEST 8-10 -
# #   Three channels
# #   Byte spanning (16 bit resolution, so 2^4)
# #   No fragmentation (payload fits within an 1400 byte MTU)
# #
# # --> PASSED
# ############################################
# run = linearTestEvent(3, 512, 4)

# for packet in run:
#     s.send(packet)

# #################### FRAGMENTATION

# # TEST 11-12
# #   Two channels
# #   Byte spanning (16 bit resolution, so 2^4)
# #   Fragmentation, with non-zero remainder
# #
# # --> PASSED 
# ############################################
# run = linearTestEvent(2, 4000, 4)

# for packet in run:
#     s.send(packet)

# # TEST 13-15
# #   Three channels
# #   Byte packing (4 bit resolution, so 2^2)
# #   Fragmentation, with non-zero remainder
# #
# # --> PASSED
# ############################################
# run = linearTestEvent(3, 5749, 2)

# for packet in run:
#     s.send(packet)

# # TEST 16
# #   One channel
# #   Byte spanning (32 bit resolution, 2^5)
# #   Fragmentation, 0 remainder
# #
# # --> PASSED
# ###########################################
# run = linearTestEvent(1, 700, 5)

# for packet in run:
#     s.send(packet)

# # TEST 17
# #   One channel
# #   Byte packing (2 bit resolution, so 2^1)
# #   Fragmentation, 0 remainder
# #
# # --> PASSED
# #############################################
# run = linearTestEvent(1, 1400*8, 1)

# for packet in run:
#     s.send(packet)

# # TEST 18 -
# #   Three channels
# #   Byte packing (2 bit resolution, so 2^1)
# #   Fragmentation, 0 remainder
# #
# # --> PASSED
# ###########################################
# run = linearTestEvent(3, 1400*8, 1)

# for packet in run:
#     s.send(packet)

# # TEST 19 -
# #   Three channels
# #   Byte packing (1 bit resolution, so 2^0)
# #   No fragmentation
# #   Padding required (samples do not fill out a byte)
# #   Pathology: Channel count is subbyte
# #
# # --> PASSED
# ###########################################
# run = linearTestEvent(3, 3, 0)

# for packet in run:
#     s.send(packet)

# # TEST 20 -
# #   Three channels
# #   Byte packing (1 bit resolution, so 2^0)
# #   No fragmentation
# #   Padding required (samples do not fill out a byte)
# #   Fragmentation, odd remainder
# #
# # --> PASSED
# ###########################################
# run = linearTestEvent(3, 1400*8 + 3, 0)

# for packet in run:
#     s.send(packet)

# # TEST 21 -
# #   Three channels
# #   Byte packing (4 bit resolution, so 2^2)
# #   No fragmentation
# #   Padding required (samples do not fill out a byte)
# #   Fragmentation, odd remainder
# #
# # --> PASSED
# ###########################################
# run = linearTestEvent(3, 1400*2 + 1, 2)

# for packet in run:
#     s.send(packet)
    

