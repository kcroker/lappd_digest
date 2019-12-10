#!/usr/bin/python3

import sys
import os

# Do not ask me why this needs to be included now...
sys.path.append("./eevee")
os.environ['EEVEE_SRC_PATH'] = "./eevee"

import lappdProtocol
import lappdIfc
import lappdTool

import pickle
import queue
import socket
import time
    
# Make a new tool
parser = lappdTool.create('Get calibration data from Eevee boards speaking protocol MK01.')

# Custom args
parser.add_argument('-p', '--pedestal', action="store_true", help='Take pedestals. (Automatically turns on -o)')
parser.add_argument('-q', '--quiet', action="store_true", help='Do not dump anything to stdout.')
parser.add_argument('-r', '--register', dest='registers', metavar='REGISTER', type=str, nargs=1, action='append', help='Peek and document the given register before intaking any events')
parser.add_argument('-g', '--gain', metavar='GAIN_FILE', type=str, help='Output amplitude-calibrated data (in volts)')

# Connect it up
ifc, args, eventQueue = lappdTool.connect(parser)

# Simple sanity check
if not args.N > 0:
    raise Exception("Number of samples must be greater than 0")

if args.i < 0:
    raise Exception("Interval must be positive")

# If we are pedestalling, disable offset subtraction
# so that we have absolute capacitor locations
if args.pedestal:

    # These conflict!
    if args.subtract:
        print("ERROR: You cannot subtract out a pedestal while taking a pedestal", file=sys.stderr)
        exit(1)
        
    print("Disabling offset subtraction during pedestal run...", file=sys.stderr)
    args.offset = True

    print("Masking out 100 samples to the left of the stop sample...", file=sys.stderr)
    args.mask = 100
    
# Are we using an external trigger?  If so, kill the delay
if args.external:
    args.i = 0

# If we gave a timing file, retain capacitor offsets in the packet-catcher
# (we calibrte them right before shipping completed events)
if args.timing:
    args.offset = True

# If binary files have been requested, if there are no calibrations
# force capacitor ordering
if args.file:
    if not args.subtract and not args.timing and not args.gain:
        print("Forcing capacitor ordering on binary output...", file=sys.stderr)
        args.offset = True
        
# Record a bunch of registers first
# (Abhorrent magic numbers...)

# Take the voltages we care about.
#
# From Vasily's snippet
#           dacCode = int(0xffff/2.5*VOut)
# So inverting it:
#   VOut = 0xfff/(2.5*dacCode)
#
human_readable = {
    0 : 'bias',
    1 : 'rofs',
    2 : 'oofs',
    3 : 'cmofs',
    4 : 'tcal_n1',
    5 : 'tcal_n2'
}

print("# Standard and custom registers at run start:")
for i in range(0,6):
    reg = 0x1020 + i*4

    # DAC levels are shadowed.
    # So I have to read twice.
    ifc.brd.peeknow(reg)
    val = ifc.brd.peeknow(reg)
    print("#\t%s (%s) = %.02fV" % (human_readable[i], hex(reg), (2.5*val/0xffff)))
    
human_readable = {
    lappdIfc.DRSREFCLKRATIO : 'DRSREFCLKRATIO',
    lappdIfc.ADCBUFNUMWORDS : 'ADCBUFNUMWORDS',
    0x620 : '36 + 4*(selected oversample)'
}

for reg in [lappdIfc.DRSREFCLKRATIO, 0x620, lappdIfc.ADCBUFNUMWORDS]:
    val = ifc.brd.peeknow(reg)
    print("#\t%s (%s) = %d" % (human_readable[reg], hex(reg), val))

# Dump some run flags
print("# Capacitor ordered: %d" % 1 if args.offset else 0)
print("# Pedestal subtracted: %s" % args.subtract)
print("# Amplitude scaled: %s" % args.gain)
print("# Timing applied: %s" % args.timing)

# Make it pretty
print("#")

# The __name__ check is mandatory
if __name__ == '__main__':
    intakeProcesses = lappdTool.spawn(args, eventQueue)

# Turn on the external trigger, if it was requested and its off
triggerToggled = False
if args.external:
    triggerToggled = ifc.brd.peeknow(0x370)
    if not (triggerToggled & 1 << 5):
        ifc.brd.pokenow(0x370, triggerToggled | (1 << 5))
        
events = []
import time

for i in range(0, args.N):

    if not args.external:
        # Suppress board readback and response!
        ifc.brd.pokenow(0x320, (1 << 6), readback=False, silent=True)

        # Notify that a trigger was sent
        # print("Trigger %d sent..." % i, file=sys.stderr)
        
        # Sleep for the specified delay
        time.sleep(args.i)

    # Get from event queue if we're not directly dumping to files
    if not args.file:
        try:
            event = eventQueue.get()

            if (event.evt_number & 255) == 0:
                print("Received event %d" % (event.evt_number), file=sys.stderr)
                
            # Push it onto the processing queue
            events.append(event)

            # Signal that we consumed something
            eventQueue.task_done()
        
        except queue.Empty:
            print("Timed out (+100ms) on soft trigger %d." % i, file=sys.stderr)

# Wait on the intake processes to finish
print("Waiting for intakes() to finish...", file=sys.stderr)
[p.join() for p in intakeProcesses]
print("intakes() complete.", file=sys.stderr)

# Turn off the extenal trigger if we turned it on
if triggerToggled:
    ifc.brd.pokenow(0x370, triggerToggled & ~(1 << 5))

# We're finished, so clean up the listeners
# lappdTool.reap(intakeProcesses)

# Should we build a pedestal with these events?
if args.pedestal:

    # BEETLEJUICE BEETLEJUICE BEETLEJUICE
    activePedestal = lappdProtocol.pedestal(events)

    # Write it out
    if len(events) > 0:
        pickle.dump(activePedestal, open("%s.pedestal" % events[0].board_id.hex(), "wb"))

elif not args.quiet:
        
    for evt in events:
        # Output the result
        lappdProtocol.dump(evt)
