#!/usr/bin/python3

# We use bitstruct since it automates working at the bit level
# This package defaults to MSB and MSb, which is what we like to use in FPGA
import bitstruct
import sys
import socket

# Define the format of a hit packet
#  HIT_MAGIC (12 bits)
#  RESOLUTION (4 bits)
#  CHANNEL_ID (8 bits)
#  DRS4_OFFSET (12 bits)
#  SEQ (4 bits)
#  HIT_PAYLOAD_SIZE (12 bits, representing byte length of all seq packet payloads)
#  RESERVED (4 bits)
#  TRIGGER_TIMESTAMP_L (32 bits)
#  PAYLOAD (e.g. ites, so 2^4*512 = 8192 bits = 1024 bytes)
#  HIT_FOOTER_MAGIC (16 bits)
hit_fmt = "u12 u4 u8 u12 u4 u12 p4 u32 r8192 u16"
hitpacker = bitstruct.compile(hit_fmt, ["magic", "resolution", "channel", "drs4_offset", "seq", "payload_size", "trigger_timestamp_l", "payload", "hit_footer_magic"])
globals()['HIT_MAGIC'] = 0x39a
globals()['HIT_FOOTER_MAGIC'] = 0xd00b

# Define the format of an event header packet
#  EVT_HEADER_MAGIC_WORD (16 bits) - just pick something easily readable in the hex stream for now
#  BOARD_ID (48 bits) - Low 48 bits of the Xilinx Device DNA, also equal to the board MAC address apart from a broadcast bit.
#  EVT_TYPE (8 bits) - encode ADC bit width, compression level if any, etc.
#   ---> ADC_RESOLUTION (3 bits)
#   ---> PEDESTAL_FLAG (1 bit)
#   ---> SOFT_TRIGGER (1 bit)
#   ---> RESERVED (3 bits)
#  EVT_NUMBER (16 bits) - global event identifier, assumed sequential
#  EVT_SIZE (16 bits) - event size in bytes
#  NUM_HITS (8 bits) - for easy alignment and reading
#  TRIGGER_TIMESTAMP_H (32-bits)
#  TRIGGER_TIMESTAMP_L (32-bits)
#  RESERVED (64-bits)
event_fmt = "u16 r48 u3 u1 u1 p3 u16 u16 u8 u32 u32 p64"
eventpacker = bitstruct.compile(event_fmt, ["magic", "board_id", "adc_bit_width", "pedestal", "is_soft_triggered", "evt_number", "evt_size", "num_hits", "trigger_timestamp_h", "trigger_timestamp_l"])
globals()['EVT_MAGIC'] = 0x39ab

# if len(sys.argv) == 2:
#     # Some simple debug: Make a sample event packet
#     event_packet = {}
#     event_packet['magic'] = EVT_MAGIC
#     event_packet['board_id'] = b'\x00\x01\x02\x03\x04\x05'
#     event_packet['adc_bit_width'] = 4
#     event_packet['evt_number'] = 5
#     event_packet['evt_size'] = 2
#     event_packet['num_hits'] = 3
#     event_packet['trigger_timestamp_h'] = 0xfedcba98
#     event_packet['trigger_timestamp_l'] = 0x76543210

#     print(event_packet)
#     packed = eventpacker.pack(event_packet)
#     with open("sample_event", 'wb') as w:
#         w.write(packed)

#     exit(0)

# Only ever run this if its being called directly from the command line
if len(sys.argv) == 3 and __name__ == '__main__':
    # Some simple debug: Make a sample hit packet
    hit_packet = {}
    hit_packet['magic'] = HIT_MAGIC
    hit_packet['resolution'] = 4
    hit_packet['channel'] = 7
    hit_packet['drs4_offset'] = 512
    hit_packet['seq'] = 1
    hit_packet['payload_size'] = 2*512
    hit_packet['trigger_timestamp_l'] = 0x76543210
    hit_packet['hit_footer_magic'] = HIT_FOOTER_MAGIC
    hit_packet['payload'] = bytearray()

    # Make a sine wave
    import numpy as np
    import math
    
    domain = np.linspace(0, 2*math.pi, 512)
    ran = [round((math.sin(t) + 1) * (1 << 14)) for t in domain]
    for r in ran:
        # val is now an integer
        hit_packet['payload'].extend(r.to_bytes(2, byteorder='big'))
    
    print(hit_packet)
    packed = hitpacker.pack(hit_packet)
    with open("sample_hit", 'wb') as w:
        w.write(packed)

    exit(0)

# Define an event class
class event(object):

    def __init__(self, packet):

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

        # How big should each hit be, once defragmented?
        self.hitsize = packet['evt_size'] / self.hitcount

        # Sanity check that this was an integer division
        if not isinstance(self.hitsize, int):
            raise Exception("Received an event where the total size of the event did not divide evenly by the number of hits.")

        # Has all of my data arrived?
        self.complete = False
        
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
        if self.resolution < 4:
            # Then we only need to look at a byte at a time
            self.chunks = 1
            self.unpacker = bistruct.compile(" ".join(["u%d" % (1 << self.resolution)] * (8 >> self.resolution)))
        else:
            # Then we need to be gluing bytes together
            self.chunks = 1 << (self.resolution - 3)

    #
    # This hit has been routed to this event
    #
    def claim(self, packet):

        # Set up a working packet reference
        working_packet = None
        
        # Route this hit to the appropriate channel
        if packet['channel_id'] in self.channels:

            # We've already got some fragments, so add this somewhere
            working_packet = self.channels[packet['channel_id']]

            # Copy it in
            working_packet['payload'][packet['seq']*width:packet['seq'] * (width+1)] = packet['payload']

            # Add to the recovered bytes
            working_packet['recovered_bytes'] += len(packet['payload'])
            
        else:
            # This is the first fragment
            self.channels[packet['channel_id']] = packet
            working_packet = packet
            
            # Are we expecting more packets?
            if len(packet['payload']) < self.hitsize:

                # Yes.  So resize this packet's payload so we can accommodate
                # the entire thing.

                # Deep copy first
                tmp = bytearray(packet['payload'])
                width = len(tmp)
                
                # Overwrite
                packet['payload'] = bytearray(self.hitsize)

                # Copy the incoming packet's data into the right place
                packet['payload'][packet['seq']*width:packet['seq'] * (width+1)] = tmp

                # Note how many bytes we've already reassembled
                packet['recovered_bytes'] = width
            else:
                packet['recovered_bytes'] = self.hitsize

        # Did we complete a hit reconstruction with this packet?
        if working_packet['recovered_bytes'] == self.hitsize:

            # Yes.  So now unpack the data
            self.unpackHit(working_packet)

            # Track that we finished one of the expected hits
            self.remaining_hits -= 1
            
        # Did we just complete our event?
        if not self.remaining_hits:

            # Flag that we are ready to be put on the eventQueue
            self.complete = True

        # Always return true (used for orphans)
        return True
        
    #
    # Replaces the hit payload with an int array
    # of amplitudes, using this event's resolution to get the widths.
    #
    def unpackHit(self, packet):
        tmp = []

        # See if we are gluing bytes into integers
        # or unpacking bits into integers
        if chunks >= 1:
            for i in range(0, len(packet['payload']) >> (self.resolution - 3)):
                # Each byte here is expected to be in MSB order....
                tmp.append(int.from_bytes(packet['payload'][i*self.chunks:(i+1)*self.chunks], byteorder='big'))
        else:
            # We are unpacking bits (or making single u8s)
            for i in range(0, len(packet['payload'])):
                amplitudes = self.unpacker.unpack(packet['payload'][i])
                for ampl in amplitudes:
                    tmp.append(ampl)

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

    # Keep track of hits that don't belong to any events
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

            # Try to unpack it as a hit first
            packet = None
            try:
                packet = hitpacker.unpack(data)
                if not packet['magic'] == HIT_MAGIC:
                    packet = None
                else:
                    print("Received a hit", file=sys.stderr)

                    # Its a hit, lets get it routed
                    tag = (addr[0], packet['trigger_timestamp_l'])

                    # Do we have an event to associate this with?
                    if tag in currentEvents:

                        # We do.  Claim this hit
                        event = currentEvents[tag]

                        # Claim the hit.
                        event.claim(packet)

                        # Did we complete one?
                        if is event.complete:

                            # OOO
                            # Push the payload completed event onto the queue
                            # Probably don't want or need to ship the object
                            # A dictionary of data sufficient for the aggregator level
                            # should be fine
                            eventQueue.put(event)

                            # Remove this from the list of current events
                            del(currentEvents[tag])
                            
                    else:
                        # We don't belong to anyone?
                        packet['addr'] = addr[0]
                        orphanedHits.append(packet)

                        # Notify.
                        print("Orphaned HIT received from %s with timestamp %d" % tag, file=sys.stderr)
            except:
                pass

            # Try to parse it as an event
            if not packet:
                try:
                    packet = eventpacker.unpack(data)
                    if not packet['magic'] == EVT_MAGIC:
                        print("Received packet could not be parsed as either an event packet or a hit packet.  Dropping.", file=sys.stderr)
                        continue
                    else:
                        print("Received an event", file=sys.stderr)

                        # Make a tuple tag for this packet so we can sort it
                        tag = (addr[0], packet['trigger_timestamp_l'])

                        if not tag in currentEvents:
                            
                            # Make an event from this packet
                            currentEvents[tag] = event(packet)

                            # Lambda function which will claim a matching orphan and signal the match success
                            claimed = lambda orphan : currentEvents[tag].claim(orphan) if (orphan['addr'], orphan['trigger_timestamp_l']) == tag else False
                            
                            # Note arcane syntax for doing an in-place mutation
                            # (I assign to the slice, instead of to the name)
                            orphanedHits[:] = [orphan for orphan in orphanedHits if not claimed(orphan)]
                                    
                        else:
                            print("Received a duplicate event (well, sequence numbers might have been different but source and low timestamp collided)")
                            
                            
                except Exception as e:
                    print(e)
                    continue

            # Echo out the most recent packet for debug
            print(packet, file=sys.stderr)

        except KeyboardInterrupt:
            print("\nCaught Ctrl+C, finishing up..", file=sys.stderr)
            break

        except SystemExit:
            print("\nCaught some sort of instruction to die with honor, committing 切腹...", file=sys.stderr)
            break
