#!/usr/bin/python3
import numpy as np
import sys
import time

import lappdIfc            # Board+firmware *specific* stuff
import lappdProtocol       # Board+firmware *independent* stuff 
import lappdTool           # UX shortcuts: mixed board and protocol stuff 

#################### COMMON TOOL INITIALIZATION BEGIN ################

# Set up a new tool, with arguments common to the event digestion
# subsystem.  All tools will share the same baseline syntax and semantics.
parser = lappdTool.create("Measure per capacitor gain slopes between two given voltages")

# Add some specific options for this tool
# These default values calibrate pretty well
parser.add_argument('low', metavar='LOW', type=float, default=0.7, help='Use this as the low voltage sample')
parser.add_argument('high', metavar='HIGH', type=float, default=1, help='Use this value as the high voltage sample')

# Handle common configuration due to the common arguments
ifc, args, eventQueue = lappdTool.connect(parser)

# Force capacitor offsetting
args.offset = True

# This is the fork() point, so it needs to be inside the
# script called.
if __name__ == "__main__":
    intakeProcesses = lappdTool.spawn(args, eventQueue)

############## COMMON TOOL INITIALIZATION END ##############

# Tell the user what we are dusering
print("# CMOFS: %f\n# TCAL_low: %f\n# TCAL_high: %f\n# ROFS: %f" % (args.cmofs, args.low, args.high, args.rofs))

# Define an event list
evts = []

for voltage in (args.low, args.high):
    # Set the low value
    ifc.DacSetVout(lappdTool.DAC_TCAL_N1, voltage)
    ifc.DacSetVout(lappdTool.DAC_TCAL_N2, voltage)

    # Take N samples at both low and high
    for k in range(0, args.N):
        # Wait for it to settle
        time.sleep(args.i)

        # Software trigger
        ifc.brd.pokenow(0x320, 1 << 6, readback=False, silent=True)

        # Wait for the event
        evt = eventQueue.get()
            
        # Add some info and stash it
        evt.voltage = voltage
        evts.append(evt)

        # Give some output
        print("Received data for TCAL_N = %f" % voltage, file=sys.stderr)

############# BEGIN COMMON TOOL FOOTER

# Once we have all the events we need, go ahead and reap the listeners.
# If not, you are going to possible fill up with tons of hardware triggers
# and choke out.

# Reap listeners
lappdTool.reap(intakeProcesses)

############# END COMMON TOOL FOOTER 

# Get the channel list
# (the * expands the iterator)
chans = [*evts[0].channels.keys()]

# The slope denominator
run = args.high - args.low

# Iterate over channels, because we want response curves per channel
chans = evts[0].channels.keys()

caps_low = {}
caps_high = {}
slopes = {}

from scipy.stats import describe
import math

for chan in chans:
    
    # Now prepare to store the average gains
    caps_low[chan] = [[] for x in range(1024)]
    caps_high[chan] = [[] for x in range(1024)]
    slopes[chan] = [[] for x in range(1024)]
    
    # Filter out any masked capacitors
    for evt in evts:

        # In case the order is wonky for some reason?
        if evt.voltage == args.high:
            caps = caps_high[chan]
        else:
            caps = caps_low[chan]

        # Save this data point (filtering out Nones)
        for cap in range(1024):
            if evt.channels[chan][cap] is None:
                continue
            
            # Record it
            caps[cap].append(evt.channels[chan][cap])

    # Now caps are nicely sorted, take averages and std deviations
    for cap in range(1024):

        # Replace the lists with tuples containing the statistical dirt
        caps_high[chan][cap] = describe(caps_high[chan][cap])
        caps_low[chan][cap] = describe(caps_low[chan][cap])

        # Now make the slopes and propogated RMSs
        varhigh = caps_high[chan][cap].variance
        varlow = caps_low[chan][cap].variance

        ampl_variance = math.sqrt(caps_high[chan][cap].variance + caps_low[chan][cap].variance)/(run*math.sqrt(args.N))
        recip_k = run/(caps_high[chan][cap].mean - caps_low[chan][cap].mean)
        
        # We want recriprocal slopes
        slopes[chan][cap] = ( recip_k, recip_k**2 * ampl_variance)

# Output a correction file
import pickle
pickle.dump(slopes, open("%s.gains" % evts[0].board_id.hex(), "wb"))
    
# Now output the results
for channel, results in slopes.items():
    print("# BEGIN CHANNEL %d" % channel)
    for cap, value in enumerate(results):
        print("%d %e %e %d" % (cap, value[0], value[1], channel))
    print("# END OF CHANNEL %d\n" % channel)
        
