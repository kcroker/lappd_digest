#!/usr/bin/python3
import multiprocessing
import argparse
import math
import pickle
import sys

import lappdProtocol

# Make a new tool
parser = parser = argparse.ArgumentParser(description='Apply calibrations to offline binary events')

# Custom args

parser.add_argument('files', metavar="FILES", type=str, help="The files to calibrate", nargs='+')
parser.add_argument('-T', '--threads', metavar="NUM_THREADS", type=int, help="Number of children run when processing pickled events. Number of processors - 1 is a good choice.", default=1)
parser.add_argument('-s', '--subtract', metavar='PEDESTAL_FILE', type=str, help='Pedestal to subtract from pickled events.')
parser.add_argument('-t', '--timing', metavar='TIMING_FILE', type=str, help='Time calibration to apply to pickled events -calibrated (results in seconds)')
parser.add_argument('-g', '--gain', metavar='GAIN_FILE', type=str, help='Gain calibration to apply to pickled events.')
parser.add_argument('-d', '--dump', action='store_true', help='Dump the calibrated events to stdout. (works only with 1 thread!)')

parser.add_argument('--incom', action='store_true', help='Dump in Incom format')

# Get dem args
args = parser.parse_args()

# Sanity
if args.dump and args.threads > 1:
    print("ERROR: Can only have one thread reporting to stdout.", file=sys.stderr)
    exit(1)

if args.incom and (args.timing or args.gain):
    print("ERROR: Incom expects only pedestalled data")
    exit(2)

# Dump the binary header
if args.incom and args.dump:
    # 4 byte blocks:
    #   + 3 (file header)
    #   + chans * 1025 (timing stuff)
    #   + 2 (board headers)
    sys.stdout.buffer.write(b'\0' * (3 + 2 + 8*1025)*4)

# I'm sure theres a smart way to do this
assignments = [[] for x in range(args.threads)]

for n,file in enumerate(args.files):
    assignments[n % args.threads].append(file)

# Make an event queue
eventQueue = multiprocessing.JoinableQueue()

from subprocess import run
from os import getpid

# Entry point for children
def calibrate(assignments, eventQueue, args):

    # Load the relevant calibrations
    pedestalCal = None
    if args.subtract:
        pedestalCal = pickle.load(open(args.subtract, "rb"))

    timingCal = None
    if args.timing:
        timingCal = pickle.load(open(args.timing, "rb"))

    gainCal = None
    if args.gain:
        gainCal = pickle.load(open(args.gain, "rb"))
        
    for task in assignments:

        # Load the specific file
        f = open(task, "rb")
        print("Processing %s..." % task, file=sys.stderr)

        # Open the destination, we will write on the fly
        if not args.dump:
            dest = open("calibrated_%s" % task, "wb")

        q = 0
        while True:
            
            try:
                # Get an event                    
                e = pickle.load(f)
                
                # Get the channels present in this file's events
                chans = e.channels.keys()

                # Remove the pedestal
                if pedestalCal:
                    for chan in chans:
                        # Because subtract usually operates on the data stream as it coming in
                        # We need to do it manually here because there are usually None's present
                        # after the fact...
                        for i in range(len(e.channels[chan])):
                            if not e.channels[chan][i] is None:
                                e.channels[chan][i] -= pedestalCal.mean[chan][i]
                                
                # Now apply gains
                if gainCal:
                    for chan in chans:
                        for i in range(1024):
                            if e.channels[chan][i] is None:
                                continue

                            # XXX This is hardcoded and lacks sophistication
                            # The gain calibration should technically have ALL the gains independently
                            # measured.
                            #
                            # It is a hack for A.21 to just use the TCAL gains as representative
                            # Its also completely wrong, so don't ever use -g for A21!
                            e.channels[chan][i] *= gainCal[15 if chan < 16 else 55][i][0]


                # Finally, apply timing
                if timingCal:
                    timingCal.apply(e)


                # Did we want ascii?
                if args.dump:
                    if not args.incom:
                        lappdProtocol.dump(e)
                    else:
                        lappdProtocol.incom(e)
                        
                else:
                    # Write out the calibrated event
                    pickle.dump(e, dest)

                # now e gets garbage collected

                # Print out a message every 256 events
                if (q & 255) == 0:
                    print("Processed %d events" % q, file=sys.stderr)

                # Keep track
                q += 1
            except EOFError as e:

                # Leave the loop
                break
            
        # Close out the calibrated file
        if not args.dump:
            print("DONE: calibrated_%s written" % file, file=sys.stderr)
            dest.close()
        
# Fork a bunch of children that will handle sublists
if __name__ == '__main__':

    calibrateProcesses = [None]*args.threads

    for i in range(0, args.threads):
        calibrateProcesses[i] = multiprocessing.Process(target=calibrate, args=(assignments[i], eventQueue, args))
        calibrateProcesses[i].start()

        # Pin the processes
        run(['taskset -p -c %d %d' % (i, calibrateProcesses[i].pid)], stdout=sys.stderr, shell=True)

    # Now, pin ourselves to the remaining CPU!
    run(['taskset -p -c %d %d' % (args.threads, getpid())], stdout=sys.stderr, shell=True)

    # Wait for them to finish (in order)
    for i in range(0, args.threads):
        calibrateProcesses[i].join()
        

    
