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

# Add some specific options for this tool
# These default values calibrate pretty well
parser.add_argument('sweep', metavar='SWEEP', type=float, default=2.5, help='Sweep TCAL until this voltage.')

# Handle common configuration due to the common arguments
ifc, args, eventQueue = lappdTool.connect(parser)

# This is the fork() point, so it needs to be inside the
# script called.
if __name__ == "__main__":
    intakeProcesses = lappdTool.spawn(args, eventQueue)

############## COMMON TOOL INITIALIZATION END ##############

# Tell the user what we are dusering
print("# CMOFS: %f\n# TCAL_start: %f\n# TCAL_stop: %f\n# ROFS: %f" % (args.cmofs, args.tcal, args.sweep, args.rofs))

# Define an event list
evts = []

# Set the number of samples in each sweep
for voltage in np.linspace(args.tcal, args.sweep, args.N):

    # Set the values
    ifc.DacSetVout(lappdTool.DAC_TCAL_N1, voltage)
    ifc.DacSetVout(lappdTool.DAC_TCAL_N2, voltage)

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
            filtered = list(filter(None, evt.channels[chan]))
            if not len(filtered):
                curves[chan].append( (evt.voltage, float('nan')))
            else:
                curves[chan].append( (evt.voltage, statistics.mean(filtered)))

    # Now output the results
    for channel, results in curves.items():
        print("# BEGIN CHANNEL %d" % channel)
        for voltage, value in results:
            print("%e %e %d" % (voltage, value, channel))
        print("# END OF CHANNEL %d\n" % channel)
        
############# BEGIN COMMON TOOL FOOTER

# Reap listeners
lappdTool.reap(intakeProcesses, args)

############# END COMMON TOOL FOOTER 
