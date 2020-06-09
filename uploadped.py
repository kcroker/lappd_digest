#!/usr/bin/python3
import argparse
import pickle
import sys
import os

#import lappdProtocol
import lappdIfc

# Make a new tool
parser = argparse.ArgumentParser(description='Query/upload a pedestal to the board for firmware subtraction and zero suppression')

# Custom args
parser.add_argument('board', metavar='IP_ADDRESS', type=str, help='IP address of the target board')
parser.add_argument('-s' '--subtract', metavar='PEDESTAL_FILE', type=str, help='Pedestal to upload for subtraction.')

# Get dem args
args = parser.parse_args()

# EEVEE Register Protocol specific
#
#  Each register transaction becomes 8 bytes:
#   4 address, 4 value
#
#  An Ethernet MTU is ~1500, so 10^10 = 1024 is the closest power of 2
#  So 8=10^3 bytes per register
#  So batches of 2^7 make sense. 
#

# How many registers to set in one batch
batchSize = 128

# XXX
# Magic numbers about the uBlaze architecture
# and DRS4 internals
pedmem_baseptr = 0x01234567
numCaps = 1024
uBlazeWidth = 4

# Load a ped
pedestalCal = pickle.load(open(args.subtract, "rb"))

# Get the channels present in this pedestal
chans = pedestalCal.mean.keys()

# Connect to the board
ifc = lappdIfc.lappdInterface(args.board)

# Start setting pedestals
for chan in chans:

    print("Processing pedestal for channel %d" % chan)

    # Compute this once
    chan_offset = pedmem_baseptr + chan*numCaps*uBlazeWidth
    
    for batch_offset in range(0, len(pedestalCal.mean[chan]), batchSize):

        # Build the batch transaction
        for cap_offset in range(batchSize):

            # Build up the transaction
            ifc.brd.poke(chan_offset + batch_offset + cap_offset,
                         pedestalCal.mean[chan][batch_offset + cap_offset])
            
        # Execute the transaction
        response = ifc.brd.transact()

        # Feedback
        # (you should probably check that the response is the one you expected)
        # (and if its not, you should resend)
        print("\tUploaded %d pedestal values..." % batch_offset)
