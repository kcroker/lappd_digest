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
def generateSubhits(M, channel, samples, resolution, base_offset, max_samples):
    subhits = []

    for m in range(0, M):

        offset = base_offset + m*(samples + 50)
        if offset > max_samples-1:
            print("WARNING: offset exceeded maximum, wrapping", file=sys.stderr)
            offset = offset % max_samples

        print("Subhit offset is: %d" % offset, file=sys.stderr)
        
        # Just do a straight line omg
        subhit = [ (m+1)*(t - offset) + channel*100 for t in range(offset, offset+samples) ]
        
        subhits.append((offset, subhit))

    print(subhits)
    return subhits

# Event maker, event maker, make me an event
def linearTestEvent(channels, subhits, samples, resolution, base_offset):

    chan_list = [i for i in range(0, channels)]
    subhit_list = [generateSubhits(subhits, chan, samples, resolution, base_offset, lappd.HIT_FOOTER_MAGIC) for chan in chan_list]
    
    # Produce the event
    # Packets are in backwards order: all orphaned hits, followed by the event
    rawpackets = lappd.event.generateEvent(666, resolution, chan_list, subhit_list, lappd.HIT_FOOTER_MAGIC)

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
#run = linearTestEvent(1, 3, 200, 4)

# Wrap-around behaviour (with FOOTER_MAGIC=1000)
# VERIFIED
#run = linearTestEvent(1, 1, 2000, 4, 900)

# One wrap around, and a a further hit that does not wrap around
# but does overwrite (FM=1000)
# VERIFIED
# run = linearTestEvent(1, 2, 500, 4, 900)


run = linearTestEvent(1, 3, 300, 4, 575) + linearTestEvent(1, 4, 300, 4, 575)


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
    

