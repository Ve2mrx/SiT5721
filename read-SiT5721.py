#!/bin/python3
import os
import sys

# mbt_SiT5721_lib lives in the lib/mbt-SiT5721-lib submodule, shared with mbt-ubx-apps
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib", "mbt-SiT5721-lib"))

from mbt_SiT5721_lib import SiT5721
# import datetime
# import math
# import struct
# import time

import smbus

bus = smbus.SMBus(0)
address = 0x60


if __name__ == "__main__":
    siTime = SiT5721(bus, address)

    # siTime.read_SiT_static()  # Populated on init/print
    # siTime.read_SiT_config()  # Populated on init/print
    # siTime.read_SiT_operation()  # Populated on init/print
    # siTime.read_SiT_dynamic()  # Populated on init/print
    siTime.print_SiT_static()
    siTime.print_SiT_operation()
    siTime.print_SiT_dynamic()
