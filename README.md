*WARNING:* for all of these, the stdout buffer will not flush unless you force it to. So I just Ctrl+C to kill the
process, which forces "output" to be fully written.

## Taking pedestals

```
./mk01_calibrate.py -p 10.0.6.212 1000 0.001 > ascii_pedestals
```

This will:

1. Build a pedestal file for the board at 10.0.6.212, from 1000 soft triggers, issued 0.001(+event reconstruction) delay
2. Dump all the raw ASCII amplitudes to `ascii_pedestals`
3. Offsets are not subtracted in the stdout dump, so you are looking at capacitor identities in the delay line (i.e. -o flag is automatically implied by -p)

## Getting pedestal subtracted noise

```
./mk01_calibrate.py -o -s 111111111111.pedestal 10.0.6.212 60 0.1 > subtracted_noise
```

This will:

1. Use the pedestal build for the board with MAC address 11:11:11:11:11:11
2. Issue 60 soft triggers 100ms apart
3. Write out ASCII plottable data of the events as the come in, pedstal subtracted
4. The -o flag keeps the data at its original positions, so that it is capacitor ordered (not time ordered)

## Listening to whatever comes in on port 5858

```
./mk01_calibrate.py -l -a 5858 ignored 1 0 > ascii_events
```

1. This listens to UDP port 5858 (on all interfaces) for MK01 events, and dumps them
in *time order*.  So the 0th sample will correspond to the first sample read in time.

Note that no control commands are issued to any boards.

# To get higher speeds
Cannot use recvmmsg() in Python, since this is a Linux specific socket API extension.
Ugh.  I can try to write this into Python, I'm surprised no one has done this yet....

tx and rx queues are not supported on all NIC hardware, so we can't depend on them either.

Lets see how multiprocess handling of the data flow works...
