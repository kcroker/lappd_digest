## Initializing and taking pedestals

```
./mk01_calibrate.py -Ipq -w 14 -c "12, 13, 14, 15, 48, 55" 10.0.6.212 1000
```

This will initialize (`-I`) the board at 10.0.6.212, enable channels (`-c`) 12-15, 48, and 55, set a delay of 14 units between trigger and stopping sampling (`-w`), and build a pedestal (`-p`) with 1000 samples.  It will do so quietly (`-q`): no ASCII dumps of waveforms to stdout.
The produced pedestal file will be `<boardhex>.pedestal`.

## Getting pedestal subtracted data (no timing calibration)

```
./mk01_calibrate.py -e -s <boardhex>.pedestal -c "12, 14" 10.0.6.212 10000 > pulses_DDMMYYYY
```

This will capture 10k hardware-triggered events (`-e`) from channels 12 and 14 of the board at 10.0.6.212, subtracting (`-s`) the given pedestal file, and dumping the ASCII of all these waveforms to `pulses_DDMMYYYY`.

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
./timing_calibration.py -s <boardhex>.pedestal -g <boardhex>.gains 10.0.6.212 10000 > ascii_dts

```

This will determine the temporal differences between adjacent capacitors in the delay lines, using calibration channels.
The pedestal (`-s`) is mandatory, and the gain correction (`-g`) is suggested.

## Notes
1. Software trigger rate is, by default, 1kHz.
2. The default operating DAC voltages values here are always reset at any tool run, and can be read from the comment headers of ./mk01_calibrate output