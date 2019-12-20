# LAPPD Digest v0.1 (alpha)

These are a set of organically grown tools designed to enable rapid exercise of firmware capabilities developed for the A2x series of Ultralytics LAPPD mating boards.
Tools for acquisition and application of calibration of offline data are multiprocess.
Tools for calibration are in various states of being re-written for multiprocess functionality, and reduced memory consumption.

The design decision was speed of capability exploration, not speed of tool.
Therefore, we chose Python 3.5.
Next generation tools, based in C, should provide order of magnitude improvements (at least) in performance.
Further, we wanted an interface that was more easily accessible to junior researchers like undergraduates and graduates.

Incoming event data can be handled on-the-fly via IPC message queues, or rapidly via multiprocess parallel disk dumps of Python pickled objects.
Data can also be calibrated on the fly, or at a later time.
A rudimentary oscilliscope has been implemented, we have found it quite useful.
Feel free to extend it :D

The offline calibration tool has been augmented to output skeletal uncalibrated waveforms in the DRS4 eval software binary format.
In this way, the A2x series can be quickly used as a drop in replacement for existing DRS4 eval board configurations (regardless of whether an LAPPD tile is mated or not).

The core of the code has not yet been optimized, prefering clarity over speed.
Also, this was my first backend DAQ project, so please forgive my obvious poor design decisions (e.g. bit packed protocol format).

# Guerrila install

The following instructions should allow you to produce a functional environment.
The LAPPD series of boards uses the Evolvable Embedded Vehicle for Execution of Experiments (EEVEE) platform for network appliance capability and register control, so this project is a prerequisite.
Note that not all features have been merged into the master branch yet.

1. clone `lappd_digest`

```bash
$ git clone https://github.com/kcroker/lappd_digest
```

2. Change to this directory, clone `eevee`, and set up the environment

```bash
$ cd lappd_digest
$ git clone https://github.com/kcroker/eevee
$ export EEVEE_SRC_PATH=`realpath ./eevee`
```

Note that the final `export` command is not persistent.
The environment must provide this path for EEVEE to work, so consider adding it to your `.bashrc`, `.profile`, or startup files appropriate for your shell of choice.
Depending on your python3 install, you may need also need to

```bash
$ export PYTHONPATH=$PYTHONPATH:`realpath ./eevee`
```
Again, if necessary, this environemnt variable can be persistently extended within your shell configuration.

3. Install the bitstruct

The Mark I protocol uses bitpacked headers.
This was implemented with the Python 3 package `bitstruct`.
To install it locally for your user

```bash
$ pip3 install bitstruct
```

## Bringing up A2x + EEVEE
If your network segment has DHCP, the board will automatically join the network.
Boards respond to broadcast pings or can be discovered in Python.
Once a board is up via DHCP, it is accessible in every way that any other IP device is accessible on that segment.
Bear this in mind for network security purposes.
In particular, boards can have their data path pointed off of the physical network, making them a potent DoS tool if abused.

If your network segment does not have DHCP, you can bring boards up one at a time by pinging at the desired IP address on the segment.
The board will watch and make sure no one else responds via the ARP request that such pings will trigger from your own OS.
If no other device responds, the board will assign itself this IP address.
In this mode, there is no external route set and the behaviour, if pointed off the segment, is undefined.
Note that if you have multiple boards, they must be brought up one by one if operating in this mode.

## Initializing and taking pedestals

```
./mk01_calibrate.py -Ipq -w 14 -c "12 13 14 15 48 55" 10.0.6.212 1000
```

This will initialize (`-I`) the board at 10.0.6.212, enable channels (`-c`) 12-15, 48, and 55, set a delay of 14 units between trigger and stopping sampling (`-w`), and build a pedestal (`-p`) with 1000 samples.  It will do so quietly (`-q`): no ASCII dumps of waveforms to stdout.
The produced pedestal file will be `<boardhex>.pedestal`.

## Getting pedestal subtracted data (no timing calibration)

```
./mk01_calibrate.py -e -s 248e5610485c.pedestal -c "12 14" 10.0.6.212 10000 > pulses_DDMMYYYY
```

This will capture 10k hardware-triggered events (`-e`) from channels 12 and 14 of the board at 10.0.6.212, subtracting (`-s`) the given pedestal file, and dumping the ASCII of all these waveforms to `pulses_DDMMYYYY`.

## Getting noise curves (capacitor ordering, masking)

```
./mk01_calibrate -o -m 100 -s 248e5610485c.pedestal -c "12 14" 10.0.6.212 10 > noise_DDMMYYYY
```

Assuming you've not connected anything to the board, this will take noise traces.
It will keep data for all events ordered by capacitor (`-o`) (i.e. absolute).
It will also mask (`-m`) out (set to None or NaN) 100 capacitor positions leading up to the stop sample.
This is necessary in calibration, since the sampling turns off over a somewhat long timescale, and the artifacts are significant.
For actual data, you may mask at your own discretion.

## Getting per-capacitor gain calibrations

This is necessary for precision timing calibration.  It does not require a pedestal.

```
./gain_calibration.py 10.0.6.212 10000 0.7 1.0
```

This will measure per-capacitor gains, averaged over a sample of 10k software triggered events.
This is done by computing the slope between 0.7V and 1.0V.
This will do an ASCII dump of the gains, as well as produce a `<boardhex>.gains` file.
These values are reasonably close to the zero point, which is currently around 0.84V.

## Building a timing calibration

This will build a `<boardhex>.timing` file by issuing software triggers.
This requires a pedestal file.

```
./timing_calibration.py -s 248e5610485c.pedestal -g 248e5610485c.gains 10.0.6.212 10000 > ascii_dts
```

This will determine the temporal differences between adjacent capacitors in the delay lines, using calibration channels.
The pedestal (`-s`) is mandatory, and the gain correction (`-g`) is suggested.

## Taking data at maximal speed (for offline analysis)

This is accomplished via hardware triggers and listening on multiple ports with multiple processes.

```
./mk01_calibrate.py -e -c "15 55 14 48" -T 3 -f fancyrun 10.0.6.212 50000
```

This will record 50k events on 3 separate processes (`-T`) and write them to binary files with the prefix `fancyrun_`.

## Performing offline analysis on binary data

Offline analysis on binary data can also proceed in parallel.
To remove only pedestals,

```
./apply_calibration.py -s 248e5610485c.pedestal fancyrun* -T 3 
```

Notice the file globbing, so we are giving it all binary dump files made during the fancyrun.
To remove pedestals and perform timing,

```
./apply_calibration.py -s 248e5610485c.pedestal -t 248e5610485c.timing fancyrun* -T 3 
```

To dump a binary run to ASCII, use the `-d` flag

```
./apply_calibration.py calibrated_fancyrun_<timestamp>_<port> -d > ascii_dump 
```

Note that only one thread can (sensibly) write to stdout at a time, so dumping to ASCII cannot be run in parallel.
Dumping can be used for data at any level of calibration: uncalibrated, pedestal subtracted, timed, etc.
(Gain subtraction is also supported, but A21 does not have comprehensive gain measurements yet.)

## Notes
1. Software trigger rate is, by default, 1kHz.
2. The default operating DAC voltages values here are always reset at any tool run, and can be read from the comment headers of ./mk01_calibrate output
3. By default, masking is disabled. It is automatically enabled for calibration procedures.
4. The default ordering of all data reported is time-ordered, i.e. with the stop sample aligned at position zero for the event readout.
5. Calibration files are named with (essentially) the MAC address of the board.   This is build directly from the Xilinx device DNA, with a bit possibly turned off so that the MAC address is not a broadcast MAC address.