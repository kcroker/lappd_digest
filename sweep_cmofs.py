#!/usr/bin/python3
import numpy as np
import multiprocessing
import sys
import time

import lappdIfc
import lappd

#################### COMMON TOOL INITIALIZATION BEGIN ################

# Common arguments
parser = lappd.commonArguments("Make volatage response curves for the A21")

# Add any custom arguments here

# Parse the arguments
args = parser.parse_args()

# Connect to the board
ifc = lappdIfc.lappdInterface(args.board, udpsport = 8888)

# Initialize the board, if requested
if args.initialize:
    ifc.Initialize()

# Set the requested threads on the hardware side 
ifc.brd.pokenow(0x678, args.threads)

# Give the socket address for use by spawn()
ifc.brd.aimNBIC()
args.listen = ifc.brd.s.getsockname()[0]

# Get ready for events
eventQueue = multiprocessing.JoinableQueue()
if __name__ == "__main__":
    intakeProcesses = lappd.spawn(eventQueue, args)

############## COMMON TOOL INITIALIZATION END ##############

# DAC Channel mappings (in A21 crosshacked)
DAC_BIAS = 0
DAC_ROFS = 1
DAC_OOFS = 2
DAC_CMOFS = 3
DAC_TCAL_N1 = 4
DAC_TCAL_N2 = 5
# Other channels are not connected.

# Units in volts
TCAL_N = 1.55
CMOFS_start = 0.0
CMOFS_stop = 2.5

# As per DRS4 spec, 1.55V gives symmetric
# differential inputs of -0.5V to 0.5V.
ROFS = 0.8

# Set the non-swept values
# For both sides of the DRS rows
ifc.DacSetVout(DAC_TCAL_N1, TCAL_N)
ifc.DacSetVout(DAC_TCAL_N2, TCAL_N)
ifc.DacSetVout(DAC_ROFS, ROFS)

# Tell the user what we are dusering
print("# TCAL_N: %f\n# CMOFS_start: %f\n# CMOFS_stop: %f\n# ROFS: %f" % (TCAL_N, CMOFS_start, CMOFS_stop, ROFS))

# Define an event list
evts = []

# Set the number of samples in each sweep
for voltage in np.linspace(CMOFS_start, CMOFS_stop, args.N):

    # Set the values
    ifc.DacSetVout(DAC_CMOFS, voltage)

    # Wait for it to settle
    time.sleep(args.i)

    # Software trigger
    ifc.brd.pokenow(0x320, 1 << 6)

    # Wait for the event
    evt = eventQueue.get()

    # Add some info and stash it
    evt.voltage = voltage
    evts.append(evt)
    
    # Give some output
    print("Received data for CMOFS = %f" % voltage, file=sys.stderr)

import statistics

# Iterate over channels, because we want response curves per channel
chans = evts[0].channels.keys()
curves = {}
for chan in chans:
    
    # Now we have a bunch of events, collapse down all the values into an average
    curves[chan] = []
    
    for evt in evts:
        # Save this data point
        # curves[chan].append( (evt.voltage, statistics.mean(evt.channels[chan]) ))
        curves[chan].append( (evt.voltage, evt.channels[chan][307] ))

# Now output the results
for channel, results in curves.items():
    print("# BEGIN CHANNEL %d" % channel)
    for voltage, value in results:
        print("%e %e %d" % (voltage, value, channel))
    print("# END OF CHANNEL %d\n" % channel)
        
############# BEGIN COMMON TOOL FOOTER

# Reap listeners
lappd.reap(intakeProcesses)

############# END COMMON TOOL FOOTER 
