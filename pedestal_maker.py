#!/usr/bin/python3
import socket
import sys

import pedestal

# Parse params
if len(sys.argv) < 3:
    print("Usage: %s <host> <port>" % sys.argv[0])
    exit(1)

# Open a connection to the intake system
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.connect((socket.gethostbyname(sys.argv[1]), int(sys.argv[2])))

# Generate 100 synthetic pedestals, and send them as soon as I get them
for i in range(0, 200):
    pedestal_set = pedestal.generatePedestal(4, [i for i in range(0, 64)], 256, 0.1)  
    for packet in pedestal_set:
        s.send(packet)
