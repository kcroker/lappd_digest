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

# #
# # STEP 4 - pedestal the boards
# #
# ######################################

# # Build pedestals by queueing 100 soft triggers
# N_pedestalSamples = 100

# for board in boards:
    
#     # (This control packet will be around 1k, so < 1 MTU)
#     for i in range(0, N_pedestalSamples):
#         board.poke(SOFT_TRIGGER, i)

#     # Note that doing it this way keeps you from blasting 100 control packets
#     # to each board.  So instead of 100 packets, we send 1.
#     board.transact()

#     # Fresh one for this board
#     pedestalEvents = []

#     # The eventQueue should be full or filling up with of event data for the this board
#     try:
#         while True:
#             # Wait at most 1 milisecond to get something
#             event = eventQueue.get(timeout=1e-3)

#             # Sanity check the event
#             if not event['addr'] == board.dest:
#                 print(file=sys.stderr, "Received an event from %s (%s), but expecting only events from %s.  Suspiciously dropping..." % (event['addr'], event['board_id'], board.dest))
#             else:
#                 pedestalEvents.append()
#     except queue.Empty as e:

#         # Did we get what we expected?
#         N = len(pedestalEvents)

#         # Inform the user
#         if N == N_pedestalSamples:
#             print(file=sys.stderr, "Pedestal acquisition successful")
#         else:
#             print(file=sys.srderr, "Pedestal acquisition INCOMPLETE")

#         # Give some specs
#         print(file=sys.stderr, "\tBoard: %s\n\tSamples requested: %d\n\tSamples received: %d" % (board, N_pedestalSamples, N))

#     # Associate an object to this board, that can this pedestal data taken with this board
#     board.pedestals = lappd.pedestal_system(pedestalEvents)

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

        detection = [eventQueue.get()]
    
        # We've received a detection, dump ascii
        print("# %s" % detection)
    
        # Apply the appropriate pedestal to each event
        for event in detection:

            # I think I want to adjust the returned boards from discover()
            # to be a hash on their DNAs
            # (Right now, this way to index won't work)
            #event['subtracted'] = board[event['board_id']].pedestals.subtract(event)
            pass
    
        # Get the length of any particular event
        #
        # --> XXX Will different boards have different ROIs?
        #
        samples = len(detection[0]['payload'])
    
        # Dump the entire detection in ASCII
    
        # Build a table for outputting, each board in a column
        data_table = {}
        for i in range(0, samples):
            data_table[i] = []

        # Populate the table
        for event in detection:
            for offset, amplitude in enumerate(event['payload']):
                data_table[offset].append(amplitude)

        # Output the table
        for offset, amplitudes in data_table.items():
            print("%d " % offset, end='')
            for amplitude in amplitudes:
                print("%d " % amplitude, end='')

                # End the line
                print("")

        # End this detection (because \n, this will have an additional newline)
        print("# END OF DETECTION\n")
    
    except Exception as e:
        print(e)
