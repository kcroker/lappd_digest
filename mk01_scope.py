#!/usr/bin/python3
import sys
import numpy as np
import time

import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation

import lappdIfc            # Board+firmware *specific* stuff
import lappdProtocol       # Board+firmware *independent* stuff 
import lappdTool           # UX shortcuts: mixed board and protocol stuff 

#################### COMMON TOOL INITIALIZATION BEGIN ################

# Set up a new tool, with arguments common to the event digestion
# subsystem.  All tools will share the same baseline syntax and semantics.
parser = lappdTool.create("Measure per capacitor gain slopes between two given voltages")

# Add some specific options for this tool
parser.add_argument('--xmin', metavar='XMIN', type=float, default=0, help='Leftmost x-axis point')
parser.add_argument('--xmax', metavar='XMAX', type=float, default=1024, help='Rightmost x-axis point.')
parser.add_argument('--ymin', metavar='YMIN', type=float, default=-0.01, help='Bottommost y-axis point')
parser.add_argument('--ymax', metavar='YMAX', type=float, default=0.1, help='Topmost y-axis point.')
parser.add_argument('--gain', metavar='GAIN', type=int, default=51242, help='ADC counts per volt')

# Handle common configuration due to the common arguments
ifc, args, eventQueue = lappdTool.connect(parser)

# This is the fork() point, so it needs to be inside the
# script called.
if __name__ == "__main__":
    intakeProcesses = lappdTool.spawn(args, eventQueue)

############## COMMON TOOL INITIALIZATION END ##############

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.animation as animation

# Set up for multiplicative correction
args.gain = 1.0/args.gain

#fig, ax = plt.subplots()
fig = plt.figure()
ax = plt.axes()

ax.set_ylim(args.ymin, args.ymax)
ax.set_xlim(args.xmin, args.xmax)

ifc.brd.pokenow(0x320, (1 << 6), readback=False, silent=True)

# Notify that a trigger was sent
print("Initial trigger sent...", file=sys.stderr)

evt = eventQueue.get()

# Doesnt work with dictionaries?
lines = []
chans = []
for chan in evt.channels.keys():
    lines.append(ax.plot(np.linspace(args.xmin, args.xmax, 10), [0]*10)[0])
    chans.append(chan)
    
def animate(i):
    if not args.external:
        ifc.brd.pokenow(0x320, (1 << 6), readback=False, silent=True)

        # Notify that a trigger was sent
        print("Trigger sent...", file=sys.stderr)
        time.sleep(args.i)
    
    evt = eventQueue.get()

    
    # for chan, ampls in evt.channels:
    if isinstance(evt.channels[chans[0]][0], tuple):

        for n,line in enumerate(lines):
            xdata, ydata = zip(*evt.channels[chans[n]])
            ydata = [y * args.gain if y is not None else None for y in ydata]
            line.set_data(xdata, ydata)

    else:
        for n,line in enumerate(lines):
            xdata, ydata = zip(*enumerate(evt.channels[chans[n]]))
            ydata = [y * args.gain if y is not None else None for y in ydata]
            line.set_data(xdata, ydata)

    return lines#,

ani = animation.FuncAnimation(fig, animate, interval=10, blit=True, save_count=10)
plt.show()

