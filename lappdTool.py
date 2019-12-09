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
    parser.add_argument('-i', metavar='INTERVAL', type=float, default=0.001, help='The interval (seconds) between software triggers')

    parser.add_argument('-T', '--threads', metavar="NUM_THREADS", type=int, help="Number of children to attach to distinct ports (to receive data in parallel on separate UDP buffers at the POSIX level.  Number of processors - 1 is a good choice.", default=1)

    parser.add_argument('-I', '--initialize', action="store_true", help="Initialize the board before taking data")
    parser.add_argument('-o', '--offset', action="store_true", help='Retain ROI channel offsets for incoming events.  (Order by capacitor, instead of ordering by time)')

    parser.add_argument('-s', '--subtract', metavar='PEDESTAL_FILE', type=str, help='Pedestal to subtract from incoming amplitude data')
    parser.add_argument('-a', '--aim', metavar='UDP_PORT', type=int, default=1338, help='Aim the given board at the given UDP port on this machine. Defaults to 1338')
    parser.add_argument('-e', '--external', action="store_true", help='Enable hardware triggering and do not send software triggers.')
    parser.add_argument('-f', '--file', metavar='FILE_PREFIX', help='Do not pass events via IPC.  Immediately dump binary to files named with this prefix.')
    parser.add_argument('-m', '--mask', metavar='MASK_STOP', help='Mask out this number of channels the time-ordered left of the final sample', type=int, default=0, choices=range(0,1024))
    parser.add_argument('-c', '--channels', metavar='CHANNELS', help="Comma separated string of channels. (Persistent)")

    parser.add_argument('-w', '--wait', metavar='WAIT', type=int, help="Adjust delay between receipt of soft/hard trigger and sampling stop. (Persistant)")
    parser.add_argument('-t', '--timing', metavar='TIMING_FILE', type=str, help='Output time-calibrated data (in seconds)')

    # At these values, unbuffered TCAL does not
    # have the periodic pulse artifact (@ CMOFS 0.8)
    #
    # Note that in A21, CMOFS is tied to OOFS, so you can't change that one without
    # undoing the effect on the other side of teh DRS4s
    #
    # DAC probably cares about OOFS being in a good spot... is it?
    # As per DRS4 spec, 1.55V gives symmetric
    # differential inputs of -0.5V to 0.5V.
    # Set the non-swept values
    # For both sides of the DRS rows

    parser.add_argument('--oofs', metavar='OOFS', type=float, default=1.3, help='OOFS DAC output voltage')
    parser.add_argument('--rofs', metavar='ROFS', type=float, default=1.05, help='ROFS DAC output voltage')
    parser.add_argument('--tcal', metavar='TCAL', type=float, default=0.84, help='Start values for TCAL_N1 and TCAL_N2 DAC output voltage')
    parser.add_argument('--cmofs', metavar='CMOFS', type=float, default=1.2, help='CMOFS DAC output Voltage')
    parser.add_argument('--bias', metavar='BIAS', type=float, default=0.7, help='BIAS DAC output Voltage')
    
    return parser

# DAC Channel mappings (in A21 crosshacked)
# (these should be moved to lappdIfc.py)
DAC_BIAS = 0
DAC_ROFS = 1
DAC_OOFS = 2
DAC_CMOFS = 3
DAC_TCAL_N1 = 4
DAC_TCAL_N2 = 5

def connect(parser):
    
    # Parse the arguments
    args = parser.parse_args()

    # Connect to the board
    ifc = lappdIfc.lappdInterface(args.board, udpsport = 8888)

    # Initialize the board, if requested
    if args.initialize:
        ifc.Initialize()

    # Set the requested threads on the hardware side 
    ifc.brd.pokenow(lappdIfc.NUDPPORTS, args.threads)

    # Give the socket address for use by spawn()
    ifc.brd.aimNBIC(port=args.aim)
    args.listen = ifc.brd.s.getsockname()[0]

    # Make an event queue
    eventQueue = multiprocessing.JoinableQueue()

    # Make a good (useful?) filename
    if args.file:
        import datetime
        args.file = "%s_%s" % (args.file, datetime.datetime.now().strftime("%d%m%Y-%H:%M:%S"))

    # Set DAC voltages
    ifc.DacSetVout(DAC_OOFS, args.oofs)
    ifc.DacSetVout(DAC_CMOFS, args.cmofs)
    ifc.DacSetVout(DAC_ROFS, args.rofs)
    ifc.DacSetVout(DAC_BIAS, args.bias)
    ifc.DacSetVout(DAC_TCAL_N1, args.tcal)
    ifc.DacSetVout(DAC_TCAL_N2, args.tcal)

    # Set the channels?
    if args.channels:
        chans = list(map(int, args.channels.split(',')))
        print("Specifying channels: ", chans, file=stderr)

        high = 0
        low = 0
        for chan in chans:
            if chan < 32:
                low |= (1 << chan)
            else:
                high |= (1 << (chan - 32))
            
        ifc.brd.pokenow(0x670, low)
        ifc.brd.pokenow(0x674, high)

    # Set the wait?
    if args.wait:
        ifc.brd.pokenow(lappdIfc.DRSWAITSTART, args.wait)
        print("Setting STOP delay to: %d" % args.wait, file=stderr)

    
    # Center the 
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
        intakeProcesses[i] = multiprocessing.Process(target=intake, args=((args.listen, args.aim+i), eventQueue, args))
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
