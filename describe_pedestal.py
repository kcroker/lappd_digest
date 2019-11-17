#!/usr/bin/python3

import pickle
import sys
from lappdProtocol import event

#
# Loads and then describes a pedestal
#

aPedestal = pickle.load(open(sys.argv[1], "rb"))

for chan in aPedestal.mean:

    print("# Channel: %d\n" % chan)

    n = 0
    for mean, var in zip(aPedestal.mean[chan], aPedestal.variance[chan]):
        print("%d %s %s" % (n, repr(mean), repr(var)))
        n += 1

    # Break on channel
    print("")
