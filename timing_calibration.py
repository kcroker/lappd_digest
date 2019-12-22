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
parser = lappdTool.create("Build a timing calibration from TCA sine samples")

# Since we want high precision here, add the option to correct per-capacitor gains
parser.add_argument('-g', '--gain', metavar='GAIN_FILE',  help='Convert ADC counts into voltage using this gain profile')
parser.add_argument('-D', '--deltas', metavar='CHIP_DELTAS_FILE', help='Input externally measured interchip timing offsets')

# Handle common configuration due to the common arguments
ifc, args, eventQueue = lappdTool.connect(parser)

# Turn off external respose
lappdTool.externalOff()

# Die if no pedestal is given
if not args.subtract:
    print("ERROR: You must provide a pedestal in order to perform timing calibration", file=sys.stderr)
    exit(1)
    
# Force capacitor ordering
args.offset = True

# Save the number of samples we demand
Nsamples = args.N

# Set args.N = -1, so we keep listening indefinitely
args.N = -1

# Enable the sin
ifc.DrsTimeCalibOscOn()

# Sleep a bit
print("Sleeping for 100ms second to allow the calibration to get smooth...", file=sys.stderr)
time.sleep(0.1)

# Save previous ones
masklow = ifc.brd.peeknow(0x670)
maskhigh = ifc.brd.peeknow(0x674)

# Set new ones
ifc.brd.pokenow(0x670, 0x00008000)
ifc.brd.pokenow(0x674, 0x00800000)

# Load the gain correction?
gainCorrection = None
if args.gain:
    import pickle
    gainCorrection = pickle.load(open(args.gain, "rb"))
    print("Using gain file %s" % args.gain, file=sys.stderr)

# Get an event
ifc.brd.pokenow(0x320, 1 << 6, readback=False, silent=True)

# Wait for the event
evt = eventQueue.get()

# Get board id
board_id = evt.board_id.hex()

# Get board active channels
chans = evt.channels.keys()

# This is the fork() point, so it needs to be inside the
# script called.
#
# This has to be done after setting things, so if we are hardware
# triggering, its okay.
if __name__ == "__main__":
    intakeProcesses = lappdTool.spawn(args, eventQueue, timingAccumulator)

############## COMMON TOOL INITIALIZATION END ##############

#
# This is called from another process, so it always runs
# in the child process.
#
# Need to take care that these local variables stay in the child
# (I think they will, but we'll see...)
# Make the nishimura romero-wolf variables
#
# Each process will have its own copy of these variables.
#
xij = {}
yij = {}
counts = {}

for chan in chans:
    # Initialize the pairs list
    xij[chan] = [0 for x in range(1024)]
    yij[chan] = [0 for y in range(1024)]

    # Initialize the count of tabulated samples
    counts[chan] = [0 for i in range(1024)]

def timingAccumulator(event, eventQueue, args):

    # If we're not None, then we should accumulate
    if event:
        # Process it right here.
        for chan in event.channels.keys():
            # First, apply the gain correction (since we don't usually care enough about this elsewhere)
            if args.gain:
                for i in range(1024):
                    if not evt.channels[chan][i] is None:
                        # We multiply by 1000 to put things into milivolts
                        #
                        # XXX we should do this at computation of the gain calibration....
                        evt.channels[chan][i] *= args.gain[chan][i][0] * 1000
                #print("Gains corrected for event number %d" % evt.evt_number, file=sys.stderr)

            # Go through the waveforms, stashing the squares already

            for i in range(1023):
                if not evt.channels[chan][i] is None and not evt.channels[chan][i+1] is None:
                    xij[chan][i] += (evt.channels[chan][i] + evt.channels[chan][i+1])**2
                    yij[chan][i] += (evt.channels[chan][i] - evt.channels[chan][i+1])**2
                    counts[chan][i] += 1

            # Don't forget the reach around
            if not evt.channels[chan][1023] is None and not evt.channels[chan][0] is None:
                xij[chan][1023] += (evt.channels[chan][1023] + evt.channels[chan][0])**2
                yij[chan][1023] += (evt.channels[chan][1023] - evt.channels[chan][0])**2
                counts[chan][1023] += 1
    else:
        # Now its time to ship our results via IPC
        eventQueue.put((xij, yij, counts))

#
# Now populate them
#
# For external triggers, each intake() when terminate when Nsamples/Nprocesses have been
# processed.
#
# For software triggers, intake() is instructed to terminate after the given number of
# soft triggers has been sent.
#
if not args.external:
    for k in range(0, Nsamples):

        # Wait for it to settle
        time.sleep(args.i)

        # Software trigger
        ifc.brd.pokenow(0x320, 1 << 6, readback=False, silent=True)

    # Tell children to clean up
    # This means to report back whatever you have...
    lappdTool.reap(intakeProcesses, args)
    
# Wait for the partial data to come in from all children
for proc in intakeProcesses:

    # Get the partial data
    pxij, pyij, pcounts = eventQueue.get()

    # Accumulate into the first responder
    if len(xij.keys()) == 0:
        xij = pxij
        yij = pyij
        counts = pcounts
    else:
        for chan in xij.keys():
            xij[chan] += pxij[chan]
            yij[chan] += pyij[chan]
            counts[chan] += pcounts[chan]

    # Signal that we got it
    eventQueue.task_done()

# Restore old channel masks
ifc.brd.pokenow(0x670, masklow)
ifc.brd.pokenow(0x674, maskhigh)

# Turn off calibration 
ifc.RegSetBit(lappdIfc.MODE, lappdIfc.C_MODE_TCA_ENA_BIT, 0)  

# Nw do the analysis
# from scipy.stats import describe
import math
    
for chan in xij.keys():
    # Okay, now compute the averages
    for i in range(1024):

        xij[chan][i] = float(xij[chan][i]/counts[chan][i])
        yij[chan][i] = float(yij[chan][i]/counts[chan][i])

        #
        # Assuming the integral average is a good approximation for this sample...
        # Then:
        #    atan(sqrt(<y^2>/<x^2>))/(\pi 1e8) = \Delta_{ij}
        #
        # Note: Our calibration oscillator is 100Mhz, so 1e8.
        #       We multiply by 1e9 to switch to nanoseconds
        #       So the final factor is 10 (on top)
        #
        xij[chan][i] = math.atan(math.sqrt(yij[chan][i]/xij[chan][i]))*10/math.pi

        print("%e %d" % (xij[chan][i], chan))
        print("Computed \Delta_{%d, %d+1} for calibration channel %d" % (i, i+1, chan), file=sys.stderr)

# Create a timing object

# For now, just set the interchip timing delays to zero
# XXX Read these in, if given...
deltat_chip = {}
for chan in xij.keys():
    deltat_chip[chan] = 0.0

# Set the reference channel to be DRS2's TCA line
reference = 15

# Make a channel mapping

chanmap = {}
for i in range(16):
    chanmap[i] = 15

for i in range(55-8, 56):
    chanmap[i] = 55

# Write out a binary timing file
import pickle
pickle.dump(lappdProtocol.timing(chanmap, xij, reference, deltat_chip), open("%s.timing" % board_id, "wb"))
