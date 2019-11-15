#!/usr/bin/python3

import sys
import os

# Do not ask me why this needs to be included now...
sys.path.append("./eevee")
os.environ['EEVEE_SRC_PATH'] = "./eevee"

import eevee
import lappd
import multiprocessing
import pickle
import queue
import argparse
import socket
import time
    
#
# STEP 0 - parse command line arguments
#
##################################
# Common arguments
parser = lappd.commonArguments('Get calibration data from Eevee boards speaking protocol MK01.')

# Custom args
parser.add_argument('-p', '--pedestal', action="store_true", help='Take pedestals. (Automatically turns on -o)')
parser.add_argument('-l', '--listen', action="store_true", help='Passively listen at IP_ADDRESS for incoming data.  Interval and samples are ignored.')
parser.add_argument('-r', '--register', dest='registers', metavar='REGISTER', type=str, nargs=1, action='append', help='Peek and document the given register before listening for events')

args = parser.parse_args()

# Simple sanity check
if not args.N > 0:
    raise Exception("Number of samples must be greater than 0")

if args.i < 0:
    raise Exception("Interval must be positive")

# If we are pedestalling, disable offset subtraction
# so that we have absolute capacitor locations
if args.pedestal:
    args.offset = True

# Are we using an external trigger?  If so, kill the delay
if args.external:
    args.i = 0
    
# Make a good (useful?) filename
if args.file:
    import datetime
    args.file = "%s_%s" % (args.file, datetime.datetime.now().strftime("%d%m%Y-%H:%M:%S"))

#
# STEP 1 - get control connections
#
#######################################

if args.listen:
    args.listen = '0.0.0.0'
else:
    # Open up a control connection
    # Don't try to query the board for its DNA yet
    board = eevee.board(args.board, anonymous=True)

    # Aim the board at ourself
    #  This sets the outgoing data path port on the board to port
    #  And sets the destination for data path packets to port
    # board.aimNBIC()
    
    # Convenience shortcut
    args.listen = board.s.getsockname()[0]

#
# STEP 2 - fork an event reconstructor
#
########################################

# Used for signaling and passing events, if not dumping them to files
eventQueue = multiprocessing.JoinableQueue()

#
# Spawn a bunch of reconstruction listener processes
# (see lappd.py for the arguments that its looking for)
#
# NOTE: if args.file = None (default), event objects will
# come in on the queue.  Otherwise, event numbers (receipts)
# will come in on the queue.
#
# The __name__ check is mandatory
if __name__ == '__main__':
    intakeProcesses = lappd.spawn(eventQueue, args)

#
# STEP 4 - pedestal the board
#
######################################

# Are we just listening?
if args.listen == '0.0.0.0':
    while args.N > 0:
        try:
            # Grab an event
            event = eventQueue.get()

            # Output it
            print("Event %d:\n\tReconstruction time: %e seconds\n\tQueue delay: %e seconds" % (event.evt_number, event.finish - event.start, time.time() - event.prequeue), file=sys.stderr)

            #if not args.quiet:
            lappd.dump(event)
                
            args.N -= 1

            # Explicitly free the memory
            eventQueue.task_done()
            del(event)
            
        except Exception as e:
            import traceback
            traceback.print_exc(file=sys.stderr)

# So we are not just listening, lets do something

events = []
import time

for i in range(0, args.N):
    # --- Note that these are magic numbers...
    if not args.external:
        # Suppress board readback and response!
        board.pokenow(0x320, (1 << 6), readback=False, silent=True) #, silent=True, readback=False)
    
        # Sleep for the specified delay
        time.sleep(args.i)

    # Get from event queue
    try:
        event = eventQueue.get()

        if isinstance(event, int):
            print("Event %d processed" % event, file=sys.stderr)
        else:
            print("Received event %d" % (event.evt_number), file=sys.stderr)
            # Push it onto the processing queue
            events.append(event)

            # Output the ascii dump
            lappd.dump(event)

        # Signal that we consumed something
        eventQueue.task_done()
        
    except queue.Empty:
        print("Timed out (+100ms) on soft trigger %d." % i, file=sys.stderr)

# Should we build a pedestal with these events?
if args.pedestal:

    # BEETLEJUICE BEETLEJUICE BEETLEJUICE
    activePedestal = event.pedestal(events)

    # Write it out
    if len(events) > 0:
        pickle.dump(activePedestal, open("%s.pedestal" % events[0].board_id.hex(), "wb"))

# We're finished, so clean up the listeners
lappd.reap(intakeProcesses)
