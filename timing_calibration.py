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
parser = lappdTool.create("Take TCA sin samples")

# Since we want high precision here, add the option to correct per-capacitor gains
parser.add_argument('-g', '--gain', metavar='GAIN_FILE',  help='Convert ADC counts into voltage using this gain profile')
parser.add_argument('-D', '--deltas', metavar='CHIP_DELTAS_FILE', help='Input externally measured interchip timing offsets')

# Handle common configuration due to the common arguments
ifc, args, eventQueue = lappdTool.connect(parser)

# Die if no pedestal is given
if not args.subtract:
    print("ERROR: You must provide a pedestal in order to perform timing calibration", file=sys.stderr)
    exit(1)
    
# Force capacitor ordering
args.offset = True

# Save the number of samples we demand
Nsamples = args.N

# Set args.N = 0, so we keep listening indefinitely
args.N = 0

# This is the fork() point, so it needs to be inside the
# script called.
if __name__ == "__main__":
    intakeProcesses = lappdTool.spawn(args, eventQueue)

############## COMMON TOOL INITIALIZATION END ##############

# Enable the sin
ifc.DrsTimeCalibOscOn()

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

# Make the nishimura romero-wolf variables
xij = {}
yij = {}

for chan in chans:
    # Initialize the pairs list
    xij[chan] = [0 for x in range(1024)]
    yij[chan] = [0 for y in range(1024)]

# Now populate them
for k in range(0, Nsamples):

    # Wait for it to settle
    time.sleep(args.i)

    # Software trigger
    ifc.brd.pokenow(0x320, 1 << 6, readback=False, silent=True)

    # Wait for the event
    evt = eventQueue.get()

    # Modestly print out status
    if k & 255 == 0:
        print("Received event %d" % k, file=sys.stderr)

    # Process it right here.
    for chan in chans:
        # First, apply the gain correction (since we don't usually care enough about this elsewhere)
        if gainCorrection:
            for i in range(1024):
                if not evt.channels[chan][i] is None:
                    evt.channels[chan][i] *= gainCorrection[chan][i][0]
            #print("Gains corrected for event number %d" % evt.evt_number, file=sys.stderr)
        
        # Go through the waveforms, stashing the squares already

        for i in range(1023):
            if not evt.channels[chan][i] is None and not evt.channels[chan][i+1] is None:
                #xij[chan][i].append( (evt.channels[chan][i] + evt.channels[chan][i+1])**2 )
                xij[chan][i] += (evt.channels[chan][i] + evt.channels[chan][i+1])**2
                #yij[chan][i].append( (evt.channels[chan][i] - evt.channels[chan][i+1])**2 )
                yij[chan][i] += (evt.channels[chan][i] - evt.channels[chan][i+1])**2
            
            # Don't forget the reach around
            if not evt.channels[chan][1023] is None and not evt.channels[chan][0] is None:
                #xij[chan][1023].append( (evt.channels[chan][1023] + evt.channels[chan][0])**2 )
                xij[chan][1023] += (evt.channels[chan][1023] + evt.channels[chan][0])**2
                #yij[chan][1023].append( (evt.channels[chan][1023] - evt.channels[chan][0])**2 )
                yij[chan][1023] += (evt.channels[chan][1023] - evt.channels[chan][0])**2

    
    # Add some info and stash it
    # evts.append(evt)

    # Signal that we got it.
    eventQueue.task_done()

# Restore old channel masks
ifc.brd.pokenow(0x670, masklow)
ifc.brd.pokenow(0x674, maskhigh)

# Turn off 
ifc.RegSetBit(lappdIfc.MODE, lappdIfc.C_MODE_TCA_ENA_BIT, 0)  

############# BEGIN COMMON TOOL FOOTER

# Reap listeners
lappdTool.reap(intakeProcesses, args)

############# END COMMON TOOL FOOTER 

# Now do the analysis
# from scipy.stats import describe
import math
    
for chan in chans:
    # Okay, now compute the averages
    for i in range(1024):

        # This function, computing 4 moments, is faster than just computing
        # the damn average manually...
        #
        # XXX changed this from these numpy.float644's to regular python float...
        xij[chan][i] = float(xij[chan][i]/Nsamples) #float(describe(xij[chan][i]).mean)
        yij[chan][i] = float(yij[chan][i]/Nsamples) #float(describe(yij[chan][i]).mean)

        #
        # Assuming the integral average is a good approximation for this sample...
        # Then:
        #    atan(sqrt(<y^2>/<x^2>))/(\pi 1e8) = \Delta_{ij}
        #
        # Note: Our calibration oscillator is 100Mhz, so 1e8
        #
        xij[chan][i] = math.atan(math.sqrt(yij[chan][i]/xij[chan][i]))/(math.pi * 1e8)

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
