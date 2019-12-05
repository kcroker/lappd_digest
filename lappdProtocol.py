#!/usr/bin/python3

# We use bitstruct since it automates working at the bit level
# This package defaults to MSB and MSb, which is what we like to use in FPGA
import bitstruct
import sys
import socket
import random
import math
import pickle
import queue
import time
import collections

# Define the format of a hit packet
#  HIT_MAGIC (16 bits) (2 bytes)
#  CHANNEL_ID (8 bits) (1 byte)
#  DRS4_OFFSET (12 bits) (1.5 bytes)
#  SEQ (4 bits) (0.5 bytes) 
#  HIT_PAYLOAD_SIZE (16 bits, representing byte length of all seq packet payloads WITHIN THIS HIT) (1.5 bytes)
#  TRIGGER_TIMESTAMP_L (32 bits) (4 bytes)
# ------------------------------------ (bitstruct for the above fixed header, 11 bytes)
#  PAYLOAD (arbitrary, but less than an Ethernet MTU for sure)
#  HIT_FOOTER_MAGIC (16 bits)
hit_fmt = "u16 u8 u16 u8 u16 u32"
hitpacker = bitstruct.compile(hit_fmt, ["magic", "channel_id", "drs4_offset", "seq", "hit_payload_size", "trigger_timestamp_l"])
globals()['HIT_MAGIC'] = 0x39a
globals()['HIT_FOOTER_MAGIC'] = 1024
globals()['HIT_HEADER_SIZE'] = bitstruct.calcsize(hit_fmt)>>3

# Define the format of an event header packet
#  EVT_HEADER_MAGIC_WORD (16 bits) - just pick something easily readable in the hex stream for now
#  BOARD_ID (48 bits) - Low 48 bits of the Xilinx Device DNA, also equal to the board MAC address apart from a broadcast bit.
#  EVT_TYPE (8 bits) - encode ADC bit width, compression level if any, etc.
#   ---> ADC_BIT_WIDTH (3 bits)
#   ---> RESERVED (5 bits)
#  EVT_NUMBER (16 bits) - global event identifier, assumed sequential
#  EVT_SIZE (16 bits) - event size in bytes
#  NUM_HITS (8 bits) - for easy alignment and reading
#  TRIGGER_TIMESTAMP_H (32-bits)
#  TRIGGER_TIMESTAMP_L (32-bits)
#  RESERVED (64-bits)
event_fmt = "u16 r48 p8 u3 p5 u16 u16 u8 p8 u32 u32 p64"
eventpacker = bitstruct.compile(event_fmt, ["magic", "board_id", "adc_bit_width", "evt_number", "evt_size", "num_hits", "trigger_timestamp_h", "trigger_timestamp_l"])
globals()['EVT_MAGIC'] = 0x39ab

# Hack to do things fast(er)?
# yeah, way better
import struct
doit = struct.Struct(">512h")

#
# Set a maximum payload size in bytes
#
########################################

# Force fragmentation (for generation only)
globals()['LAPPD_MTU'] = 90

# Define an event class
class event(object):

    # An internal utility class used for reconstructing
    # hit fragments
    class hitstash(object):

        def __init__(self, packet):

            # How many bytes are we trying to receive?
            self.targetLength = -1

            # How many bytes have we already received?
            self.receivedBytes = 0

            # This will be (sample offsets, byte payloads) of individual fragments
            self.payloads = {}

            # The total number of samples possible 
            self.max_samples = 0
            
            # And stash the first one received
            self.stash(packet)
            
        def stash(self, packet):

            # Sanity check
            if self.targetLength < 0:
                # Initialize some things
                self.targetLength = packet['hit_payload_size']
                self.max_samples = packet['max_samples']
                #print("New subhit stash for channel %d" % packet['channel_id'], file=sys.stderr)
                
            else:
                # Verify it
                if not self.targetLength == packet['hit_payload_size']:
                    raise Exception("Inconsistent total hit payload length, not stashing packet!")

                if not self.max_samples == packet['max_samples']:
                    raise Exception("Inconsistent total samples count (e.g. bad footer), not stashing packet!")

            # Make sure there are no dups
            if packet['seq'] in self.payloads:
                raise Exception("Duplicate fragment received!")

            # We will eventually sort by the sequence number once we have all the packets
            self.payloads[packet['seq']] = (packet['drs4_offset'], packet['payload'])

            # Remember that we got it
            self.receivedBytes += len(packet['payload'])

            # Sanity check it
            if self.receivedBytes > self.targetLength:
                print(packet)
                raise Exception("Received %d of expected %d bytes!  Too many!" % (self.receivedBytes, self.targetLength))

            #            print("Stashed seq %d for channel %d with %d bytes.  %d remaining bytes" % (packet['seq'], packet['channel_id'], len(packet['payload']), self.targetLength - self.receivedBytes), file=sys.stderr)
                  
        def completed(self):
            return self.receivedBytes == self.targetLength

    #
    # Utility class to compute pedestals from a list of events
    #
    class pedestal(object):

        def __init__(self, samples):

            # Now compute the pedestals
            from statistics import variance
            from statistics import mean
            
            # Did we receive any samples?
            if not len(samples):
                raise Exception("Did not receive any samples!")
        
            # Some board information
            self.board_id = samples[0].board_id

            # Use the first event to determine the list of channels
            self.chan_list = samples[0].channels.keys()

            # Sanity checks on the pedestal samples
            for sample in samples:
            
                if not isinstance(sample, event):
                    raise Exception("Encountered non-event in list of samples.  Nonsense.")
            
                if not self.chan_list == sample.channels.keys():
                    raise Exception("Provided sample events for pedestaling have inhomogeneous channel content.  This .... is ... U N A C C E P T A B L E E E E ---- U N A C C E P T A B L E E E E E E E")
                if not sample.keep_offset:
                    raise Exception("Refusing to build pedestals with torn data (ROI mode)")
            
            # Set up for pedestals
            self.mean = {}
            self.variance = {}

            # Gotta do it manually
            for chan_id in self.chan_list:
                caps = [ [] for x in range(0, len(samples[0].channels[chan_id])) ]
                self.mean[chan_id] = []
                self.variance[chan_id] = []
                
                for evt in samples:
                    for capacitor, ampl in enumerate(evt.channels[chan_id]):
                        if not ampl is None:
                            caps[capacitor].append(ampl)

                # Now we have it in filtered capacitor form
                for cap in caps:
                    # Cap is a list
                    N = len(cap)
                    if N == 0:
                        self.mean[chan_id].append(None)
                        self.variance[chan_id].append(None)
                    elif N == 1:
                        self.mean[chan_id].append(cap)
                        self.variance[chan_id].append(None)
                    else:
                        avg = mean(cap)
                        self.mean[chan_id].append(avg)
                        self.variance[chan_id].append(variance(cap, xbar=avg))
                    
            # Remove the samples because python can't pickle it
            del(self.chan_list)

        #
        # Return a pedestal subtracted list of amplitudes
        #
        def subtract(self, amplitudes, chan_id):
            if not chan_id in self.mean:
                raise Exception("Given pedestal does not define channel %d" % chan_id)

            # OOO This looks slow as balls
            adjusted = []
            for i in range(0, len(self.mean[chan_id])):
                if not self.mean[chan_id][i] is None and not amplitudes[i] is None:
                    adjusted.append(amplitudes[i] - self.mean[chan_id][i])
                else:
                    adjusted.append(None)
                    
            return adjusted
            
        #
        # Generate a test pedestal, with normally distributed event samples
        #
        def generatePedestal(resolution, chan_list, numsamples, scale):

            import random

            # Compute the maximum value pedestal in any channel for this set of events.
            # Since this is for pedestals, we don't want the channel useless
            # (a pedestal near saturation is useless)
            #
            # We set pedestals' offsets to be, at most 1/8 of the channel's dynamic range
            maxy = 1 << ((1 << resolution) - 3) - 1

            # Generate some random offsets
            base_amplitudes = {}
            for chan_id in chan_list:
                base_amplitudes[chan_id] = [random.randrange(maxy) for i in range(0, numsamples)]

            ampl_list = []
            for chan_id, base in base_amplitudes.items():

                # Make some new fluxes
                flux = stats.norm.rvs(size=numsamples, scale=scale)

                # Apply them to the base amplitudes
                ampl_list.append([math.floor( base[i] + flux[i]*base[i] ) for i in range(0, numsamples)])

            # Make a (zero-offsets) event that has these features
            # Amplitude list for generateEvent() needs to be order preserving, or else the zip() will get the orders
            # screwed up

            #            print("Pedestal: %d channels, with %d samples each @ %d-bit" % (len(chan_list), numsamples, 1 << resolution), file=sys.stderr)
            return lappd.event.generateEvent(555, resolution, chan_list, [0]*len(chan_list), ampl_list)

        
    #
    # This generates hits, for testing
    #
    # subhits is a list of (offset, amplitudes) tuples
    #
    def generateHit(event, chan, subhits):

        if event.resolution < 3:
            mul = 1 << (3 - event.resolution)
        else:
            mul = 1 << (event.resolution - 3)

        # Go through each subhit and make fragments if necessary
        hit_payload_size = 0
        seqn = 0
        fragments = []
        
        for offset, amplitudes in subhits:
            
            # Make sure that amplitudes makes sense for encoding
            remainder = 0
            if event.resolution < 3:
                remainder = len(amplitudes) % mul

            # Pad with additional amplitudes, if necessary
            if remainder:
                print("Padding generated hit with an additional %d amplitudes.  Fix your amplitude list, dummy" % (mul - remainder))
                # Extend with the -1...
                amplitudes.extend([-1]*(mul - remainder))
                
            # Compute the (total_)hit_payload_size and required number of fragments
            # XXX?  (sanity check this)
            if event.resolution >= 3:
                subhit_payload_size = len(amplitudes) << (event.resolution - 3)
            else:
                subhit_payload_size = len(amplitudes) >> (3 - event.resolution)

            # Sanity check that this is an integer
            if not isinstance(subhit_payload_size, int):
                raise ValueError("You computed padding wrong, subhit_payload_size stopped being an integer")

            # Track it
            hit_payload_size += subhit_payload_size
            
            # Determine how many fragments we need and the length of the last fragment
            num_fragments = math.ceil(subhit_payload_size / LAPPD_MTU)
            final_fragment_length = subhit_payload_size - (num_fragments-1)*LAPPD_MTU
        
            # Sanity check
            if final_fragment_length > LAPPD_MTU:
                raise Exception("Something is insane in fragment payload size computations")
        
            # Make the total payload as a byte array
            subhit_total_payload = bytearray(subhit_payload_size)
        
            # [We use hasattr() here because the code reads better than "if not event.unpacker or trying to catch some weird language exception"]
            if not hasattr(event, 'unpacker'):

                # How many bytes do we get for each amplitude?
                mul = 1 << (event.resolution - 3)

                # We are doing explosion (or just endian-flip)
                for i,ampl in enumerate(amplitudes):
                    subhit_total_payload[i*mul:(i+1)*mul] = ampl.to_bytes(mul, byteorder='big', signed=True)
            else:
                # We are doing compression
                j = 0
                mul = 1 << (3 - event.resolution)
                for i in range(0, len(amplitudes) >> (3 - event.resolution)):

                    # This should contain a single byte when done
                    # Notice the star, to turn the iterable into an argument list
                    #
                    # XXX
                    # This will shit out on signed quantities
                    compressed = event.unpacker.pack(*amplitudes[i*mul:(i+1)*mul])
                    subhit_total_payload[j] = compressed[0]
                    j += 1
            
            # Okay, we now have a payload.
            # Build the hit, splitting the payload into fragments
            fragment = {}

            # Set things that are common to all fragments
            fragment['magic'] = HIT_MAGIC
            fragment['resolution'] = event.resolution
            fragment['trigger_timestamp_l'] = event.raw_packet['trigger_timestamp_l']
            fragment['channel_id'] = chan

            # Now populate individual fragments
            # Gotta reset i, because if we never enter the loop, then i never changes
            i = 0
            for i in range(0, num_fragments-1):

                # Note that we have to make an explicit copy
                # or else we just keep rewriting the same object
                tmp = fragment.copy()
                tmp['seq'] = seqn + i
                tmp['payload'] = subhit_total_payload[i*LAPPD_MTU:(i+1)*LAPPD_MTU]
                tmp['drs4_offset'] = offset

                # Add this subhit fragment
                fragments.append(tmp)
                #print("Appended fragment %d, offset %d" % ((seqn + i), offset), file=sys.stderr)
                
                # Update the offset, since we fragment as if we had back to back offsets
                if event.resolution - 3 >= 0:
                    offset += LAPPD_MTU >> (event.resolution - 3)
                else:
                    offset += LAPPD_MTU << (3 - event.resolution)

                # Sanitize in case we overran
                offset = offset % HIT_FOOTER_MAGIC

            # And do the final fragment
            if num_fragments > 1:
                i += 1

                # XXX This number is necessary for correct generation
                offset = offset % HIT_FOOTER_MAGIC

            fragment['seq'] = seqn + i
            fragment['drs4_offset'] = offset
            fragment['payload'] = subhit_total_payload[i*LAPPD_MTU:i*LAPPD_MTU + final_fragment_length]
            fragments.append(fragment)
            #print("Appended fragment %d, offset %d" % ((seqn + i), offset), file=sys.stderr)

#            import pdb
#            pdb.set_trace()

            # Increment the global sequence
            seqn += num_fragments


        # Now we are all done with subhits, so set the correct total payload length
        # inside every fragment
        for fragment in fragments:
            fragment['hit_payload_size'] = hit_payload_size
            
        # Return the list of fragments
        return fragments

    #
    # This generates an event, for testing
    #
    def generateEvent(event_number, resolution, chan_list, subhits_list, max_sample):

        # Make a dummy event
        event_packet = {}
        event_packet['magic'] = EVT_MAGIC
        event_packet['board_id'] = b'\x00\x01\x02\x03\x04\x05'
        event_packet['adc_bit_width'] = resolution
        event_packet['evt_number'] = event_number
        event_packet['evt_size'] = 0
        event_packet['num_hits'] = len(chan_list)
        event_packet['trigger_timestamp_h'] = 0xfedcba98
        event_packet['trigger_timestamp_l'] = random.getrandbits(32)

        # Generate the event object
        # (we do this since it makes the bit packer/unpacker for us)
        testEvent = event(event_packet)

        # Hack in the maximum sample
        testEvent.max_sample = max_sample
        
        # Now generate the hits
        hitPackets = []

        for chan, subhits in zip(chan_list, subhits_list):

            # We use extend() because event.generateHit(...) possibly returns a list of
            # hit fragments
            hitPackets.extend(event.generateHit(testEvent, chan, subhits))
            
            # See how much size this added to the event
            # any fragment will work, so use the last one
            event_packet['evt_size'] += hitPackets[-1]['hit_payload_size']

        # We will return *packed* packets in LIFO order.
        # Later, we can scramble the order elsewhere to make sure out of order arrivals are handled
        # correctly.

        # Make the bytes for the hit packets
        for packet in hitPackets:

            # print("Encoding fragment %d, channel %d" % (packet['seq'], packet['channel_id']))
            
            # Slice the header into the front
            packet['payload'][:0] = hitpacker.pack(packet)

            # Put the footer on the end
            packet['payload'].extend(HIT_FOOTER_MAGIC.to_bytes(2, byteorder='big'))

        raw_packets = [x['payload'] for x in hitPackets]

        # Make the bytes for the event
        raw_packets.append(eventpacker.pack(event_packet))
        return raw_packets
            
    def __init__(self, packet, keep_offset=False, activePedestal=None, activeGain=None, mask=0):

        # Store a reference to the packet
        self.raw_packet = packet

        # What event number are we?
        # This will be used by higher levels to aggreate many responses from many boards.
        # Presumably, this number is synchronized via other external
        # means across all participating boards.
        self.evt_number = packet['evt_number']

        # Store the board id, jesus
        self.board_id = packet['board_id']
        
        # Keep track of our ... greatest hits ;)
        self.channels = {}

        # How many hit channels am I expecting?
        self.remaining_hits = packet['num_hits']

        # How many totla bytes am I expecting?
        self.remaining_bytes = packet['evt_size']
        
        # Has all of my data arrived?
        self.complete = False

        # A list of offsets measured for each channel
        self.offsets = {}

        # Should I keep any offsets present in the data?
        self.keep_offset = keep_offset

        # How much to mask?
        self.mask = mask
        
        # Am I pedestalling?
        self.activePedestal = activePedestal

        # Am I converting to voltages?
        self.activeGain = activeGain
        
        # When was I made (profiling debugging)
        self.start = time.time()
        
        # Protocol encodes resolution at the event level
        # (Technically, its a channel property.)
        #
        # The resolution is actually 2^adc_bit_width
        #    0 -> on/off
        #    3 -> 8-bit data (1 byte/sample)
        #    4 -> 16-bit data (2 bytes/sample)
        #    5 -> 32-bit data (4 bytes/sample)
        #    6 -> 64-bit data (8 bytes/sample)
        #    > 7  ERROR
        #
        self.resolution = packet['adc_bit_width']

        # Set up the unpacker for this event (so we don't make it and tear
        # it down many times needlessly)
        #
        # OOO We should turn this into a factory, so this is only ever
        # compiled once...
        #
        if self.resolution < 3:
            # Then we only need to look at a byte at a time
            self.chunks = 0
            self.unpacker = bitstruct.compile(" ".join(["s%d" % (1 << self.resolution)] * (8 >> self.resolution)))
        else:
            # Then we need to be gluing bytes together (or copying)
            self.chunks = 1 << (self.resolution - 3)

    #
    # Determine a signature for this event, once it is complete.
    # The signature allows you to sensibly subtract pedestals.
    #
    # In principle, a device may provide any number of amplitudes on each channel (e.g. distinct ROIs per channel)
    # By design, an event always takes place at a fixed resolution for all channels.
    #
    # The signature gives a full channel list, the number of amplitudes 
    
    #
    # This hit has been routed to this event
    #
    def claim(self, packet):

        #print("Claiming a hit from %s with timestamp %d" % (packet['addr'], packet['trigger_timestamp_l']), file=sys.stderr)

        # Sanity check the length
        if len(packet['payload']) == 0:
            
            # Raise an exception with the bad packet attached
            e = Exception("Received an empty payload...")
            print(packet, file=sys.stderr)
            e.packet = packet
            raise e

        # Route this hit to the appropriate channel
        if packet['channel_id'] in self.channels:

            #print("Hit fragment %d routed to existing channel %d" % (packet['seq'], packet['channel_id']), file=sys.stderr)

            # Store this fragment in this channel's hit stash
            self.channels[packet['channel_id']].stash(packet)
            
        else:
            #print("Hit establishing data for channel %d, via fragment %d" % (packet['channel_id'], packet['seq']), file=sys.stderr)

            # This is the first fragment
            self.channels[packet['channel_id']] = event.hitstash(packet)
            
        # A quick alias
        current_hit = self.channels[packet['channel_id']]
        
        # Did we complete a hit reconstruction with this packet?
        if current_hit.completed():
            # Remove these bytes from the total expected over all channels
            self.remaining_bytes -= current_hit.receivedBytes
            
            #print("All expected hit bytes received on channel %d.  Unpacking..." % packet['channel_id'], file=sys.stderr)

            # Overwrite the reference to this hitstash object with the final amplitudes list
            # This should eventually garbage collect the hitstash object...
            self.channels[packet['channel_id']] = self.translate(current_hit, packet['channel_id'])

            # Track that we finished one of the expected hits
            self.remaining_hits -= 1

        # Did we just complete our event?
        if not self.remaining_hits or not self.remaining_bytes:

            #print("Event completed!", file=sys.stderr)
            # Flag that we are ready to be put on the eventQueue
            self.complete = True

        # Always return true (used for orphans)
        return True

    #
    # This converts a channel (as a hitstash object) into a Python integer list 
    # 
    def translate(self, current_hit, channel):
                    
        # Notice that we sort the dictionary by sequence numbers!
        subhits = [(offnpay[0], self.unpack(offnpay[1])) for seq, offnpay in sorted(current_hit.payloads.items(), key=lambda x:x[0])]

        # Since this is sorted, the offset of the lowest sequence number is (hopefully)
        # the true offset.  This will be wrong if the first packet is dropped...
        #
        # (With the sequence numbers being fully incremental, you'll be able to
        #  reconstruct capacitor positions, but not have any time reference.)
        #print("Setting the overall offset for channel %d to %d" % (packet['channel_id'], subhits[0][0]), file=sys.stderr)
        self.offsets[channel] = subhits[0][0]

        # Allocate space for the entire dero
        # Store None's 
        amplitudes = [None] * current_hit.max_samples
        
        # Assign by slicing directly into the amplitudes
        # OOO we can write torn offsets directly here
        for offset, ampls in subhits:
            
            # DDD
            # print(ampls, file=sys.stderr)
            
            #print("\tWriting at offset %d" % offset, ampls, file=sys.stderr)
            # Don't know how much optimiation python does with minimizing the number of
            # lookups on len, which is O(N)...
            len_ampls = len(ampls)
            end = offset + len_ampls

            # Slice it in, if we don't overrun
            if end < current_hit.max_samples:
                amplitudes[offset:end] = ampls
            else:
                # Slice in what we can at the end...
                # XXX off by 1?
                overrun = end - current_hit.max_samples
                fit = current_hit.max_samples - offset
                amplitudes[offset:current_hit.max_samples] = ampls[:fit]

                # ... and slice the rest in at the front
                amplitudes[:overrun] = ampls[fit:]

        # All subhits are now in place in a mutable list.
                
        # Are we pedestalling?  Do it now before we adjust the zero offset
        if self.activePedestal:
            #print("Subtracting pedestals from data before taring...", file=sys.stderr)
            amplitudes = self.activePedestal.subtract(amplitudes, channel)

        # Are we adjusting gains?  Do it now before masking and adjusting the zero offset.
        if self.activeGain and channel in self.activeGain:
            for i in range(1024):
                amplitudes[i] *= self.activeGain[channel][i][0]
                #            amplitudes = [x*self.activeGain[channel][cap][0] for cap,x in enumerate(amplitudes)]
            
        # Mask out the naughty ones to the left of stop.
        # This is because stop is t_max, and things get munged
        # during the stop process
        p = subhits[0][0]
        masklen = 5

        for i in range(0, masklen):

            # Right mask
            amplitudes[p + i] = None

            if p + (i + 1) == current_hit.max_samples:
                p = -(i + 1)

        p = subhits[0][0]
        for i in range(0, self.mask):

            # Left mask?
            amplitudes[p - i] = None
            
            if p - (i + 1) < 0:
                p = current_hit.max_samples + i
         
        # Are we trying to zero offset?
        if not self.keep_offset:

            # This is the first sampled capacitor position, in time
            tare = subhits[0][0]
            #print("Taring the final amplitude list by %d..." % tare, file=sys.stderr)
                
            # Never do a modulo in a loop computation, god
            # Since we are not memory limited in 2019, just do an offset copy
            tmp = [0]*(current_hit.max_samples)

            # Minimize computations
            delta = current_hit.max_samples - tare

            # Do the head of the final list...
            tmp[:delta] = amplitudes[tare:current_hit.max_samples]

            # ... and the tail
            tmp[delta:] = amplitudes[0:tare]

            # Replace amplitudes
            amplitudes = tmp

        return amplitudes

        
    #
    # Return an int array based on the provided payload.
    # Uses the current event's resolution and unpacking
    #
    def unpack(self, payload):
        tmp = None

        # See if we are gluing bytes into integers
        # or unpacking bits into integers
        if self.chunks > 0:

            tmp = doit.unpack(payload)
            # Populate the list
            # SLOW AS BALLS
            #tmp = [int.from_bytes(payload[i*self.chunks:(i+1)*self.chunks], byteorder='big', signed=True) for i in range(0, len(payload) >> (self.resolution - 3))]

        else:
            # OOO
            # We should technically do a computation here too and not use append...
            tmp = []

            # We are unpacking bits (or making single u8s)
            for i in range(0, len(payload)):
                # Notice that we do an [i:i+1] slide, instead of an index.
                # The index would return an integer, but the slice returns a bytes object with a single byte.
                amplitudes = self.unpacker.unpack(payload[i:i+1])
                for ampl in amplitudes:
                    tmp.append(ampl)
            
        # Return the unpacked payload
        return tmp

def export(anevent, eventQueue, dumpFile):

    # For profiling of event reconstruction and
    # queueing
    anevent.finish = time.time()
                                                    
    # Recover: ~1 + ~1 + ~1 + 30 + sizeof(compiled bitstruct)= > 33+ bytes
    del(anevent.remaining_hits, anevent.complete, anevent.chunks, anevent.raw_packet)
    if hasattr(anevent, 'unpacker'):
        del(anevent.unpacker)

    try:
        
        # Push it to another process?
        if dumpFile:
            pickle.dump(anevent, dumpFile)
            eventQueue.put(anevent.evt_number, block=False)
        else:
            # There's always a queue for controlling the processes
            anevent.prequeue = time.time()
            eventQueue.put(anevent, block=False)
            
    except queue.Full as e:
        print(e)
    
# Multiprocess fork() entry point
def intake(listen_tuple, eventQueue, args): #dumpFile=None, keep_offset=False, subtract=None):

    # If we pedestalling, load the pedestal
    activePedestal = None
    if args.subtract:
        activePedestal = pickle.load(open(args.subtract, "rb"))
        print("Using pedestal file %s" % args.subtract, file=sys.stderr)

    # Are we correcting gains?
    activeGain = None
    if args.gain:
        activeGain = pickle.load(open(args.gain, "rb"))
        print("Using gain file %s" % args.gain, file=sys.stderr)
        
    # Start listening
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind((socket.gethostbyname(listen_tuple[0]), listen_tuple[1]))
    
    # Keep track of events in progress and hits that don't belong to any events
    currentEvents = collections.OrderedDict()
    numCurrentEvents = 0

    # Only keep track of at most ~2e6 orphans (~1Gig) before we start dropping
    # deque doesn't like to be list comprehended
    orphanedHits = [] #collections.deque(maxlen=10000)

    # Open the dumpfile, if we were requested to make one
    if args.file:
        args.file = open("%s_%d" % (args.file, listen_tuple[1]), "wb")
        
    # Release the semaphore lock
    print("Releasing initialization lock for port %d..." % listen_tuple[1], file=sys.stderr)
    msg = Exception()
    msg.port = listen_tuple[1]
    eventQueue.put(msg)

    # Now wait for everyone to be ready
    eventQueue.join()

    # Server loop
    print("Entering service loop", file=sys.stderr)
    
    while True:

        try:
            # Grab the maximum IP packet size
            # (and wait until things come in)
            # UDP semantics just pops whatever is there off of the packet stack
            #print("Waiting for packets at %s:%d..." % listen_tuple, file=sys.stderr)
            data, addr = s.recvfrom(1500)
            #print("Packet received from %s:%d!" % addr, file=sys.stderr)

            #
            # Note that bitstruct is only useful for the header, 
            # because it cannot handle arbitrary length payloads.
            # (It is also useful for packing bits into bytes for payloads)
            #
            # So, for hits, we have to:
            #  1) analyze the header with bitstruct
            #  2) move the remaining bytes, minus footer, into a payload field added to the dict returned by bitstruct
            #
            # Try to unpack it as a hit first
            packet = None
            try:
                # Get the hit header into the packet
                packet = hitpacker.unpack(data)
                if not packet['magic'] == HIT_MAGIC:
                    packet = None
                else:
                    #print("Received a hit", file=sys.stderr)

                    ## DDD 
                    #print(packet, file=sys.stderr)
                    
                    # Since we've got a hit, there are more bytes to deal with
                    packet['payload'] = data[HIT_HEADER_SIZE:-2]

                    # Interpret the footer as the total number of samples possible within this data
                    packet['max_samples'] = int.from_bytes(data[-2:], byteorder='big')
                    
                    # Its a hit, lets get it routed
                    tag = (addr[0], packet['trigger_timestamp_l'])
                    packet['addr'] = addr[0]
                    
                    # Do we have an event to associate this with?
                    if tag in currentEvents:

                        #print("Event exists for %s at %d, claiming." % tag, file=sys.stderr)

                        # Don't make new references to the object
                        # deleting those won't (??) delete the originally referenced object...
                        
                        # Claim the hit.
                        currentEvents[tag].claim(packet)

                        # Did we complete one?
                        if currentEvents[tag].complete:
                            export(currentEvents[tag], eventQueue, args.file)
                            del(currentEvents[tag])
                            numCurrentEvents -= 1
                            
                    else:
                        # We don't belong to anyone?
                        packet['addr'] = addr[0]
                        orphanedHits.append(packet)

                        # Notify.
                        #print("Orphaned HIT fragment %d, channel %d, received from %s with timestamp %d" % (packet['seq'], packet['channel_id'], *tag), file=sys.stderr)
            except Exception as e:
                import traceback
                traceback.print_exc(file=sys.stderr)

            # Try to parse it as an event
            if not packet:
                try:
                    packet = eventpacker.unpack(data)
                    if not packet['magic'] == EVT_MAGIC:
                        print("Received packet could not be parsed as either an event packet or a hit packet.  Dropping.", file=sys.stderr)
                        print(packet, file=sys.stderr)
                        continue
                    else:
                        #print("Received an event", file=sys.stderr)
                        #print(packet, file=sys.stderr)
                        # Make a tuple tag for this packet so we can sort it
                        tag = (addr[0], packet['trigger_timestamp_l'])

                        if not tag in currentEvents:

                            # print("Registering new event %d from %s, timestamp %d" % (packet['evt_number'], *tag), file=sys.stderr)
                            
                            # Make an event from this packet
                            currentEvents[tag] = event(packet, args.offset, activePedestal, activeGain, args.mask)

                            # And remove old ones if we are overflowing
                            numCurrentEvents += 1
                            if numCurrentEvents > 100:
                                old = currentEvents.popitem(last=False)

                                # It would be better to dump this event, even if its incomplete...
                                
                                # This should delete all references to the hitstash inside the object
                                del(old)

                            # Lambda function which will claim a matching orphan and signal the match success
                            claimed = lambda orphan : currentEvents[tag].claim(orphan) if (orphan['addr'], orphan['trigger_timestamp_l']) == tag else False
                            #print("Trying to claim orphans...", file=sys.stderr)
                            # Note arcane syntax for doing an in-place mutation
                            # (I assign to the slice, instead of to the name)
                            #
                            orphanedHits[:] = [orphan for orphan in orphanedHits if not claimed(orphan)]
                                                        
                            # Now, this event might have been completed by a bunch of orhpans
                            if currentEvents[tag].complete:
                                #print("Orphans completed an event, pushing...", file=sys.stderr)
                                export(currentEvents[tag], eventQueue, args.file)

                                # Remove it from the list
                                del(currentEvents[tag])
                                numCurrentEvents -= 1
                                
                        else:
                            print("Received a duplicate event (well, sequence numbers might have been different but source and low timestamp collided)")
                            
                
                except bitstruct.Error as e:
                    print("Received packet could not be parsed as either an event packet or a hit packet.  Dropping.", file=sys.stderr)
                    continue
                except Exception as e:
                    # This is something more serious...
                    import traceback
                    traceback.print_exc(file=sys.stderr)
                    continue

            # Echo out the most recent packet for debug
            # print(packet, file=sys.stderr)

        except KeyboardInterrupt:
            print("\nCaught SIGINT.", file=sys.stderr)

            # If there was a dumpFile, close it
            if args.file:
                print("\nClosing dump..", file=sys.stderr)
                args.file.close()
            
            print("At death:\n\tOrphaned hits: %d\n\tIncomplete events: %d" % (len(orphanedHits), len(currentEvents)), file=sys.stderr)
            
            # Permit death without pushing further data onto the pipe
            eventQueue.cancel_join_thread()
            break
        except SystemExit:
            print("\nCaught some sort of instruction to die with honor, committing 切腹...", file=sys.stderr)
            break
        
#
# Utility function to dump a pedestal subtracted event
#
def dump(event):
    # # Dump the entire detection in ASCII
    print("# event number = %d\n# y_max = %d" % (event.evt_number, (1 << ((1 << event.resolution) - 1)) - 1))

    # A quick formatter
    fmt = lambda x : float('nan') if x is None else x
    
    for channel, amplitudes in event.channels.items():
        print("# BEGIN CHANNEL %d\n# drs4_offset: %d" % (channel, event.offsets[channel]))
        for t, ampl in enumerate(amplitudes):
            print("%d %e %d" % (t, fmt(ampl), channel))
        print("# END OF CHANNEL %d (EVENT %d)" % (channel, event.evt_number))
        
    # End this detection (because \n, this will have an additional newline)
    print("# END OF EVENT %d\n" % event.evt_number)
