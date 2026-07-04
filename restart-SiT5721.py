#!/bin/python3
# Aging-corrected restart Pull Value for SiT5721. See restart-pull-fix-brief.md.
#
# On power failure the SiT5721 resets Pull/Aging/Total offset to 0. Simply
# reloading the last saved Total Offset Written as the new Pull ignores the
# time elapsed since that save, so the Pull is off until a manual recalc days
# later. This extrapolates forward by the aging that occurred during the gap:
#   Pull_restart = last_total_offset_written + aging_compensation * delta_t

import argparse
import configparser
import datetime
import os
import struct
import sys

import smbus

# mbt_SiT5721_lib lives in the lib/mbt-SiT5721-lib submodule, shared with mbt-ubx-apps
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib", "mbt-SiT5721-lib"))

from mbt_SiT5721_lib import SiT5721

# Exit codes: 0 success, 1 I2C write/readback mismatch (real failure),
# 2 refused to run (no valid prior save, bad clock, etc. - not fatal to a
# caller that just wants to fall back to starting the save screen as-is).
EXIT_OK = 0
EXIT_MISMATCH = 1
EXIT_REFUSED = 2

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SETTINGS_FILE = os.path.join(SCRIPT_DIR, "SiT-settings2.ini")
SETTINGS_SECTION = "Current"

EPOCH_UTC = datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc)
MAX_SANE_DELTA_T = datetime.timedelta(days=3650).total_seconds()


def cook_f32(value):
    """Round-trip through float32, matching what the SiT itself will store."""
    return struct.unpack("f", struct.pack("f", value))[0]


def refuse(message):
    print(f"Refusing to run: {message}", file=sys.stderr)
    sys.exit(EXIT_REFUSED)


def read_settings(settings_file, section=SETTINGS_SECTION):
    if not os.path.exists(settings_file):
        refuse(f"settings file not found: {settings_file}")

    config = configparser.ConfigParser()
    config.read(settings_file)

    return (
        float(config[section]["total_offset_written"]),
        float(config[section]["pull_range"]),
        float(config[section]["aging_compensation"]),
        float(config[section]["max_freq_ramp_rate"]),
        config[section]["datetime"],
        float(config[section]["config_ver"]),
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("settings_file", nargs="?", default=DEFAULT_SETTINGS_FILE)
    parser.add_argument("--dry-run", action="store_true",
                         help="Compute and print only, no I2C write")
    args = parser.parse_args()

    total, prange, aging, ramp, saved_dt_str, ver = read_settings(args.settings_file)

    saved_dt = datetime.datetime.fromisoformat(saved_dt_str)
    if saved_dt.tzinfo is None:
        saved_dt = saved_dt.replace(tzinfo=datetime.timezone.utc)

    if saved_dt == EPOCH_UTC:
        refuse("settings file was never saved (1970 epoch datetime).")

    if total == 0.0 and aging == 0.0:
        refuse("settings are default (Total Offset Written and Aging "
               "compensation are both 0) - nothing to restore.")

    now = datetime.datetime.now(tz=datetime.timezone.utc)
    delta_t = (now - saved_dt).total_seconds()

    if delta_t < 0:
        refuse(f"saved datetime {saved_dt.isoformat()} is in the future "
               f"(delta_t = {delta_t:.0f}s). Check the system clock.")
    if delta_t > MAX_SANE_DELTA_T:
        refuse(f"delta_t = {delta_t:.0f}s ({delta_t / 86400:.1f} days) exceeds "
               f"the sanity limit of {MAX_SANE_DELTA_T / 86400:.0f} days. "
               f"Check the system clock.")

    new_pull = total + aging * delta_t

    print(f"Settings file           {args.settings_file}")
    print(f"Saved datetime          {saved_dt.isoformat()}")
    print(f"Now                     {now.isoformat()}")
    print(f"Delta t                 {delta_t:.0f}s ({delta_t / 3600:.2f}h)")
    print(f"Aging compensation      {aging:=+.8g} part/s")
    print(f"Total Offset Written    {total:=+.8g}  (uncorrected restart Pull)")
    print(f"Restart Pull Value      {new_pull:=+.8g}  (aging-corrected)")

    if args.dry_run:
        print()
        print("Dry run - no I2C write performed.")
        return EXIT_OK

    bus = smbus.SMBus(0)
    address = 0x60
    siTime = SiT5721(bus, address)

    siTime.set_pull_value(new_pull)
    siTime.set_aging_comp(aging)
    siTime.set_pull_range(prange)
    siTime.set_max_freq_ramp_rate(ramp)

    siTime.read_SiT_config()

    checks = (
        ("Pull Value", cook_f32(new_pull), siTime.pull_value),
        ("Aging compensation", aging, siTime.aging_compensation),
        ("Pull Range", prange, siTime.pull_range),
        ("Max. Freq Ramp Rate", ramp, siTime.max_freq_ramp_rate),
    )

    print()
    return_value = EXIT_OK
    for label, expected, actual in checks:
        if expected == actual:
            print(f"{label:<24}match!")
        else:
            print(f"{label:<24}MISMATCH! (wrote {expected!r}, read back {actual!r})")
            return_value = EXIT_MISMATCH

    return return_value


if __name__ == "__main__":
    sys.exit(main())
