#!/usr/bin/python3

import pickle
import sys
from lappdProtocol import event

#
# Loads and then describes a pedestal
#

aPedestal = pickle.load(open(sys.argv[1], "rb"))

for chan in aPedestal.mean:

    print("# Channel: %d" % chan)

    n = 0

    #fmt = lambda x: x if not x is None else float('nan')
    
    for mean, var in zip(aPedestal.mean[chan], aPedestal.variance[chan]):
        #print(mean, var)

        if mean is None:
            mean = float('nan')

        if var is None:
            var = float('nan')
            
        print("%d %e %e %d" % (n, mean, var, chan))
        n += 1

    # Break on channel
    print("")
