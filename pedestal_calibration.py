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
parser = lappdTool.create("Build a pedestal calibration from noise samples")

# Handle common configuration due to the common arguments
ifc, args, eventQueue = lappdTool.connect(parser)

# Sanity check
if args.subtract:
    print("ERROR: You cannot subtract out a pedestal while taking a pedestal", file=sys.stderr)
    exit(1)
        
print("Disabling offset subtraction during pedestal run...", file=sys.stderr)
args.offset = True

print("Masking out 100 samples to the left of the stop sample...", file=sys.stderr)
args.mask = 100
    
# Save the number of samples we demand
Nsamples = args.N

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
sums = {}
sumsquares = {}
rmss = {}
counts = {}

chans = None

#
# In this way, huge lists of event data never need to be shippped via IPC
# The callback must be defined above its use in the intake() as a hook, because Python.
#
def pedestalAccumulator(event, eventQueue, args):

    global chans
            
    # If we're not None, then we should accumulate
    if event:

        # If this is the first event, do some initialization on our end
        if chans is None:
            chans = event.channels.keys()
            
            for chan in chans:
                # Initialize the pairs list
                sums[chan] = [0 for x in range(1024)]
                sumsquares[chan] = [0 for x in range(1024)]
                rmss[chan] = [0.0 for x in range(1024)]

                # Initialize the count of tabulated samples
                counts[chan] = [0 for i in range(1024)]

        # Process it right here.
        for chan in event.channels.keys():
            for i in range(1024):

                # If its not none, accumulate it
                if not event.channels[chan][i] == lappdProtocol.NOT_DATA:
                    sums[chan][i] += event.channels[chan][i]
                    sumsquares[chan][i] += event.channels[chan][i]**2
                    counts[chan][i] += 1
    else:
        # Okay, now its processing time
        
        # Now its time to ship our results via IPC
        eventQueue.put((sums, sumsquares, counts))

# This is the fork() point, so it needs to be inside the
# script called.
#
# This has to be done after setting things, so if we are hardware
# triggering, its okay.
#
if __name__ == "__main__":
    intakeProcesses = lappdTool.spawn(args, eventQueue, pedestalAccumulator)

############## COMMON TOOL INITIALIZATION END ##############
        
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
    pmeans, psumsquares, pcounts = eventQueue.get()

    print("Received from child %d" % proc.pid, file=sys.stderr)
    
    # Accumulate into the first responder
    if len(xij.keys()) == 0:
        sums = pmeans
        sumsquares = psumsquares
        counts = pcounts
    else:
        for chan in means.keys():
            for i in range(1024):
                sums[chan][i] += psums[chan][i]
                sumsquares[chan][i] += psumsquares[chan][i]

    # Signal that we got it
    eventQueue.task_done()

# We've received all partial means, and all children are waiting for us to ship args.threads number of
# full averages

# Compute averages and the average squares
for chan in sums.keys():
    for i in range(1024):
        # Make sure its an integer (so we can do fast integer subtraction when pedestalling raw ADC counts)
        sums[chan][i] = round(sums[chan][i]/counts[chan][i])
        sumsquares[chan][i] = math.sqrt(sumsquares[chan][i]/counts[chan][i] - sums[chan][i]**2)
    
# Write out a binary timing file
import pickle
pickle.dump(lappdProtocol.pedestal(sums, sumsquares, counts), open("%s.pedestal" % board_id, "wb"))
