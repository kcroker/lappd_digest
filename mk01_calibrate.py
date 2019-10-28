#!/usr/bin/python3

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
import argparse
import socket

#
# Utility function to dump a pedestal subtracted event
# Note that it MUTATES the events!!
#
def dump(event, activePedestal):
    # Subtract the pedestal if its defined
    if activePedestal:
        activePedestal.subtract(event)
        print("# pedestal = %s" % activePedestal.board_id)
            
    # # Dump the entire detection in ASCII
    for channel, amplitudes in event.channels.items():
        print("# event number = %d\n# channel = %d\n# samples = %d\n# y_max = %d" % (event.evt_number, channel, len(amplitudes), (1 << (1 << event.resolution)) - 1))
        for t, ampl in enumerate(amplitudes):
            print("%d %d" % (t, ampl))
        print("# END OF CHANNEL %d (EVENT %d)" % (channel, event.evt_number))
        
    # End this detection (because \n, this will have an additional newline)
    print("# END OF EVENT %d\n" % event.evt_number)
    

#
# STEP 0 - parse command line arguments
#
##################################
parser = argparse.ArgumentParser(description='Get calibration data from Eevee boards speaking protocol MK01.')

parser.add_argument('board', metavar='IP_ADDRESS', type=str, help='IP address of the target board')
parser.add_argument('N', metavar='NUM_SAMPLES', type=int, help='The number of samples to request')
parser.add_argument('i', metavar='INTERVAL', type=float, help='The interval (seconds) between software triggers')

parser.add_argument('-p', '--pedestal', action="store_true", help='Take pedestals')
parser.add_argument('-s', '--subtract', metavar='PEDESTAL_FILE', type=str, help='Pedestal to subtract from incoming amplitude data')
parser.add_argument('-a', '--aim', metavar='UDP_PORT', type=int, default=1338, help='Aim the given board at the given UDP port on this machine. Defaults to 1338')
parser.add_argument('-l', '--listen', action="store_true", help='Ignore board, interval, and samples.  Instead, passively listen for incoming data.')
parser.add_argument('-o', '--offset', action="store_true", help='Retain ROI channel offsets for incoming events')
args = parser.parse_args()

# Simple sanity check
if not args.N > 0:
    raise Exception("Number of samples must be greater than 0")

if args.i < 0:
    raise Exception("Interval must be positive")

# If we are pedestalling, force persistent offsets
if args.pedestal:
    args.offset = True
    
#
# STEP 1 - get control connections
#
#######################################

listen_here = None

if args.listen:
    listen_here = '0.0.0.0'
else:
    # Open up a control connection
    board = eevee.board(args.board)

    # Aim the board at ourself
    #  This sets the outgoing data path port on the board to port
    #  And sets the destination for data path packets to port
    board.aimNBIC()
    
    # Convenience shortcut
    listen_here = board.s.getsockname()[0]

#
# STEP 2 - fork an event reconstructor
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
intakeProcess = None
if __name__ == '__main__':
    intakeProcess = multiprocessing.Process(target=lappd.intake, args=((listen_here, args.aim), eventQueue, args.offset))
    intakeProcess.start()

# The reconstructor will push an Exception object on the queue when the socket is open
# and ready to receive data.  Use the existing queue, so we don't need to make a new lock
if not isinstance(eventQueue.get(), Exception):
    raise Exception("First event received did not indicate permission to proceed. Badly broken.")

print("Lock passed, intake process is now listening...", file=sys.stderr)

#
# STEP 4 - pedestal the board
#
######################################

activePedestal = None

# See if we should load an existing pedestal
if args.subtract:
    activePedestal = pickle.load(open(args.subtract, "rb"))

# Are we just listening?
while(args.listen):
    try:
        # Grab an event
        event = eventQueue.get()

        # Output it
        print("Event %d received on the queue, dumping to stdout..." % event.evt_number, file=sys.stderr)
        dump(event, activePedestal)
    
    except Exception as e:
        import traceback
        traceback.print_exc(file=sys.stderr)

# So we are not just listening, lets do something

events = []
import time
    
for i in range(0, args.N):
    # --- Note that these are magic numbers...
    board.pokenow(0x320, (1 << 6))
    
    # Sleep for the specified delay
    time.sleep(args.i)

    # Add it to the event queue
    try:
        event = eventQueue.get(timeout=0.1)
        print("Received event %d, in response to trigger %d." % (event.evt_number, i), file=sys.stderr)
        # Push it onto the processing queue
        events.append(event)

        # Output the ascii dump
        dump(event, activePedestal)
    except queue.Empty:
        print("Timed out (+100ms) on soft trigger %d." % i, file=sys.stderr)

# Should we build a pedestal with these events?
if args.pedestal:

    # BEETLEJUICE BEETLEJUICE BEETLEJUICE
    activePedestal = pedestal.pedestal(events)

    # Write it out
    if len(events) > 0:
        pickle.dump(activePedestal, open("%s.pedestal" % events[0].board_id.hex(), "wb"))

# Send the death signal to the child and wait for it
print("Sending death signal to intake process...", file=sys.stderr)
from os import kill
from signal import SIGINT
kill(intakeProcess.pid, SIGINT)
intakeProcess.join()
