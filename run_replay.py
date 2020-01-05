#!/usr/bin/python3
#
# This will replay a (set) of binary data file(s) as if it were a run
#
import argparse
import multiprocessing
import sys
import lappdProtocol

parser = parser = argparse.ArgumentParser(description='Replay binary files as if they were coming from a board')
parser.add_argument('files', metavar="FILES", type=str, help="The files to calibrate", nargs='+')
parser.add_argument('-T', '--threads', metavar="NUM_THREADS", type=int, help="Number of children run when processing pickled events. Number of processors - 1 is a good choice.", default=1)
parser.add_argument('-a', '--aim', metavar="AIM_PORT", type=int, default=1338, help="(first) port at which to aim")
parser.add_argument('--address', metavar='IP_ADDRESS', type=str, default="127.0.0.1", help="Address at which to aim (defaults to localhost)")

# Get dem args
args = parser.parse_args()

# I'm sure theres a smart way to do this
assignments = [[] for x in range(args.threads)]

for n,file in enumerate(args.files):
    assignments[n % args.threads].append(file)

# Make an event queue
eventQueue = multiprocessing.JoinableQueue()

from subprocess import run
from os import getpid
import socket
import pickle

def replay(assignments, eventQueue, args, port):

    pid = getpid()
    
    # Open a socket at this port to localhost
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect((socket.gethostbyname(args.address), port))

    for task in assignments:

        # Load the specific file
        f = open(task, "rb")
        print("(PID %d): Processing %s..." % (pid, task), file=sys.stderr)
        
        # Start blasting events
        while True:    
            try:
                e = pickle.load(f)

                # Make parallel lists
                chan_list = []
                subhits_list = []

                # Build a list of channels and a single subhit at the stop sample
                # (XXX so the assumption is capacitor ordered data... this really needs to be
                #  encoded into the event structure itself)
                #
                # Ugh.  Places where there are None's in the data need to be chunked off into subhits
                
                for chan,ampls in e.channels.items():
                    print("Offset: %d" % e.offsets[chan])
                    print(ampls)
                    channel_subhits = []
                    subhit = []
                    offset = e.offsets[chan]
                    
                    for ampl in ampls:
                        if not (ampl & 1):
                            subhit.append(ampl)
                        else:
                            # We hit a none, terminate this subhit and adjust the offset
                            print("Hit NOT_DATA")
                            if len(subhit) > 0:
                                # Add this one
                                channel_subhits.append((offset, subhit))
                                
                                # Make a new empty one
                                subhit = []
                                
                            offset = (offset + len(subhit) + 1) % 1024

                    # Add the final subhit for this channel
                    channel_subhits.append( (offset, subhit) )

                    # And add this list to the subhits list
                    subhits_list.append(channel_subhits)
                    
                    # Add the 
                    chan_list.append(chan)

                rawpackets = lappdProtocol.event.generateEvent(e.evt_number,
                                                               e.resolution,
                                                               chan_list,
                                                               subhits_list,
                                                               1024)

                # Write it out
                for packet in rawpackets:
                    s.send(packet)
                
            except EOFError as e:
                            
                # Leave the while loop
                break


# Fork a bunch of children that will handle sublists
if __name__ == '__main__':

    processes = [None]*args.threads

    for i in range(0, args.threads):
        processes[i] = multiprocessing.Process(target=replay, args=(assignments[i], eventQueue, args, args.aim+i))
        processes[i].start()

        # Pin the processes
        run(['taskset -p -c %d %d' % (i, processes[i].pid)], stdout=sys.stderr, shell=True)

    # Now, pin ourselves to the remaining CPU!
    run(['taskset -p -c %d %d' % (args.threads, getpid())], stdout=sys.stderr, shell=True)

    # Wait for them to finish (in order)
    for i in range(0, args.threads):
        processes[i].join()
