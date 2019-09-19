#!/usr/bin/python3

# We use bitstruct since it automates working at the bit level
# This package defaults to MSB and MSb, which is what we like to use in FPGA
import bitstruct
import sys
import socket
import numpy as np
import math

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

if len(sys.argv) == 2:
    # Some simple debug: Make a sample event packet
    event_packet = {}
    event_packet['magic'] = EVT_MAGIC
    event_packet['board_id'] = b'\x00\x01\x02\x03\x04\x05'
    event_packet['adc_bit_width'] = 4
    event_packet['evt_number'] = 5
    event_packet['evt_size'] = 2
    event_packet['num_hits'] = 3
    event_packet['trigger_timestamp_h'] = 0xfedcba98
    event_packet['trigger_timestamp_l'] = 0x76543210

    print(event_packet)
    packed = eventpacker.pack(event_packet)
    with open("sample_event", 'wb') as w:
        w.write(packed)

    exit(0)

if len(sys.argv) == 3:
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
    domain = np.linspace(0, 2*math.pi, 512)
    for t in domain:
        hit_packet['payload'].extend(  (math.floor( (math.sin(t) + 1) * (1 << 15)).to_bytes(2, byteorder='big')))
    
    print(hit_packet)
    packed = hitpacker.pack(hit_packet)
    with open("sample_hit", 'wb') as w:
        w.write(packed)

    exit(0)

# Define the digester class
class digester(object):

    def __init__(self, ip, port=1338):

        # The list of assembled events
        self.events = []
        self.s = 
        
# Define an event class
class event(object):

    def __init__(self, packet):

        # Explicitly copy the packet into the header
        self.header = dict(packet)

        # Unset things that are 
        
        # What event number are we?
        # This aggreates many responses from many boards
        # Presumably, this number is synchronized via other external
        # means across all participating boards.
        self.eventNumber = packet['evt_number']
        
        self.hitQueue = []

        # Am I pedestalling?
        self.is_pedestal = bool(packet['pedstal'])
        
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
        if self.resolution < 4:
            # Then we only need to look at a byte at a time
            self.chunks = 1
            self.unpacker = bistruct.compile(" ".join(["u%d" % (1 << self.resolution)] * (8 >> self.resolution)))
        else:
            # Then we need to be gluing bytes together
            self.chunks = 1 << (self.resolution - 3)

        # These are the amplitudes for an event
        
    #
    # This is called when all the expected hits have arrived for an event
    # (or 
    #
    def finalizeEvent(self):
        pass

    #
    # Writes this SEQ payload into the right spot in the buffer
    #
    # If necessary, allocates a new payload that is large enough
    # to accommodate all the hit fragments first.
    #
    def registerHit(self, packet):

        # Have we already started reassembling this hit?
        hit = self.hits[packet['channel']]
        if hit:

            # Do some sanity checks
            expected_len = packet['payload_size'] / len(packet['payload'])
            if not isinstance(expected_len, int):
                raise Exception("Malrofmed fragmented hit packet.  Total payload length %d is not divisble by the payload length %d" % (packet['payload_size'], len(packet['payload'])))

            # Copy it in
            (hit['payload'])[packet['seq']*expected_len:(packet['seq'] + 1)*expected_len + 1] = packet.payload

            # Flag that we got the fragment
            hit['findmask'] &= 1 << packet['seq']

            # Are we done?
            if hit['findmask'] == :
                
            
        else:

            # Reallocate the payload

            # Add a hitmask
            # The biggest we could ever have is 
                
    #
    # Replaces the hit payload with an int array
    # of amplitudes, using this event's resolution to get the widths.
    # Assumes that this hit has already been correctly routed to this event
    #
    def unpackHit(self, packet):
        tmp = []
        
        # See if we are gluing bytes
        if self.chunks > 1:
            # Okay, we are gluing bytes
            for i in range(0, len(packet.payload) >> (self.resolution - 3)):
                # Each byte here is expected to be in MSB order....
                tmp.append(int.from_bytes(packet.payload[i:i + (chunks-1)], byteorder='big'))
        else:
            # We are unpacking bits
            for i in range(0, len(packet.payload)):
                amplitudes = self.unpacker.unpack(packet.payload[i])
                for ampl in amplitudes:
                    tmp.append(ampl)

        # tmp now contains the unpacked amplitudes in as python integers
        # Replace the raw payload
        packet.payload = tmp
        
        
        
# Define a channel object
#
# Each channel will have its own pedestal, so this
# is a reasonable place to put an abstraction
#
# A channel abstracts the notion of ASIC+subasic data path
class channel(object):

    # id = hit:channel
    # resolution.  its in the protocol, but I won't be using it right now.
    # since its not in the frozen protocol spec at the moment
    def __init__(self, id):

        # Some identification information so we can route
        self.id = packet['channel']
        
        # For pedestals
        # These are amplitudes (unpacked and assembled payloads) that get accumulated
        self.pedestal_amplitudes = []

        # This is the eventual mean, variance, skewness, and kurtosis
        self.pedestal = None

    def computePedestal(self):
        self.pedestal = scipy.stats.describe(self.pedestal_amplitudes)

def unpackHit(packet):
    pass

def processEvent(event):
    pass

# A debugging routine mainly
def addPedestal():
    pass

def subtractPedestal():
    pass

# Hit fragments
# Key off of channel and trigger timestamp
hitFragments = {}

# Creat an event for widowed hits
# like those that NRL produces
currentEvents = {}
widowedPackets = {}

# Create the invariant information about channels: pedestals and resolution
channels = {}
for i in range(0, 16):
    channel[i] = channel(i, 2 << 4)
    
# Start listening
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.bind(('127.0.0.1', 1338))

#
# Flow:
# 1) Event headers arrive from multiple boards
# 2) Hit packets flow and need to be matched to specific boards
# 3)

# Server loop
print("Entering service loop")
while True:

    # Grab the maximum IP packet size
    # (and wait until things come in)
    # UDP semantics just pops whatever is there off of the packet stack
    print("Waiting for packets...")
    data, addr = s.recvfrom(1 << 16)
    print("Packet received from %s:%d!" % addr)
    
    # Try to unpack it as a hit first
    packet = None
    try:
        packet = hitpacker.unpack(data)
        if not packet['magic'] == HIT_MAGIC:
            packet = None
        else:
            print("Received a hit", file=sys.stderr)
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
        except Exception as e:
            print(e)
            continue

    # Echo out the most recent packet for debug
    print(packet)

    if packet['magic'] == HIT_MAGIC:

        # If we are matcing hits to events, this is taking place on a single board
        # Then all the hits will share the same trigger_timestamp_l
        
        # If its a hit, all we've got to identify the source is the ip and port the thing came from
        # So first check the events, to see if this IP address is known.
        matched = currentEvents[tag]
        
        if not matched:
            # There is no event associated with this board at this moment in time
            # So, put the hit in the orphan bucket
            orphanedHits.append((tag, packet))
        else:
            # There is an event that can claim this
            currentEvents[tag].registerHit(packet)
            
            # Unpack the hit (based on the event's resolution)
            currentEvents[tag].unpackHit(packet)

            # If its a pedestal event, add these amplitudes
            if currentEvents[tag]
            
    else:
        # Its an event, does this event already exist?
        if not currentEvents[tag]:
            currentEvents[tag] = event(packet)
        else:
            # We've received a duplicate
            raise Exception("Duplicate event header packet with tag %s" % tag)
    
        
    
    

    
        
