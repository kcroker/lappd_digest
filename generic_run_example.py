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
import eevee
import lappd
import pedestal
import multiprocessing

#
# STEP 1 - get control connections
#
#######################################

# Define some things for the network topology
ourself = 'localhost'
port = 1338

# # Get all the boards on the subnet
# broadcast = '10.0.6.255'
# boards = eevee.discover(broadcast)

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
# The fork listens for, and then reassembles, fragmented data and
# then shifts this data according delay line offset.
#
# Data is in the form of dictionaries, that have event header fields
# augmented with a list of channels that link to hits
#
# If a hit was not received on that channel, the type is set to None
# Because we will implement a listener

# Required for multiprocess stuff
eventQueue = multiprocessing.Queue()

# Since we are in UNIX, this will operate via a fork()
if __name__ == '__main__':
    multiprocessing.Process(target=lappd.intake, args=((ourself, port), eventQueue)).start()    

#
# STEP 4 - pedestal the boards
#
######################################

# # Build pedestals by queueing 100 soft triggers
# N_pedestalSamples = 100

# for board in boards:
    
#     # (This control packet will be around 1k, so < 1 MTU)
#     for i in range(0, N_pedestalSamples):
#         board.poke(SOFT_TRIGGER, i)

#     # Note that doing it this way keeps you from blasting 100 control packets
#     # to each board.  So instead of 100 packets, we send 1.
#     board.transact()

# #
# # STEP 5 - set into data run-mode configuration
# #
# ######################################

# for board in boards:
    
#     # Queue disable of flag to read out all hits on all channels
#     # (for actual runs now)
#     board.poke(FULL_READOUT, 0)
    
#     # Execute the poke
#     board.transact()
    
#
# STEP 6 - process incoming data, outputting to stdout
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

        # Pedestal
        N = 200
        pedestalList = []
        while N:
            pedestalList.append(eventQueue.get())
            N -= 1
            print("%d remaining pedestal samples to collect..." % N, file=sys.stderr)

        # Make it 10k
        # pedestalList = pedestalList*100

        print("Profiling pedestal construction...", file=sys.stderr)
        import time
        start = time.time()
        
        # We have the pedestal now
        myPedestal = pedestal.pedestal(pedestalList)

        end = time.time()
        print("Pedestal built:  Total time %f" % (end - start), file=sys.stderr)

        # Subtract the pedestals
        for event in pedestalList:
            myPedestal.subtract(event)

        # Dump the entire detection in ASCII
        for channel, packet in pedestalList[0].channels.items():
            print("# event number = %d\n# channel = %d\n# offset = %d\n# samples = %d\n# y_max = %d" % (pedestalList[0].eventNumber, channel, packet['drs4_offset'], len(packet['payload']), (1 << (1 << pedestalList[0].resolution)) - 1))
            for t, ampl in enumerate(packet['payload']):
                print("%d %d" % (t, ampl))
            print("")
        
        # End this detection (because \n, this will have an additional newline)
        print("# END OF DETECTION")
    
    except Exception as e:
        import traceback
        traceback.print_exc(file=sys.stderr)
