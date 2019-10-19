#!/usr/bin/python3

###################################################################################
#
# This file is an experimental run.
# 
# It gives everything required to put a collection of boards back
# into a reproducible state and take data.
#
# I feel this is better than a GUI, because it is a written transcript of exactly
# what is done to get a certain set of data from a certain set of boards.
#
####################################################################################

import sys
import os

# Do not ask me why this needs to be included now...
sys.path.append("./eevee")
os.environ['EEVEE_SRC_PATH'] = "./eevee"

import eevee
import lappd
import pedestal
import multiprocessing
import pickle
import queue

#
# STEP 1 - get control connections
#
#######################################

# Define some things for the network topology
ourself = '10.0.6.254'
port = 1444

# # Get all the boards on the subnet
# broadcast = '10.0.6.255'
if len(sys.argv) < 2:
    print("Usage: %s <target board ip address> [pedestal file | NONE]" % sys.argv[0])
    print("(NOTE: not specifying a pedestal file or NONE will cause pedestals to be taken)")
    exit(1)

# Open up a control connection
board = eevee.board(sys.argv[1])

# Aim the board at ourself
#  This sets the outgoing data path port on the board to port
#  And sets the destination for data path packets to port
board.aimNBIC(ourself, port)

# #
# # STEP 2 - initialize the boards
# #
# ########################################

# # Set some default threshold values for all boards
# regs = {}
# for i in range(0,16):
#     regs[THRES_OFFSET | i] = 500

# # Initialize all boards with these values
# for board in boards:
    
#     # Queue setting the thresholds
#     board.poke(regs)

#     # Queue enable of flag to read out all hits on all channels
#     # (for pedestaling)
#     board.poke(FULL_READOUT, 1)

#     # Execute the poke
#     board.transact()

#
# STEP 3 - fork a raw event handler
#
########################################

# This forks (process) and returns a process safe queue.Queue.
# The fork listens for, and then reassembles, fragmented data
#
# Data is in the form of dictionaries, that have event header fields
# augmented with a list of channels that link to hits
#

# Required for multiprocess stuff
eventQueue = multiprocessing.Queue()

# Since we are in UNIX, this will operate via a fork()
if __name__ == '__main__':
     multiprocessing.Process(target=lappd.intake, args=((ourself, port), eventQueue)).start()    

#
# STEP 4 - pedestal the board
#
######################################

activePedestal = None

# See if we should load an existing pedestal
if len(sys.argv) > 2:
    # Assume the next entry is a pedestal file
    if not sys.argv[2] == "NONE":
        activePedestal = pickle.load(open(sys.argv[2], "rb"))
else:
    # Build pedestals by queueing 100 soft triggers
    N_pedestalSamples = 100

    #
    # This code sends 100 control packets.
    # It is wasteful, but it waits until the event is received at the queue
    # before sending out another one
    #
    
    # Set for actual A21
    pedestal_events = []
    
    for i in range(0, N_pedestalSamples):
        # --- Note that these are magic numbers...
        board.pokenow(0x320, (1 << 6))

        # Add it to the event queue
        try:
            pedestal_events.append(eventQueue.get(timeout=0.1))
        except queue.Empty:
            print("Timed out on pedestal event %d." % i, file=sys.stderr)

    # So now we have some N <= 100 pedestal events.
    # BEETLEJUICE BEETLEJUICE BEETLEJUICE
    activePedestal = pedestal.pedestal(pedestal_events)

    # Write it out
    pickle.dump(activePedestal, open("%s.pedestal" % pedestal_events[0].board_id.hex(), "wb"))
#
# STEP 5 - process incoming data, outputting to stdout
#
######################################

while(True):
    
    try:
        # A detection is a collection of events with the same sequence number.
        # This function returns once events from N boards have been received.
        # The timeout defines, once you start receiving events, how long to wait for
        # all of them to come in
        #
        # A detection is tagged with the system time, so be sure to have some
        # sort of ntpd running which is keeping your system in reasonable sync
        # with the rest of the world.
        #
        # Their order is sorted by event['board_id']
        # detection = lappd.eventAggregator(eventQueue, len(boards), timeout=1e-3)
        #
        # Coming soon, to a repository near you.....

        # Grab an event
        event = eventQueue.get()
        
        # Subtract the pedestal if its defined
        if activePedestal:
            activePedestal.subtract(event)
        
        # # Dump the entire detection in ASCII
        for channel, amplitudes in event.channels.items():
            print("# event number = %d\n# channel = %d\n# samples = %d\n# y_max = %d" % (event.eventNumber, channel, len(amplitudes), (1 << (1 << event.resolution)) - 1))
            for t, ampl in enumerate(amplitudes):
                print("%d %d" % (t, ampl))
            print("")
        
        # End this detection (because \n, this will have an additional newline)
        print("# END OF DETECTION")
    
    except Exception as e:
        import traceback
        traceback.print_exc(file=sys.stderr)
