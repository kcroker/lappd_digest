#!/usr/bin/python3

# We use bitstruct since it automates working at the bit level
# This package defaults to MSB and MSb, which is what we like to use in FPGA
import bitstruct
import sys
import socket
import random
import math

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
hit_fmt = "u16 u8 u12 u4 u16 u32"
hitpacker = bitstruct.compile(hit_fmt, ["magic", "channel_id", "drs4_offset", "seq", "hit_payload_size", "trigger_timestamp_l"])
globals()['HIT_MAGIC'] = 0x39a
globals()['HIT_FOOTER_MAGIC'] = 0xd00b
globals()['HIT_HEADER_SIZE'] = 11

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
event_fmt = "u16 r48 u3 p5 u16 u16 u8 u32 u32 p64"
eventpacker = bitstruct.compile(event_fmt, ["magic", "board_id", "adc_bit_width", "evt_number", "evt_size", "num_hits", "trigger_timestamp_h", "trigger_timestamp_l"])
globals()['EVT_MAGIC'] = 0x39ab


#
# Set a maximum payload size in bytes
#
########################################
globals()['LAPPD_MTU'] = 1400

# Define an event class
class event(object):

    #
    # This generates hits, for testing
    #
    def generateHit(event, chan, offset, amplitudes):

        if event.resolution < 3:
            mul = 1 << (3 - event.resolution)
        else:
            mul = 1 << (event.resolution - 3)
        
        # Make sure that amplitudes makes sense for encoding
        remainder = 0
        if event.resolution < 3:
            remainder = len(amplitudes) % mul

        # Pad with additional amplitudes, if necessary
        if remainder:
            # print("Padding generated hit with an additional %d amplitudes" % (mul - remainder))
            amplitudes.extend([0]*(mul - remainder))

        # Compute the (total_)hit_payload_size and required number of fragments
        # XXX?  (sanity check this)
        if event.resolution >= 3:
            hit_payload_size = len(amplitudes) << (event.resolution - 3)
        else:
            hit_payload_size = len(amplitudes) >> (3 - event.resolution)

        # Sanity check that this is an integer
        if not isinstance(hit_payload_size, int):
            raise ValueError("You computed padding wrong, hit_payload_size stopped being an integer")

        # Determine how many fragments we need and the length of the last fragment
        num_fragments = math.ceil(hit_payload_size / LAPPD_MTU)
        final_fragment_length = hit_payload_size - (num_fragments-1)*LAPPD_MTU
        
        # Sanity check
        if final_fragment_length > LAPPD_MTU:
            raise Exception("Something is insane in fragment payload size computations")
        
        # Make the total payload as a byte array
        total_payload = bytearray(hit_payload_size)
        
        # [We use hasattr() here because the code reads better than "if not event.unpacker or trying to catch some weird language exception"]
        if not hasattr(event, 'unpacker'):

            # How many bytes do we get for each amplitude?
            mul = 1 << (event.resolution - 3)

            # We are doing explosion (or just endian-flip)
            for i,ampl in enumerate(amplitudes):
                total_payload[i*mul:(i+1)*mul] = ampl.to_bytes(mul, byteorder='big')
        else:

            # We are doing compression
            j = 0
            mul = 1 << (3 - event.resolution)
            for i in range(0, len(amplitudes) >> (3 - event.resolution)):

                # This should contain a single byte when done
                # Notice the star, to turn the iterable into an argument list
                compressed = event.unpacker.pack(*amplitudes[i*mul:(i+1)*mul])
                total_payload[j] = compressed[0]
                j += 1
            
        # Okay, we now have a payload.
        # Build the hit, splitting the payload into fragments
        fragments = []
        fragment = {}

        # Set things that are common to all fragments
        fragment['magic'] = HIT_MAGIC
        fragment['resolution'] = event.resolution
        fragment['trigger_timestamp_l'] = event.raw_packet['trigger_timestamp_l']
        fragment['channel_id'] = chan
        fragment['drs4_offset'] = offset
        fragment['hit_payload_size'] = hit_payload_size

        #import pdb
        #pdb.set_trace()
        
        # Now populate individual fragments
        # Gotta reset i, because if we never enter the loop, then i never changes
        i = 0
        for i in range(0, num_fragments-1):

            # Note that we have to make an explicit copy
            # or else we just keep rewriting the same object
            tmp = fragment.copy()
            tmp['seq'] = i
            tmp['payload'] = total_payload[i*LAPPD_MTU:(i+1)*LAPPD_MTU]
            fragments.append(tmp)

        # And do the final fragment
        if num_fragments > 1:
            i += 1
            
        fragment['seq'] = i
        fragment['payload'] = total_payload[i*LAPPD_MTU:i*LAPPD_MTU + final_fragment_length]
        fragments.append(fragment)

        # Return the list of fragments
        return fragments

    #
    # This generates an event, for testing
    #
    def generateEvent(event_number, resolution, chan_list, offset_list, amplitudes_list):

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
            
        # Now generate the hits
        hitPackets = []

        for chan, offset, amplitudes in zip(chan_list, offset_list, amplitudes_list):

            # We use extend() because event.generateHit(...) possibly returns a list of
            # hit fragments
            hitPackets.extend(event.generateHit(testEvent, chan, offset, amplitudes))
            
            # See how much size this added to the event
            # any fragment will work, so use the last one
            event_packet['evt_size'] += hitPackets[-1]['hit_payload_size']

        # We will return *packed* packets in LIFO order.
        # Later, we can scramble the order elsewhere to make sure out of order arrivals are handled
        # correctly.

        # Make the bytes for the hit packets
        for packet in hitPackets:

            #import pdb
            #pdb.set_trace()

            # print("Encoding fragment %d, channel %d" % (packet['seq'], packet['channel_id']))
            
            # Slice the header into the front
            packet['payload'][:0] = hitpacker.pack(packet)

            # Put the footer on the end
            packet['payload'].extend(HIT_FOOTER_MAGIC.to_bytes(2, byteorder='big'))

        raw_packets = [x['payload'] for x in hitPackets]

        # Make the bytes for the event
        raw_packets.append(eventpacker.pack(event_packet))
        return raw_packets
            
    def __init__(self, packet, keep_offset=False):

        # Store a reference to the packet
        self.raw_packet = packet

        # What event number are we?
        # This will be used by higher levels to aggreate many responses from many boards.
        # Presumably, this number is synchronized via other external
        # means across all participating boards.
        self.eventNumber = packet['evt_number']

        # Keep track of our ... greatest hits ;)
        self.channels = {}

        # How many hits am I expecting?
        self.remaining_hits = packet['num_hits']

        # Has all of my data arrived?
        self.complete = False

        # Should I keep any offsets present in the data?
        self.keep_offset = keep_offset
        
        # Am I pedestalling?
        # self.is_pedestal = bool(packet['pedstal'])
        
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
            self.unpacker = bitstruct.compile(" ".join(["u%d" % (1 << self.resolution)] * (8 >> self.resolution)))
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

        print("Claiming a hit from %s with timestamp %d" % (packet['addr'], packet['trigger_timestamp_l']), file=sys.stderr)

        # Sanity check the length
        if len(packet['payload']) == 0:
            
            # Raise an exception with the bad packet attached
            e = Exception("Received an empty payload...")
            e.packet = packet
            raise e

        # Set up a working packet reference
        working_packet = None

        # Route this hit to the appropriate channel
        if packet['channel_id'] in self.channels:

            print("Hit fragment %d routed to existing channel %d" % (packet['seq'], packet['channel_id']), file=sys.stderr)
            
            # We've already got some fragments, so add this somewhere
            working_packet = self.channels[packet['channel_id']]

            # This fragment's payload length
            width = len(packet['payload'])

            # Copy it in
            # XXX This will fuck up if the firmware drops payload bytes
            # So remember we saw last packet, and raise an exception if we see a short packet again!
            if width < LAPPD_MTU:
                # We received the last one
                working_packet['payload'][packet['seq']*LAPPD_MTU:packet['seq']*LAPPD_MTU + width] = packet['payload']
            else:
                working_packet['payload'][packet['seq']*LAPPD_MTU:(packet['seq'] + 1)*LAPPD_MTU] = packet['payload']

                # Add to the recovered bytes
            working_packet['recovered_bytes'] += width
            
        else:
            print("Hit establishing data for channel %d, via fragment %d" % (packet['channel_id'], packet['seq']), file=sys.stderr)

            # This is the first fragment
            self.channels[packet['channel_id']] = packet
            working_packet = packet

            # Are we expecting more packets?
            # While defragmenting, we are working with possibly compressed payloads and lengths
            if len(packet['payload']) < packet['hit_payload_size']:

                # Yes.  So resize this packet's payload so we can accommodate
                # the entire thing.

                # Deep copy first
                tmp = bytearray(packet['payload'])

                # XXX Initialize with something that is not valid data
                #
                # Encode as NaNs
                #
                # XXX Current ADC's read out [-max/2,max/2] 
                
                width = len(tmp)
                
                # Overwrite
                packet['payload'] = bytearray(packet['hit_payload_size'])

                # Copy the incoming packet's data into the right place
                if width < LAPPD_MTU:
                    # Then its the last position
                    packet['payload'][packet['seq']*LAPPD_MTU:packet['seq']*LAPPD_MTU + width] = tmp
                else:
                    packet['payload'][packet['seq']*LAPPD_MTU:(packet['seq'] + 1)*LAPPD_MTU] = tmp
                    
                # Note how many bytes we've already reassembled
                packet['recovered_bytes'] = width
            else:
                packet['recovered_bytes'] = packet['hit_payload_size']
               

        # Did we complete a hit reconstruction with this packet?
        if working_packet['recovered_bytes'] == working_packet['hit_payload_size']:

            print("Hit reassembled!", file=sys.stderr)

            # Yes.  So now unpack the data
            print("Attempting to unpack %d bytes of payload" % len(working_packet['payload']), file=sys.stderr)
            self.unpackHit(working_packet)
            
            # Track that we finished one of the expected hits
            self.remaining_hits -= 1
            
        # Did we just complete our event?
        if not self.remaining_hits:

            print("Event completed!", file=sys.stderr)
            # Flag that we are ready to be put on the eventQueue
            self.complete = True

        # Always return true (used for orphans)
        return True
        
    #
    # Replaces the hit payload with an int array
    # of amplitudes, using this event's resolution to get the widths.
    #
    def unpackHit(self, packet):
        tmp = None

        # See if we are gluing bytes into integers
        # or unpacking bits into integers
        if self.chunks > 0:

            # Populate the list
            tmp = [int.from_bytes(packet['payload'][i*self.chunks:(i+1)*self.chunks], byteorder='big') for i in range(0, len(packet['payload']) >> (self.resolution - 3))]
        else:
            # OOO
            # We should technically do a computation here too and not use append...
            tmp = []

            # We are unpacking bits (or making single u8s)
            for i in range(0, len(packet['payload'])):
                # Notice that we do an [i:i+1] slide, instead of an index.
                # The index would return an integer, but the slice returns a bytes object with a single byte.
                amplitudes = self.unpacker.unpack(packet['payload'][i:i+1])
                for ampl in amplitudes:
                    tmp.append(ampl)
            
        # Now, make a new list that is offset
        # OOO
        # This can be done in the unpacking step, but premature
        # optimization is the root of all evil
        tmp2 = None
        if not self.keep_offset:# and not packet['drs4_offset'] == 0:
            # I feel like there should be a list primitive for this
            print("Subtracting offset from unpacked data...", file=sys.stderr)
            length = len(tmp)

            # XXX!! Why is this not (i + packet['drs4_offset']) % length
            tmp = [ tmp[ (i - packet['drs4_offset'] + length) % length ] for i in range(0, length)]

        # tmp now contains the unpacked amplitudes as integers
        # Replace the raw payload
        packet['payload'] = tmp
        
# Multiprocess fork() entry point
def intake(listen_tuple, eventQueue):

    # Start listening
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind((socket.gethostbyname(listen_tuple[0]), listen_tuple[1]))
    
    #
    # Flow:
    # 1) Event headers arrive from multiple boards
    # 2) Hit packets flow and need to be matched to specific boards
    # 3)

    # Keep track of events in progress and hits that don't belong to any events
    currentEvents = {}
    orphanedHits = []
    
    # Server loop
    print("Entering service loop", file=sys.stderr)
    
    while True:
        try:
            # Grab the maximum IP packet size
            # (and wait until things come in)
            # UDP semantics just pops whatever is there off of the packet stack
            print("Waiting for packets...", file=sys.stderr)
            data, addr = s.recvfrom(1 << 16)
            print("Packet received from %s:%d!" % addr, file=sys.stderr)

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
                    print("Received a hit", file=sys.stderr)

                    # Since we've got a hit, there are more bytes to deal with
                    packet['payload'] = data[HIT_HEADER_SIZE:-2]
                    
                    # Its a hit, lets get it routed
                    tag = (addr[0], packet['trigger_timestamp_l'])

                    # Do we have an event to associate this with?
                    if tag in currentEvents:

                        print("Event exists for %s at %d, claiming." % tag, file=sys.stderr)
                        
                        # We do.  Claim this hit
                        myevent = currentEvents[tag]

                        # Claim the hit.
                        myevent.claim(packet)

                        # Did we complete one?
                        if myevent.complete:

                            # OOO
                            # Push the payload completed event onto the queue
                            # Probably don't want or need to ship the object
                            # A dictionary of data sufficient for the aggregator level
                            # should be fine
                            print("Shipping completed packet...\n\n", file=sys.stderr)

                            # Strip unnecessary things from the event
                            # and channels.
                            
                            # Recover: ~1 + ~1 + ~1 + 30 + sizeof(compiled bitstruct)= > 33+ bytes
                            del(myevent.remaining_hits, myevent.complete, myevent.chunks, myevent.raw_packet)
                            if hasattr(myevent, 'unpacker'):
                                del(myevent.unpacker)

                            # Recover: 0.5 + 2 + 2 + 4 + 1 + 16 (at most) = 24.5 -> ~25 bytes/channel
                            for channel in myevent.channels:
                                del(channel['addr'], channel['seq'], channel['magic'], channel['hit_payload_size'], channel['trigger_timestamp_l'], channel['resolution'])

                                # If it was orphaned, we added an address to it
                                if 'addr' in channel:
                                    del(channel['addr'])

                            # Push it to the other process
                            eventQueue.put(myevent)

                            # Remove this from the list of current events
                            del(currentEvents[tag])
                            
                    else:
                        # We don't belong to anyone?
                        packet['addr'] = addr[0]
                        orphanedHits.append(packet)

                        # Notify.
                        print("Orphaned HIT fragment %d, channel %d, received from %s with timestamp %d" % (packet['seq'], packet['channel_id'], *tag), file=sys.stderr)
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
                        print("Received an event", file=sys.stderr)

                        # Make a tuple tag for this packet so we can sort it
                        tag = (addr[0], packet['trigger_timestamp_l'])

                        if not tag in currentEvents:

                            print("Registering new event from %s, timestamp %d" % tag, file=sys.stderr)
                            
                            # Make an event from this packet
                            currentEvents[tag] = event(packet)

                            # Lambda function which will claim a matching orphan and signal the match success
                            claimed = lambda orphan : currentEvents[tag].claim(orphan) if (orphan['addr'], orphan['trigger_timestamp_l']) == tag else False

                            print("Trying to claim orphans...", file=sys.stderr)
                            # Note arcane syntax for doing an in-place mutation
                            # (I assign to the slice, instead of to the name)
                            orphanedHits[:] = [orphan for orphan in orphanedHits if not claimed(orphan)]

                            # Now, this event might have been completed by a bunch of orhpans
                            if currentEvents[tag].complete:
                                print("Orphans completed an event, pushing...", file=sys.stderr)
                                eventQueue.put(currentEvents[tag])

                                # Remove it from the list
                                del(currentEvents[tag])
                                    
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
            print("\nCaught Ctrl+C, finishing up..", file=sys.stderr)
            break

        except SystemExit:
            print("\nCaught some sort of instruction to die with honor, committing 切腹...", file=sys.stderr)
            break

        
