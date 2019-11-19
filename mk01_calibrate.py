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
    args.offset = True

# Are we using an external trigger?  If so, kill the delay
if args.external:
    args.i = 0
    
# Make a good (useful?) filename
if args.file:
    import datetime
    args.file = "%s_%s" % (args.file, datetime.datetime.now().strftime("%d%m%Y-%H:%M:%S"))

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

# Make it pretty
print("#")

#
# XXX Blocked queries broken in Mark I *hardware* 
# (rapid register accesses for external devices not safe)
#
# # Queue these registers
# ifc.brd.peek(regs)

# # Queue any additionally requested registers
# if args.registers:
#     ifc.brd.peek(args.registers)

# # Query all registers at once
# responses = ifc.brd.transact()

# # Write them out
# print("# System register values before run: ")
# for reg,val in responses[0].payload.items():
#     print("# %s: %s" % (hex(reg), hex(val)))  

# if args.registers:
#     print("# Additional register values before run: ")
#     for reg,val in responses[1].payload.items():
#         print("# %s: %s" % (hex(reg), hex(val)))  

# The __name__ check is mandatory
if __name__ == '__main__':
    intakeProcesses = lappdTool.spawn(args, eventQueue)


# # Are we just listening?
# if args.listen == '0.0.0.0':
#     while args.N > 0:
#         try:
#             # Grab an event
#             event = eventQueue.get()

#             # Output it
#             print("Event %d:\n\tReconstruction time: %e seconds\n\tQueue delay: %e seconds" % (event.evt_number, event.finish - event.start, time.time() - event.prequeue), file=sys.stderr)

#             #if not args.quiet:
#             lappd.dump(event)
                
#             args.N -= 1

#             # Explicitly free the memory
#             eventQueue.task_done()
#             del(event)
            
#         except Exception as e:
#             import traceback
#             traceback.print_exc(file=sys.stderr)

# # So we are not just listening, lets do something

events = []
import time

for i in range(0, args.N):
    # --- Note that these are magic numbers...
    if not args.external:
        # Suppress board readback and response!
        ifc.brd.pokenow(0x320, (1 << 6), readback=False, silent=True)
    
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

            if not args.quiet:
                # Output the ascii dump
                lappdProtocol.dump(event)

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
lappdTool.reap(intakeProcesses)
