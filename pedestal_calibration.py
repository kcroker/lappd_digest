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

# Turn off external respose
lappdTool.externalOff()
    
# Save the number of samples we demand
Nsamples = args.N

# Set args.N = -1, so we keep listening indefinitely
args.N = -1

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
    intakeProcesses = lappdTool.spawn(args, eventQueue, pedestalAccumulator)

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
means = {}
variances = {}
counts = {}

for chan in chans:
    # Initialize the pairs list
    means[chan] = [0 for x in range(1024)]
    variances[chan] = [0.0 for x in range(1024)]
    
    # Initialize the count of tabulated samples
    counts[chan] = [0 for i in range(1024)]

#
# This will use IPC in two stages:
#   1) computes the sum of the values
#   2) ships it and waits for the total average to come in
#   3) uses this to compute the sum (x_i - x_\bar)**2
#   4) ships it
#
# In this way, huge lists of event data never need to be shippped via IPC
#
def pedestalAccumulator(event, eventQueue, args):

    # If we're not None, then we should accumulate
    if event:
        # Process it right here.
        for chan in event.channels.keys():
            for i in range(1024):

                # If its not none, accumulate it
                if event.channels[chan][i]:
                    means[chan][i] += event.channels[chan][i]
                    counts[chan] += 1
    else:
        # Okay, now its processing time
        
        # Now its time to ship our results via IPC
        eventQueue.put((mean, None, counts))

        # Wait for all the other children to submit sums
        # and the parent to consume them
        eventQueue.join()

        # Wait for the total averages
        avgs = eventQueue.get()

        # Now make sums of squares
        for chan in event.channels.keys():

            # Note that counts will be unchanged!
            for i in range(1024):

                # If its not none, use it
                if event.channels[chan][i]:

                    # This should be an integer, because the averages will be rounded to
                    # the nearest integer (since this is in the noise anyway)
                    variances[chan] += (avgs[chan][i] - event.channels[chan][i])**2

        # Now ship the variances
        # (parent already has the means and the counts)
        eventQueue.put((None, variances, None))
    
    
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
    pmeans, pvariances, pcounts = eventQueue.get()

    # Accumulate into the first responder
    if len(xij.keys()) == 0:
        means = pmeans
        if pvariances:
            raise Exception("ERROR: Received non-None variance before computing means.  IPC broken")

        counts = pcounts
    else:
        for chan in means.keys():
            for i in range(1024):
                means[chan][i] += pmeans[chan][i]
                counts[chan][i] += pcounts[chan][i]

    # Signal that we got it
    eventQueue.task_done()

# We've received all partial means, and all children are waiting for us to ship args.threads number of
# full averages

# Compute averages
for chan in means.keys():
    for i in range(1024):
        # Make sure its an integer
        means[chan][i] = round(means[chan][i]/counts[chan][i])

# Ship them back
for proc in intakeProcesses:
    eventQueue.put(means)

# Wait for the children to finish
for proc in intakeProcesses:
    pmeans, pvariances, pcounts = eventQueue.get()

    if len(variances.keys()) == 0:
        variances = pvariances
        
        if pmeans or pcounts:
            raise Exception("ERROR: Received non-None means and counts before computing variances.  IPC broken")
    else:
        for chan in variances.keys():
            for i in range(1024):
                variances[chan][i] += pvariances[chan][i]

    # Signal that we got it
    eventQueue.task_done()

# Now compute the final variances
for chan in means.keys():
    for i in range(1024):
        # Make sure its an integer
        variances[chan][i] = round(variances[chan][i]/counts[chan][i])

# Write out a binary timing file
import pickle
pickle.dump(lappdProtocol.pedestal(means, variances, counts), open("%s.pedestal" % board_id, "wb"))
