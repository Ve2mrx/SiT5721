#!/usr/bin/env python3
"""
Write Pull Value / Aging Compensation / Pull Range / Max Freq Ramp Rate to a
SiT5721 (I2C 0x60).

Values come from a CSV OUTSIDE the repo - by default ~/SiT5721-pull-values.csv.
That file is this device's calibration history: one row per intended write,
newest last, and the script uses the LAST row. It replaces the old kludge of
editing constants at the top of this file and keeping a commented stack of
previous values, which meant every re-tune was edit -> commit -> pull on the
device -> run.

    python3 write-SiT5721.py                 # DRY RUN - shows the plan, writes nothing
    python3 write-SiT5721.py --commit        # actually write
    python3 write-SiT5721.py --show          # just read the device and stop
    python3 write-SiT5721.py --file X.csv    # use a different values file

If the values file is missing, an annotated example is written to that path and
the script exits WITHOUT touching the device.

!! DRY RUN IS THE DEFAULT. The previous version wrote all four registers on
   every single run, so merely inspecting the device changed it. You must now
   pass --commit. Nothing else about the register writes has changed.

--------------------------------------------------------------------------
WHAT GETS WRITTEN, AND WHY IT IS NOT DERIVED HERE
--------------------------------------------------------------------------
`pull` in the CSV is the RAW Pull register value, taken straight from the
workbook's Calc-new-<cycle> **row 75** (last day column). It is written to
register 0x61 as-is. The script does NOT recompute it.

That is deliberate. The device relates the registers as

    total_offset = pull_value + aging_compensation * uptime

so a Pull value could in principle be derived from a desired total offset:
`pull = target - aging*uptime`. The workbook already does exactly that -
row 75 = row 73 (target, trended) - row 74 (current compensation) - using the
uptime **at the moment the value was calculated**. Verified on the real
2026-03-28 re-tune: Calc-new-60313 day 15 gives row 73 = 1.23264846e-07 and
row 75 = 1.24157120e-07, matching the two constants this script used to carry.

Re-deriving it here would use the uptime **at write time**, which is a
different number. In the power-loss case - one of the two situations this
script is used in - the SiT has reset and uptime is ~0, so the derivation
would collapse to `pull = target` and write 1.23264846e-07 instead of
1.24157120e-07: wrong by 0.89 ppb, in precisely the scenario the script
exists for.

`target_pull` is therefore recorded in the CSV for provenance only (it is the
workbook's row 73) and is never used to compute anything. The old code carried
both as constants the same way; only `new_pull_value` was ever written, and
`calc_SiT_new_pull_value_from_target()` was future intent that was never
wired in. `pull_for_target()` below preserves that intent as a helper, unused,
with the caveat attached.

--------------------------------------------------------------------------
UNITS
--------------------------------------------------------------------------
pull         RAW Pull register value, fractional offset ("part").
             Workbook Calc-new-<cycle> row 75, last day column.
             e.g. 1.24157120E-07 == 0.124157120 ppm.  *** THIS IS WRITTEN ***
target_pull  workbook row 73 - desired total offset. Recorded for provenance
             only; never used in a calculation. May be left blank.
aging        fractional offset per second ("part/s"), e.g. -6.97342370E-16
pull_range   fractional offset, device default 1.0E-05
ramp_rate    fractional offset, device default 1.0E-05

A positive aging value increases output frequency over time, compensating a
negative aging trend. 2.0E-14 part/s = 1.728 ppb/day.
"""

import argparse
import csv
import datetime
import os
import struct
import sys

I2C_BUS = 0
I2C_ADDRESS = 0x60

DEFAULT_VALUES_FILE = os.path.expanduser("~/SiT5721-pull-values.csv")
DEFAULT_LOG_FILE = os.path.expanduser("~/SiT5721-write-log.csv")

# Bump when the values-CSV column set changes. Written as the first column of
# every row so a reader can dispatch per row and one file may hold a mix -
# same convention as CSV_LINE_VERSION in mbt-ubx-apps and HEALTH_LINE_VERSION
# in save-SiT5721.py.
#
# CHANGELOG
#   1  2026-08-05  initial: ver,date,pull,target_pull,aging,pull_range,
#                  ramp_rate,note. 'pull' is written; 'target_pull' is
#                  recorded for provenance and never used in a calculation.
VALUES_VERSION = 1

VALUES_FIELDS = ["ver", "date", "pull", "target_pull", "aging",
                 "pull_range", "ramp_rate", "note"]

# Sanity bounds. These are deliberately loose - they exist to catch a typo or a
# misplaced exponent, not to second-guess a deliberate calibration.
MAX_ABS_AGING = 1e-12          # part/s; observed values are ~1e-16
MAX_RANGE = 1e-4               # part; device default is 1e-5

EXAMPLE_CSV = f"""\
# SiT5721 calibration values - THIS DEVICE ONLY, not tracked in git.
#
# One row per intended write, newest LAST. write-SiT5721.py uses the LAST
# data row. Keep old rows: this file is the calibration history that used to
# live as commented-out constants inside write-SiT5721.py.
#
# ver         schema version (currently {VALUES_VERSION})
# date        when the value was calculated (free text, ISO date preferred)
# pull        *** THE VALUE WRITTEN ***  raw Pull register value, fractional
#             offset "part". Copy from the workbook: Calc-new-<cycle> row 75,
#             last DAY column (not the rightmost - skeleton columns carry
#             copies). 1.0E-07 part = 0.1 ppm.
# target_pull workbook row 73. Recorded for provenance only, never used to
#             compute anything - see the script docstring for why. Optional.
# aging       aging compensation, part/s. Positive raises frequency over time.
# pull_range  device default 1.0E-05
# ramp_rate   max frequency ramp rate, device default 1.0E-05
# note        free text - how the value was derived, e.g. the fit window
#
# Nothing is written unless you pass --commit.
#
{",".join(VALUES_FIELDS)}
{VALUES_VERSION},2025-11-28,1.40458797E-07,1.39454720E-07,-6.97342370E-16,1.0E-05,1.0E-05,17d calculated end 2025-11-28 19:04:42+00:00 with trend
{VALUES_VERSION},2026-03-11,1.31595357E-07,1.31595357E-07,-6.97342370E-16,1.0E-05,1.0E-05,17d calculated end 2026-03-11 19:16:22+00:00 with trend
{VALUES_VERSION},2026-03-28,1.24157120E-07,1.23264846E-07,-6.97342370E-16,1.0E-05,1.0E-05,15d calculated end 2026-03-28 19:16:22+00:00 with trend
"""


def load_values(path):
    """Last data row of the values CSV as a dict of floats.

    If the file is missing, writes EXAMPLE_CSV there and returns None - the
    caller must then exit without touching the device. Writing an example
    rather than inventing defaults is deliberate: a plausible-looking default
    is exactly how a zero gets written over a good calibration."""
    if not os.path.exists(path):
        with open(path, "w", newline="") as fh:
            fh.write(EXAMPLE_CSV)
        print(f"WARNING  no values file at {path}", file=sys.stderr)
        print(f"WARNING  an annotated example has been written there.",
              file=sys.stderr)
        print(f"WARNING  EDIT IT, then re-run. Nothing was written to the device.",
              file=sys.stderr)
        return None

    rows = []
    with open(path, newline="") as fh:
        for row in csv.DictReader(r for r in fh if not r.lstrip().startswith("#")):
            if row.get("ver"):
                rows.append(row)
    if not rows:
        print(f"ERROR  {path} has no data rows", file=sys.stderr)
        return None

    row = rows[-1]
    if row["ver"].strip() != str(VALUES_VERSION):
        print(f"ERROR  last row has ver={row['ver']}, this script speaks "
              f"ver={VALUES_VERSION}", file=sys.stderr)
        return None

    out = {"date": (row.get("date") or "").strip(),
           "note": (row.get("note") or "").strip(),
           "_row": len(rows)}
    for k in ("pull", "aging", "pull_range", "ramp_rate"):
        try:
            out[k] = float(row[k])
        except (KeyError, TypeError, ValueError):
            print(f"ERROR  {path} last row: '{k}' is missing or not a number",
                  file=sys.stderr)
            return None
    # Provenance only - blank is fine, and it is never used in a calculation.
    raw = (row.get("target_pull") or "").strip()
    try:
        out["target_pull"] = float(raw) if raw else None
    except ValueError:
        print(f"ERROR  {path} last row: 'target_pull' is not a number", file=sys.stderr)
        return None
    return out


def validate(vals, dev, allow_zero, force):
    """List of blocking problems. Empty list == safe to write."""
    bad = []
    if not allow_zero and vals["pull"] == 0.0:
        bad.append("pull is 0 - that would wipe the calibration. "
                   "Pass --allow-zero if you really mean to reset it.")
    if vals["pull_range"] <= 0 or vals["pull_range"] > MAX_RANGE:
        bad.append(f"pull_range {vals['pull_range']:.3e} outside (0, {MAX_RANGE:.0e}]")
    if vals["ramp_rate"] <= 0:
        bad.append(f"ramp_rate {vals['ramp_rate']:.3e} must be > 0")
    if abs(vals["aging"]) > MAX_ABS_AGING:
        bad.append(f"|aging| {abs(vals['aging']):.3e} > {MAX_ABS_AGING:.0e} - "
                   f"check the exponent")
    # The Pull register must fit inside the Pull Range or the device clamps it.
    if abs(vals["pull"]) > vals["pull_range"]:
        bad.append(f"pull {vals['pull']:.6e} exceeds pull_range "
                   f"{vals['pull_range']:.3e} - it would be clamped")
    if not force:
        if dev.error_status_str != "good":
            bad.append(f"device error status is '{dev.error_status_str}' "
                       f"(--force to override)")
        if dev.stability_status_str != "stabilized":
            bad.append(f"device is '{dev.stability_status_str}' - writing to an "
                       f"unstabilized oscillator gives a meaningless result "
                       f"(--force to override)")
    return bad


class SiT5721:
    """Register access per the SiTime SiT5721 datasheet rev 1.0.

    Reads only on construction; every write is an explicit method call, so
    instantiating this class can never modify the device."""

    def __init__(self, bus, address):
        self.bus = bus
        self.address = address
        self.read_static()
        self.read_config()
        self.read_operation()
        self.read_dynamic()

    def _f32(self, reg):
        """One float32 register. struct.unpack returns a 1-tuple; take [0].

        The old code did float(''.join(str(x) for x in unpack(...))), which
        round-trips the value through decimal text for no reason and can lose
        the last bit or two."""
        return struct.unpack('f', bytes(
            self.bus.read_i2c_block_data(self.address, reg, 4)))[0]

    def _u32(self, reg):
        return struct.unpack('I', bytes(
            self.bus.read_i2c_block_data(self.address, reg, 4)))[0]

    def _ascii(self, reg, n=32):
        # smbus cannot read the full 256-byte part-number field; 32 is enough.
        return ''.join(chr(c) for c in
                       self.bus.read_i2c_block_data(self.address, reg, n))

    def read_static(self):
        self.part_num_str = self._ascii(0x50)      # 0x50 Part Number
        self.nomfreq_str = self._ascii(0x52)       # 0x52 Nominal Frequency
        self.lot_sn_str = self._ascii(0x56)        # 0x56 Lot and Serial Numbers
        self.fab_date_str = self._ascii(0x57)      # 0x57 Fabrication Date

    def read_config(self):
        self.pull_value = self._f32(0x61)          # 0x61 Pull Value, R/W
        self.pull_range = self._f32(0x62)          # 0x62 Pull Range, R/W
        self.aging_compensation = self._f32(0x63)  # 0x63 Aging Compensation, R/W
        self.max_freq_ramp_rate = self._f32(0x64)  # 0x64 Max Freq Ramp Rate, R/W

    def read_operation(self):
        # 0xA1 Resonator Temp. (the old comment here said 0xAB - copy-paste
        # from the Total Offset read below; same bug already fixed in
        # mbt-SiT5721-lib, commit 0422f5a).
        self.temperature_float = self._f32(0xA1)
        self.supply_voltage_float = self._f32(0xA3)        # 0xA3 Supply Voltage
        self.heater_power_float = self._f32(0xA7)          # 0xA7 Heater Power
        self.temperature_err_float = self._f32(0xB0)       # 0xB0 Temp. Error
        self.heater_power_target_float = self._f32(0xB1)   # 0xB1 Power Target

    def read_dynamic(self):
        self.uptime_uint = self._u32(0xA0)                 # 0xA0 Time Since Power Up
        self.total_offset_written = self._f32(0xAB)        # 0xAB Total Offset Written
        self.error_status_flag_uint = self._u32(0xAE)      # 0xAE Error Status Flag
        self.stability_flag_uint = self._u32(0xAF)         # 0xAF Stability Flag
        self.error_status_str = ("good" if self.error_status_flag_uint == 7
                                 else "ERROR")
        self.stability_status_str = ("stabilized" if self.stability_flag_uint == 1
                                     else "unstabilized")

    # ---- derived -------------------------------------------------------
    def current_compensation(self):
        """total_offset_written - pull_value, i.e. aging_compensation*uptime."""
        return self.total_offset_written - self.pull_value

    def pull_for_target(self, target_pull, aging):
        """Raw Pull register value that would land total_offset on target_pull
        at THIS MOMENT's uptime.

        !! DELIBERATELY UNUSED - do not wire this into the write path.
        The workbook already performs this conversion (row 75 = row 73 - row 74)
        using the uptime at CALCULATION time, and row 75 is what the CSV's
        `pull` column carries. Recomputing here would use the uptime at WRITE
        time instead, giving a different answer - and after a power loss, where
        uptime is ~0, it collapses to `pull = target` and is wrong by the whole
        accumulated compensation (0.89 ppb on the real 2026-03-28 re-tune).
        Kept only because the original code carried the same intent, unwired,
        as calc_SiT_new_pull_value_from_target()."""
        return target_pull - aging * self.uptime_uint

    # ---- writes --------------------------------------------------------
    def _write_f32(self, reg, value):
        self.bus.write_i2c_block_data(self.address, reg,
                                      list(struct.pack('f', value)))

    def set_pull_value(self, v):        self._write_f32(0x61, v)
    def set_pull_range(self, v):        self._write_f32(0x62, v)
    def set_aging_comp(self, v):        self._write_f32(0x63, v)
    def set_max_freq_ramp_rate(self, v): self._write_f32(0x64, v)

    # ---- printing ------------------------------------------------------
    def print_static(self):
        print(f"Part Number             {self.part_num_str}")
        print(f"Nominal frequency       {self.nomfreq_str}")
        print(f"Lot-SN                  {self.lot_sn_str}")
        print(f"Fabrication             {self.fab_date_str}")
        print()

    def print_operation(self):
        print(f"Supply voltage          {self.supply_voltage_float:.8g} V")
        print(f"Resonator temperature   {self.temperature_float:=3.8g} degC")
        print(f"Temperature error       {self.temperature_err_float:=+3.8g} degC")
        print(f"Heater power            {self.heater_power_float:.8g} W")
        print(f"Target power            {self.heater_power_target_float:.8g} W")
        print()

    def print_dynamic(self):
        print(f"Uptime                  {self.uptime_uint}s "
              f"({datetime.timedelta(seconds=self.uptime_uint)})")
        print(f"Error status flag       {self.error_status_str}")
        print(f"Stability flag          {self.stability_status_str}")
        print()
        self.print_short()

    def print_short(self):
        print(f"Pull Value              {self.pull_value / 1e-6:=+.8g} ppm")
        print(f"Pull Range              {self.pull_range / 1e-6:=.8g} ppm")
        print(f"Aging compensation      {self.aging_compensation:=+.8g} part/s")
        print(f"Max. Freq Ramp Rate     {self.max_freq_ramp_rate / 1e-6:=.8g} ppm")
        print(f"Total offset written    {self.total_offset_written / 1e-6:=+.8g} ppm")


def append_log(path, dev_before, dev_after, vals):
    """Append one audit row: what was intended, what was on the device before,
    and what the device reported after the write. Separate from the values
    file so that intent and outcome never get confused for one another."""
    new = not os.path.exists(path)
    with open(path, "a", newline="") as fh:
        w = csv.writer(fh)
        if new:
            w.writerow(["ver", "written_utc", "values_date", "values_row",
                        "uptime_s",
                        "pull", "target_pull", "aging",
                        "pull_range", "ramp_rate",
                        "before_pull", "before_aging", "before_total",
                        "after_pull", "after_aging", "after_total",
                        "note"])
        w.writerow([VALUES_VERSION,
                    datetime.datetime.now(datetime.timezone.utc).isoformat(),
                    vals["date"], vals["_row"], dev_before.uptime_uint,
                    repr(vals["pull"]),
                    ("" if vals["target_pull"] is None else repr(vals["target_pull"])),
                    repr(vals["aging"]), repr(vals["pull_range"]),
                    repr(vals["ramp_rate"]),
                    repr(dev_before.pull_value),
                    repr(dev_before.aging_compensation),
                    repr(dev_before.total_offset_written),
                    repr(dev_after.pull_value),
                    repr(dev_after.aging_compensation),
                    repr(dev_after.total_offset_written),
                    vals["note"]])


def as_f32(x):
    """Value as the device will store it, for read-back comparison."""
    return struct.unpack('f', struct.pack('f', x))[0]


def main():
    ap = argparse.ArgumentParser(
        description="Write SiT5721 calibration registers from a values CSV.")
    ap.add_argument("--file", default=DEFAULT_VALUES_FILE,
                    help=f"values CSV (default {DEFAULT_VALUES_FILE})")
    ap.add_argument("--log", default=DEFAULT_LOG_FILE,
                    help=f"audit log appended on write (default {DEFAULT_LOG_FILE})")
    ap.add_argument("--commit", action="store_true",
                    help="actually write. WITHOUT THIS NOTHING IS WRITTEN.")
    ap.add_argument("--show", action="store_true",
                    help="read and print the device, then stop")
    ap.add_argument("--allow-zero", action="store_true",
                    help="permit target_pull = 0 (resets the calibration)")
    ap.add_argument("--force", action="store_true",
                    help="write even if the device is in error/unstabilized")
    a = ap.parse_args()

    try:
        import smbus
        bus = smbus.SMBus(I2C_BUS)
    except Exception as exc:
        print(f"ERROR  cannot open I2C bus {I2C_BUS}: {exc}", file=sys.stderr)
        return 1

    try:
        dev = SiT5721(bus, I2C_ADDRESS)
    except Exception as exc:
        print(f"ERROR  cannot read SiT5721 at 0x{I2C_ADDRESS:02X}: {exc}",
              file=sys.stderr)
        return 1

    dev.print_static()
    dev.print_operation()
    dev.print_dynamic()

    if a.show:
        return 0

    vals = load_values(a.file)
    if vals is None:
        return 1

    print()
    print(f"--- Planned write   (from {a.file}, row {vals['_row']}, "
          f"dated {vals['date'] or 'n/a'})")
    if vals["note"]:
        print(f"    note                {vals['note']}")
    print(f"  new Pull Value        {vals['pull'] / 1e-6:=+.8g} ppm"
          f"   (was {dev.pull_value / 1e-6:=+.8g})")
    print(f"  new Aging comp.       {vals['aging']:=+.8g} part/s"
          f"   (was {dev.aging_compensation:=+.8g})")
    print(f"  new Pull Range        {vals['pull_range'] / 1e-6:=.8g} ppm")
    print(f"  new Ramp Rate         {vals['ramp_rate'] / 1e-6:=.8g} ppm")
    if vals["target_pull"] is not None:
        print(f"    (workbook row 73 target, for the record: "
              f"{vals['target_pull'] / 1e-6:=+.8g} ppm - not used here)")
    # Predicted total offset AFTER the write, at the current uptime. Shown as a
    # sanity check only; the value written is `pull`, taken as given.
    predicted = vals["pull"] + vals["aging"] * dev.uptime_uint
    print(f"  => Pull register moves {(vals['pull'] - dev.pull_value) / 1e-9:=+.4g} ppb")
    print(f"     total offset {dev.total_offset_written / 1e-6:=+.8g} -> "
          f"{predicted / 1e-6:=+.8g} ppm (at uptime {dev.uptime_uint}s)")

    problems = validate(vals, dev, a.allow_zero, a.force)
    if problems:
        print()
        for p in problems:
            print(f"REFUSING  {p}", file=sys.stderr)
        return 1

    if not a.commit:
        print()
        print("DRY RUN - nothing written. Re-run with --commit to apply.")
        return 0

    # Constraint registers first, so the Pull value that must satisfy them is
    # written last and is never briefly outside a stale range.
    dev.set_pull_range(vals["pull_range"])
    dev.set_max_freq_ramp_rate(vals["ramp_rate"])
    dev.set_aging_comp(vals["aging"])
    dev.set_pull_value(vals["pull"])

    after = SiT5721(bus, I2C_ADDRESS)
    print()
    print("--- Updated:")
    after.print_short()

    ok = True
    for name, got, want in (("Pull Value", after.pull_value, vals["pull"]),
                            ("Aging comp.", after.aging_compensation, vals["aging"]),
                            ("Pull Range", after.pull_range, vals["pull_range"]),
                            ("Ramp Rate", after.max_freq_ramp_rate, vals["ramp_rate"])):
        if got != as_f32(want):
            print(f"VERIFY FAILED  {name}: device reports {got!r}, "
                  f"expected {as_f32(want)!r}", file=sys.stderr)
            ok = False
    print()
    print("Read-back verified." if ok else "READ-BACK MISMATCH - see above.")

    append_log(a.log, dev, after, vals)
    print(f"Logged to {a.log}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
