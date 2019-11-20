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
parser = lappdTool.create("Make volatage response curves for the A21")

# Handle common configuration due to the common arguments
ifc, args, eventQueue = lappdTool.connect(parser)

# This is the fork() point, so it needs to be inside the
# script called.
if __name__ == "__main__":
    intakeProcesses = lappdTool.spawn(args, eventQueue)

############## COMMON TOOL INITIALIZATION END ##############

# DAC Channel mappings (in A21 crosshacked)
# (these should be moved to lappdIfc.py)
DAC_BIAS = 0
DAC_ROFS = 1
DAC_OOFS = 2
DAC_CMOFS = 3
DAC_TCAL_N1 = 4
DAC_TCAL_N2 = 5
# Other channels are not connected.

# At these values, unbuffered TCAL does not
# have the periodic pulse artifact (@ CMOFS 0.8)
#  TCAL_N   0.64 -> 0.73
#
# Note that in A21, CMOFS is tied to OOFS, so you can't change that one without
# undoing the effect on the other side of teh DRS4s
#
# DAC probably cares about OOFS being in a good spot... is it?

TCAL_start = 0.1 #0.0
TCAL_stop = 1.5 #2.5

# As per DRS4 spec, 1.55V gives symmetric
# differential inputs of -0.5V to 0.5V.
ROFS = 1.55

# Set the non-swept values
# For both sides of the DRS rows
CMOFS = 0.8
ifc.DacSetVout(DAC_CMOFS, CMOFS)
ifc.DacSetVout(DAC_ROFS, ROFS)

# Tell the user what we are dusering
print("# CMOFS: %f\n# TCAL_start: %f\n# TCAL_stop: %f\n# ROFS: %f" % (CMOFS, TCAL_start, TCAL_stop, ROFS))

# Define an event list
evts = []

# Set the number of samples in each sweep
for voltage in np.linspace(TCAL_start, TCAL_stop, args.N):

    # Set the values
    ifc.DacSetVout(DAC_TCAL_N1, voltage)
    ifc.DacSetVout(DAC_TCAL_N2, voltage)

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

# Get the channel list
# (the * expands the iterator)
chans = [*evts[0].channels.keys()]

# # Dump out the events to stdout
# for evt in evts:
#     lappdProtocol.dump(evt)
    
# # Rudimentary animated visualization of actual full reads
# import numpy as np
# import matplotlib.pyplot as plt
# from matplotlib.animation import FuncAnimation

# fig, ax = plt.subplots()
# xdata, ydata = [], []
# ln, = plt.plot([], [], 'ro')
# plt.grid(True)
# title = ax.text(0.5, 0.1, "", bbox={'facecolor':'w', 'alpha':0.5, 'pad':5},
#                                 transform=ax.transAxes, ha="center")

# def init():
#     ax.set_xlim(0, 1024)
#     ax.set_ylim(-(1<<15) - 5e3, (1<<15) + 5e3)
#     return ln, title,

# def update(frame):
#     title.set_text("TCAL_N = %f" % evts[frame].voltage)
#     ydata = evts[frame].channels[chans[0]]
#     ln.set_data(range(0, 1024), ydata)
#     return ln, title,

# ani = FuncAnimation(fig, update, frames=range(0, len(evts)), init_func=init, blit=True)
# plt.show()

# Gnuplot output, which an be fit for the gain calibration curve
if not args.subtract:
    print("Cannot compute gain curve without a pedestal", file=sys.stderr)
else:
    import statistics
    # Iterate over channels, because we want response curves per channel
    chans = evts[0].channels.keys()
    curves = {}
    
    for chan in chans:
    
        # Now we have a bunch of events, collapse down all the values into an average
        curves[chan] = []
    
        for evt in evts:
            # Save this data point (filtering out Nones)
            curves[chan].append( (evt.voltage, statistics.mean(filter(None, evt.channels[chan]))) )

    # Now output the results
    for channel, results in curves.items():
        print("# BEGIN CHANNEL %d" % channel)
        for voltage, value in results:
            print("%e %e %d" % (voltage, value, channel))
        print("# END OF CHANNEL %d\n" % channel)
        
############# BEGIN COMMON TOOL FOOTER

# Reap listeners
lappdTool.reap(intakeProcesses)

############# END COMMON TOOL FOOTER 
