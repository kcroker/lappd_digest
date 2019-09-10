#!/usr/bin/python3

# We use bitstruct since it automates working at the bit level
# This package defaults to MSB and MSb, which is what we like to use in FPGA
import bitstruct
import sys
import socket
import numpy as np
import math

# Define the format of a hit packet
#  HIT_MAGIC (16 bits)
#  CHANNEL_ID (8 bits)
#  DRS4_OFFSET (12 bits)
#  SEQ (4 bits)
#  HIT_PAYLOAD_SIZE (12 bits)
#  RESERVED (4 bits)
#  TRIGGER_TIMESTAMP_L (32 bits)
#  PAYLOAD (16*512 = 8192 bits = 1024 bytes)
#  HIT_FOOTER_MAGIC (16 bits)
hit_fmt = "u16 u8 u12 u4 u12 p4 u32 r8192 u16"
hitpacker = bitstruct.compile(hit_fmt, ["magic", "channel", "drs4_offset", "seq", "payload_size", "trigger_timestamp_l", "payload", "hit_footer_magic"])
globals()['HIT_MAGIC'] = 0x39ac
globals()['HIT_FOOTER_MAGIC'] = 0xd00b

# Define the format of an event header packet
#  EVT_HEADER_MAGIC_WORD (16 bits) - just pick something easily readable in the hex stream for now
#  BOARD_ID (48 bits) - Low 48 bits of the Xilinx Device DNA, also equal to the board MAC address apart from a broadcast bit.
#  EVT_TYPE (8 bits) - encode ADC bit width, compression level if any, etc.
#  EVT_NUMBER (16 bits) - global event identifier, assumed sequential
#  EVT_SIZE (16 bits) - event size in bytes
#  NUM_HITS (8 bits) - for easy alignment and reading
#  TRIGGER_TIMESTAMP_H (32-bits)
#  TRIGGER_TIMESTAMP_L (32-bits)
#  RESERVED (64-bits)
event_fmt = "u16 r48 u8 u16 u16 u8 u32 u32 p64"
eventpacker = bitstruct.compile(event_fmt, ["magic", "board_id", "evt_type", "evt_number", "evt_size", "num_hits", "trigger_timestamp_h", "trigger_timestamp_l"])
globals()['EVT_MAGIC'] = 0x39ab

if len(sys.argv) == 2:
    # Some simple debug: Make a sample event packet
    event_packet = {}
    event_packet['magic'] = EVT_MAGIC
    event_packet['board_id'] = b'\x00\x01\x02\x03\x04\x05'
    event_packet['evt_type'] = 0
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

# Start listening
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.bind(('127.0.0.1', 1338))

# Server loop
print("Entering service loop")
while True:

    # Grab the maximum IP packet size
    # (and wait until things come in)
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

    print(packet)
    
    with open("most_recent", "wb") as w:
        if packet['magic'] == HIT_MAGIC:
            w.write(hitpacker.pack(packet))
        else:
            w.write(eventpacker.pack(packet))
        
    
    

    
        
