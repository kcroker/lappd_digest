*WARNING:* for all of these, the stdout buffer will not flush unless you force it to. So I just Ctrl+C to kill the
process, which forces "output" to be fully written.

Quick usage:

```
./generic_run_example.py 10.0.6.212 > output
```

This will:
1 build a pedestal for the A21 with 100 samples
2 write this pedestal out to a file MACADDRESS.pedestal
3 then write ASCII plottable data of the packets as they come in, pedestal substracted

```
./generic_run_example.py 10.0.6.212 111111111111.pedestal > output
```

This will:
1 attempt to load a pedestal made for the board with mac address 11:11:11:11:11:11
2 then write ASCII plottable data of the packets as they come in, pedestal subtracted

```
./generic_run_example.py 10.0.6.212 NONE > output
```

This will:
1 write ASCII plottable data of the packets as they come in, no pedestals!
