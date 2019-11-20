#!/usr/bin/python3

import argparse
import multiprocessing
from os import kill
from signal import SIGINT
from sys import stderr

import lappdIfc
from lappdProtocol import intake

#
# Common parameters that are used by anything intaking packets
#
def create(leader):
    
    parser = argparse.ArgumentParser(description=leader)
    
    parser.add_argument('board', metavar='IP_ADDRESS', type=str, help='IP address of the target board')
    parser.add_argument('N', metavar='NUM_SAMPLES', type=int, help='The number of samples to request')
    parser.add_argument('-i', metavar='INTERVAL', type=float, default=0.01, help='The interval (seconds) between software triggers')

    parser.add_argument('-t', '--threads', metavar="NUM_THREADS", type=int, help="Number of children to attach to distinct ports (to receive data in parallel on separate UDP buffers at the POSIX level.  Number of processors - 1 is a good choice.", default=1)

    parser.add_argument('-I', '--initialize', action="store_true", help="Initialize the board before taking data")
    parser.add_argument('-o', '--offset', action="store_true", help='Retain ROI channel offsets for incoming events.  (Order by capacitor, instead of ordering by time)')

    parser.add_argument('-s', '--subtract', metavar='PEDESTAL_FILE', type=str, help='Pedestal to subtract from incoming amplitude data')
    parser.add_argument('-a', '--aim', metavar='UDP_PORT', type=int, default=1338, help='Aim the given board at the given UDP port on this machine. Defaults to 1338')
    parser.add_argument('-e', '--external', action="store_true", help='Do not send software triggers (i.e. expect an external trigger)')
    parser.add_argument('-f', '--file', metavar='FILE_PREFIX', help='Do not pass events via IPC.  Immediately dump binary to files named with this prefix.')
        
    return parser

def connect(parser):
    
    # Parse the arguments
    args = parser.parse_args()

    # Connect to the board
    ifc = lappdIfc.lappdInterface(args.board, udpsport = 8888)

    # Initialize the board, if requested
    if args.initialize:
        ifc.Initialize()

    # Set the requested threads on the hardware side 
    ifc.brd.pokenow(0x678, args.threads)

    # Give the socket address for use by spawn()
    ifc.brd.aimNBIC(port=args.aim)
    args.listen = ifc.brd.s.getsockname()[0]

    # Make an event queue
    eventQueue = multiprocessing.JoinableQueue()

    # Make a good (useful?) filename
    if args.file:
        import datetime
        args.file = "%s_%s" % (args.file, datetime.datetime.now().strftime("%d%m%Y-%H:%M:%S"))

    # Return a tuble with the interface and the arguments
    return (ifc, args, eventQueue)

#
# This will spawn a bunch of listener processes
# and return when they are ready
#
def spawn(args, eventQueue):

    from subprocess import run
    from os import getpid
    
    # Track the children
    intakeProcesses = [None]*args.threads

    for i in range(0, args.threads):
        intakeProcesses[i] = multiprocessing.Process(target=intake, args=((args.listen, args.aim+i), eventQueue, args.file, args.offset, args.subtract))
        intakeProcesses[i].start()

        # Pin the processes
        run(['taskset -p -c %d %d' % (i, intakeProcesses[i].pid)], stdout=stderr, shell=True)

    # Now, pin ourselves to the remaining CPU!
    run(['taskset -p -c %d %d' % (args.threads, getpid())], stdout=stderr, shell=True)

    # Wait for the intake processes to flag that they are ready
    for i in range(0, args.threads):
    
        # The reconstructor will push an Exception object on the queue when the socket is open
        # and ready to receive data.  Use the existing queue, so we don't need to make a new lock
        msg = eventQueue.get()

        if not isinstance(msg, Exception):
            raise Exception("Semaphore event did not indicate permission to proceed. Badly broken.")

        print("Acknowledged ready to intake on %d" % msg.port, file=stderr)
        eventQueue.task_done()

    print("Lock passed, all intake processes ready...", file=stderr)

    # Return the processes
    return intakeProcesses

# If doing hardware triggers, the event queue is probably
# loaded with events
# Send the death signal to the child and wait for it
def reap(intakeProcesses):
    print("Sending interrupt signal to intake process (get out of recvfrom())...", file=stderr)
    
    for proc in intakeProcesses:
        kill(proc.pid, SIGINT)
        proc.join()
