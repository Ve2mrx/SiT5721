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
import json
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
DEFAULT_SETTINGS_FILE = os.path.join(os.path.expanduser("~"), "SiT-settings2.ini")
SETTINGS_SECTION = "Current"

EPOCH_UTC = datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc)
MAX_SANE_DELTA_T = datetime.timedelta(days=3650).total_seconds()

# Mirrors check-SiT5721-defaults.py's DEFAULTS/TOLERANCE (mbt-ubx-apps repo) -
# keep the two in sync if the datasheet defaults ever change.
POWER_ON_DEFAULTS = {
    "pull_value": 0.0,
    "pull_range": 1e-05,
    "aging_compensation": 0.0,
    "max_freq_ramp_rate": 1e-05,
}
DEFAULTS_TOLERANCE = 1e-9

# Shared with mbt-ubx-apps' get-data.py, which folds this into
# SiT-calib_output.txt and renames it aside once consumed - see
# project memory power-loss-mark-todo.
POWER_LOSS_MARK_FILE = os.path.expanduser("~/SiT-power-loss-mark.json")


def is_at_defaults(siTime):
    """True if siTime's config registers are still at hardware power-on
    defaults, i.e. this restart follows a real power loss (chip reset),
    not just an OS reboot with the chip staying powered."""
    return all(
        abs(getattr(siTime, field) - value) < DEFAULTS_TOLERANCE
        for field, value in POWER_ON_DEFAULTS.items()
    )


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

    # Cooked through float32 here, at the point these untrusted ini-file
    # values enter the program - the SiT5721's registers are float32, so
    # this is their true precision regardless of what the ini file's text
    # representation implies. Keeping every downstream use (writes,
    # prints, comparisons) already float32-clean avoids relying on each
    # call site to remember to cook_f32() before comparing against a
    # readback. config_ver/datetime aren't register values, left as-is.
    return (
        cook_f32(float(config[section]["total_offset_written"])),
        cook_f32(float(config[section]["pull_range"])),
        cook_f32(float(config[section]["aging_compensation"])),
        cook_f32(float(config[section]["max_freq_ramp_rate"])),
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
        print("On a real run these are written only if the chip is at "
              "power-on defaults (a real power loss); if the SiT kept its "
              "calibration, the live values are left untouched.")
        return EXIT_OK

    bus = smbus.SMBus(0)
    address = 0x60
    siTime = SiT5721(bus, address)

    # Captured before any writes below - SiT5721.__init__() already read
    # the current registers, so this reflects the chip's state going into
    # this restart, not the values we're about to write.
    power_loss = is_at_defaults(siTime)

    if not power_loss:
        # Registers are not at power-on defaults, so the chip kept its
        # calibration across this restart (e.g. an OS reboot with the SiT
        # staying powered). Its Pull/Aging are still live and correct;
        # rewriting them would re-fold the already-accumulated aging back
        # into the Pull and jump the output offset. Leave the running chip
        # untouched - the aging-corrected restart only applies after a real
        # power loss (chip reset to defaults).
        print()
        print("Registers are not at power-on defaults: calibration survived "
              "this restart (no power loss). Leaving the live values in "
              "place - no write performed.")
        print(f"Live Pull Value         {siTime.pull_value:=+.8g}")
        print(f"Live Aging compensation {siTime.aging_compensation:=+.8g} part/s")
        return EXIT_OK

    print()
    print("Power loss detected (registers at defaults): restoring the "
          "aging-corrected Pull Value.")

    # Order pull -> aging -> range -> ramp. write-SiT5721.py was aligned to
    # this order 2026-08-06 (it had briefly used constraints-first); keep the
    # two matching. Pull first means a bus failure part-way through leaves the
    # calibration applied, with the constraint registers still at the defaults
    # this path has already confirmed are in place.
    siTime.set_pull_value(new_pull)
    siTime.set_aging_comp(aging)
    siTime.set_pull_range(prange)
    siTime.set_max_freq_ramp_rate(ramp)

    siTime.read_SiT_config()

    # aging/prange/ramp are already float32-clean from read_settings() -
    # only new_pull needs cook_f32() here, since it's freshly computed
    # (total + aging * delta_t) rather than a direct passthrough read.
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

    if return_value == EXIT_OK:
        print()
        print("Recalculated and reloaded values verified. Leaving a mark "
              f"for get-data.py at {POWER_LOSS_MARK_FILE}")
        mark = {
            "detected_at": now.isoformat(),
            "settings_file": args.settings_file,
            "saved_datetime": saved_dt.isoformat(),
            "delta_t_seconds": delta_t,
            "aging_compensation": aging,
            "total_offset_written": total,
            "restart_pull_value": new_pull,
        }
        try:
            with open(POWER_LOSS_MARK_FILE, "w") as f:
                json.dump(mark, f, indent=2)
        except OSError as e:
            print(f"WARNING: failed to write {POWER_LOSS_MARK_FILE}: {e!r}", file=sys.stderr)

    return return_value


if __name__ == "__main__":
    sys.exit(main())
