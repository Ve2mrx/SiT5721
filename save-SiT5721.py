#!/bin/python3
import smbus
import struct
import datetime
from zoneinfo import ZoneInfo
import configparser
import contextlib
import io
import json
import os
import statistics
import subprocess
import sys
import tempfile

# mbt_SiT5721_lib lives in the lib/mbt-SiT5721-lib submodule, shared with mbt-ubx-apps
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib", "mbt-SiT5721-lib"))

from mbt_SiT5721_lib import SiT5721

bus = smbus.SMBus(0)
address = 0x60

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
STATUS_FILE = os.path.join(SCRIPT_DIR, "SiT-save_status.txt")


def atomic_write_text(path, text, mode=0o644):
    """Write text to path via a same-dir temp file + os.replace(), so a
    power failure mid-write can't leave a truncated/corrupt file."""
    directory = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=os.path.basename(path) + ".")
    try:
        os.chmod(tmp_path, mode)
        with os.fdopen(fd, "w") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        os.unlink(tmp_path)
        raise


class Tee(io.TextIOBase):
    """Writes to multiple streams at once - lets main() print to the
    terminal/journal as usual while also capturing the same text for
    STATUS_FILE."""

    def __init__(self, *streams):
        self.streams = streams

    def write(self, data):
        for stream in self.streams:
            stream.write(data)
        return len(data)

    def flush(self):
        for stream in self.streams:
            stream.flush()

# Note that a float has 7.225 decimal digit precision
new_pull_value = 0.000000000  # default 0.000000000
target_pull_value = 0.000000000  # default 0.000000000

new_pull_range = 0.000010000  # default 0.000010000 (10E-06)

# A positive value increases the output frequency, compensating for a negative aging trend.
# 2.0000000e-14 = 1.728ppb/day
new_aging_compensation = 0.000000000  # default 0.000000000

new_max_freq_ramp_rate = 0.000010000  # default 0.000010000 (1.00E-05)

settings_file = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.expanduser("~"), "SiT-settings2.ini")
settings_section = "Current"


class SiT5721_settings:
    def __init__(self):
        self.config = configparser.ConfigParser()

        self.config_ver = float(1.1)  # 1.1: pull_value renamed to total_offset_written
        self.datetime = float("NaN")
        self.total_offset_written = float("NaN")
        self.pull_range = float("NaN")
        self.aging_compensation = float("NaN")
        self.max_freq_ramp_rate = float("NaN")

        self.default_pull_value = 0.00000000
        self.default_pull_range = 0.000010000
        self.default_aging_compensation = 0.00000000
        self.default_max_freq_ramp_rate = 0.000010000

        # self.config['DEFAULT']['datetime'] = datetime.datetime.now(tz=datetime.timezone.utc).isoformat('T','auto')
        self.config["DEFAULT"] = {
            "datetime": datetime.datetime(1970, 1, 1, tzinfo=ZoneInfo("UTC")).isoformat(
                "T", "auto"
            ),
            "config_ver": self.config_ver,
            "total_offset_written": self.default_pull_value,
            "pull_range": self.default_pull_range,
            "aging_compensation": self.default_aging_compensation,
            "max_freq_ramp_rate": self.default_max_freq_ramp_rate,
        }

    def is_default(
        self,
        test_pull_value,
        test_pull_range,
        test_aging_compensation,
        test_max_freq_ramp_rate,
    ):
        return_value = True

        #  Cook default values
        #  Due to the SiT5721 being only 4 byte float, we need to reduce the precision to match
        cooked_pull_value = float(
            "".join(
                [
                    str(item)
                    for item in struct.unpack(
                        "f", bytes(
                            list(struct.pack("f", self.default_pull_value)))
                    )
                ]
            )
        )

        cooked_pull_range = float(
            "".join(
                [
                    str(item)
                    for item in struct.unpack(
                        "f", bytes(
                            list(struct.pack("f", self.default_pull_range)))
                    )
                ]
            )
        )

        cooked_aging_compensation = float(
            "".join(
                [
                    str(item)
                    for item in struct.unpack(
                        "f",
                        bytes(
                            list(struct.pack("f", self.default_aging_compensation))),
                    )
                ]
            )
        )

        cooked_max_freq_ramp_rate = float(
            "".join(
                [
                    str(item)
                    for item in struct.unpack(
                        "f",
                        bytes(
                            list(struct.pack("f", self.default_max_freq_ramp_rate))),
                    )
                ]
            )
        )

        if test_pull_value != cooked_pull_value:
            return_value = False
        if test_pull_range != cooked_pull_range:
            return_value = False
        if test_aging_compensation != cooked_aging_compensation:
            return_value = False
        if test_max_freq_ramp_rate != cooked_max_freq_ramp_rate:
            return_value = False

        # print(test_pull_value, cooked_pull_value)
        # print(test_pull_range, cooked_pull_range)
        # print(test_aging_compensation, cooked_aging_compensation)
        # print(test_max_freq_ramp_rate, cooked_max_freq_ramp_rate)
        # print(return_value)

        return return_value

    def read_file(self, settings_file, settings_section):
        if os.path.exists(settings_file) == True:
            self.config.read(settings_file)

        return (
            float(self.config[settings_section]["total_offset_written"]),
            float(self.config[settings_section]["pull_range"]),
            float(self.config[settings_section]["aging_compensation"]),
            float(self.config[settings_section]["max_freq_ramp_rate"]),
            self.config[settings_section]["datetime"],
            float(self.config[settings_section]["config_ver"]),
        )

    def write_file(self, settings_file, settings_section):
        self.config[settings_section] = dict()
        self.config[settings_section]["config_ver"] = str(self.config_ver)
        self.config[settings_section]["datetime"] = datetime.datetime.now(
            tz=datetime.timezone.utc
        ).isoformat("T", "auto")
        self.config[settings_section]["total_offset_written"] = str(
            self.total_offset_written)
        self.config[settings_section]["pull_range"] = str(self.pull_range)
        self.config[settings_section]["aging_compensation"] = str(
            self.aging_compensation
        )
        self.config[settings_section]["max_freq_ramp_rate"] = str(
            self.max_freq_ramp_rate
        )

        buffer = io.StringIO()
        self.config.write(buffer)
        atomic_write_text(settings_file, buffer.getvalue())

    def print(self, settings_file, settings_section):
        print("settings_file         ", settings_file)
        print("settings_section      ", settings_section)

        if self.datetime == float("NaN"):
            print("datetime              * NaN")
        else:
            print("datetime              ", self.datetime)

        print("Total Offset Written  ", self.total_offset_written)
        print("Pull Range            ", self.pull_range)
        print("Aging compensation    ", self.aging_compensation)
        print("Max. Freq Ramp Rate   ", self.max_freq_ramp_rate)


def cm4_soc_temp_c():
    """
    CM4 SoC temperature in degrees C, via `vcgencmd measure_temp` (the
    Raspberry Pi-supported interface - not a raw sysfs read, which isn't
    guaranteed to be the same thermal zone index across kernels/models),
    or None if unavailable.

    Logged alongside the SiT5721 registers as a diurnal proxy for
    enclosure-interior temperature - the LEA-M8F (mbt-ubx-apps) is not
    temperature-compensated the way the SiT5721 is, so this is relevant to
    phase-measurement noise. mbt-ubx-apps' get-data.py already reads this
    once/day into the main capture via its own copy of this function (small
    enough, and these are independent repos, to duplicate rather than share -
    same call as this file's own atomic_write_text()). Best-effort: never
    raises, so a missing/misbehaving vcgencmd can't affect the register-save
    this rides along with.

    :return float | None: SoC temperature in C, or None if unavailable
    """

    try:
        out = subprocess.run(
            ["vcgencmd", "measure_temp"],
            capture_output=True, text=True, timeout=2, check=True,
        ).stdout.strip()
        if not out.startswith("temp="):
            return None
        return float(out[len("temp="):].split("'")[0])
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


# Bump when the HEALTH,<version>,... line's field list changes, and give
# any reader (e.g. the sliding-window computation below) an explicit
# per-version field list to dispatch on - same convention as mbt-ubx-apps'
# CSV_LINE_VERSION/CSV_LINE_FIELDS_V<N> in parse_sit.py, adopted here before
# ~/sit-health.csv had more than one unversioned row in production.
HEALTH_LINE_VERSION = 2

# Field order for a HEALTH,1,... line, timestamp excluded (handled
# separately in _parse_health_line) - must match main()'s fh.write() below.
HEALTH_CSV_FIELDS_V1 = [
    "resonator_temp_c", "temp_error_c", "heater_power_w",
    "heater_power_target_w", "supply_v",
]

# v2 (2026-08-01) = v1 + CM4 SoC temp - fixes a gap against
# claude-code-health-logging-patch.md's own cooked-stats field list, which
# named cm4_soc_temp_c as one of the trailing-24h metrics despite this file
# never having read it (only get-data.py did, once/day, into the main
# capture). Append-only, same convention as CSV_LINE_FIELDS_V2 in
# mbt-ubx-apps' parse_sit.py.
HEALTH_CSV_FIELDS_V2 = HEALTH_CSV_FIELDS_V1 + ["cm4_soc_temp_c"]

# Superset across all versions - what compute_health_window_stats() reports
# on. A window can legitimately span both V1 and V2 lines (right after this
# version bump, until 24h of V1-only history ages out); handled by counting
# each field's own n from whichever samples actually have it, rather than
# assuming every sample has every field.
HEALTH_CSV_FIELDS_ALL = HEALTH_CSV_FIELDS_V2

HEALTH_WINDOW_SECONDS = 86400  # 24h - see claude-code-health-logging-patch.md sec 2


def _read_health_tail(path, tail_bytes=64 * 1024):
    """
    Reads the tail of `path`, bounded to `tail_bytes` - O(1) as the file
    grows forever (append-only). 64 KB is ~800 samples at the 600s sample
    rate (~5.5 days), comfortably more than the 24h window ever needs.

    :param str path: path to sit-health.csv (or a test file, same format)
    :param int tail_bytes: how much of the file's tail to read
    :return list[str]: complete lines from near the end of the file (the
        first line is dropped whenever the seek landed mid-file, since it
        may be a partial line)
    """
    with open(path, "rb") as fh:
        fh.seek(0, os.SEEK_END)
        size = fh.tell()
        fh.seek(max(0, size - tail_bytes))
        chunk = fh.read()
    lines = chunk.decode("utf-8", errors="replace").splitlines()
    if size > tail_bytes and lines:
        lines = lines[1:]  # drop a possibly-partial first line
    return lines


def _parse_health_line(line):
    """
    Parses one HEALTH,<version>,... line. Values are plain reprs of floats/
    ints and an ISO timestamp - none can contain a comma, so a plain split
    is safe (unlike parse_sit.py's CSV_LINE_RE, which uses csv.reader
    because build_csv_line() there does carry enum-ish string fields).

    :param str line: one line from sit-health.csv
    :return tuple[datetime.datetime, dict] | None: (UTC timestamp,
        {field: float}), or None if the line is not a recognized,
        well-formed HEALTH line - corrupt/truncated/unknown-version lines
        are skipped, never raised, so one bad line can't lose the rest of
        the window
    """
    parts = line.split(",")
    if len(parts) < 2 or parts[0] != "HEALTH":
        return None
    try:
        version = int(parts[1])
    except ValueError:
        return None
    if version == 1:
        fields = HEALTH_CSV_FIELDS_V1
    elif version == 2:
        fields = HEALTH_CSV_FIELDS_V2
    else:
        return None  # unrecognized future version - skip, never crash
    values = parts[2:]
    if len(values) != 1 + len(fields):  # + 1 for the timestamp
        return None
    try:
        ts = datetime.datetime.fromisoformat(values[0])
        # Empty string -> missing (e.g. cm4_soc_temp_c when vcgencmd
        # failed that run), not a parse error - see main()'s fh.write().
        data = {name: (None if v == "" else float(v)) for name, v in zip(fields, values[1:])}
    except ValueError:
        return None
    return ts, data


def compute_health_window_stats(csv_path, window_seconds=HEALTH_WINDOW_SECONDS, now=None):
    """
    Recomputes trailing-window statistics (mean/min/max/population-sd, plus
    n and the window bounds) for each field in HEALTH_CSV_FIELDS_ALL, from
    csv_path's recent history. Capture-time independent by construction:
    the window is anchored on `now`, not on when/whether a capture ran.

    A window can legitimately mix V1 and V2 lines (for 24h after any
    version bump that adds a field, e.g. cm4_soc_temp_c) or have individual
    None values (a field that's itself best-effort, e.g. cm4_soc_temp_c
    when vcgencmd failed that run) - each field's stats are computed only
    from the samples that actually have a non-None value for it, with its
    own "n" reported alongside, rather than assuming every sample has every
    field.

    Best-effort by design (see caller): returns None on any hard failure
    (missing/empty/unreadable file, or nothing falls inside the window)
    rather than raising, so a corrupt log can't take down the register-save
    this rides along with. Never extrapolates or back-fills a short
    window - n is reported honestly instead.

    :param str csv_path: path to sit-health.csv (or a test file, same format)
    :param float window_seconds: trailing window width, in seconds -
        overridable so this can be exercised against a small synthetic
        window before trusting it at real 24h scale
    :param datetime.datetime now: reference "now" for the window's end -
        overridable for tests; defaults to the real current UTC time
    :return dict | None: cooked stats dict (JSON-serializable), or None if
        nothing could be computed at all
    """
    if now is None:
        now = datetime.datetime.now(tz=datetime.timezone.utc)
    window_start = now - datetime.timedelta(seconds=window_seconds)

    try:
        lines = _read_health_tail(csv_path)
    except OSError:
        return None

    samples = []
    for line in lines:
        parsed = _parse_health_line(line)
        if parsed is None:
            continue
        ts, data = parsed
        if window_start <= ts <= now:
            samples.append(data)

    if not samples:
        return None

    result = {
        "n": len(samples),
        "window_start": window_start.isoformat(),
        "window_end": now.isoformat(),
        "generated": now.isoformat(),
    }
    for field in HEALTH_CSV_FIELDS_ALL:
        values = [s[field] for s in samples if s.get(field) is not None]
        if not values:
            continue  # no sample in this window has this field (yet)
        result[field] = {
            "n": len(values),
            "mean": statistics.mean(values),
            "min": min(values),
            "max": max(values),
            # Population sd (statistics.pstdev): this window IS the whole
            # population being described, not a sample of a larger one.
            "sd": statistics.pstdev(values) if len(values) > 1 else 0.0,
        }
    return result


def main():
    # config = configparser.ConfigParser()
    siTime = SiT5721(bus, address)

    # Health-log append (2026-08-01): SiT5721.__init__() above already
    # calls read_SiT_operation(), so these values are already in memory -
    # no extra I2C traffic. This service's job is saving register state;
    # a logging failure here must never prevent that, hence the bare
    # except and no re-raise. See
    # ubx-data/claude-code-health-logging-patch.md sec. 2.
    try:
        cm4_temp = cm4_soc_temp_c()  # None if vcgencmd unavailable/failed
        with open(os.path.join(os.path.expanduser("~"), "sit-health.csv"), "a") as fh:
            fh.write("HEALTH,{},{},{!r},{!r},{!r},{!r},{!r},{}\n".format(
                HEALTH_LINE_VERSION,
                datetime.datetime.now(tz=datetime.timezone.utc).isoformat(),
                siTime.temperature_float,       # 0xA1 resonator temp, C
                siTime.temperature_err_float,   # 0xB0 temp error, C
                siTime.heater_power_float,      # 0xA7 heater power, W
                siTime.heater_power_target_float,
                siTime.supply_voltage_float,    # 0xA3 supply, V
                ("" if cm4_temp is None else repr(cm4_temp))))
    except Exception:
        pass

    # Trailing 24h statistics, recomputed from scratch every run (2026-08-01,
    # Step 3) - capture-time independent by construction (see
    # compute_health_window_stats()'s docstring), so this is unaffected by
    # whenever mbt-ubx-apps' daily capture happens to run. Best-effort, same
    # reasoning as the health-log append above: this must never affect the
    # register-save.
    try:
        stats = compute_health_window_stats(
            os.path.join(os.path.expanduser("~"), "sit-health.csv"))
        if stats is not None:
            buf = io.StringIO()
            json.dump(stats, buf, indent=2)
            atomic_write_text(
                os.path.join(os.path.expanduser("~"), "sit-health-24h.json"),
                buf.getvalue())
    except Exception:
        pass

    SiT_config = SiT5721_settings()

    # siTime.read_SiT_static()  # Populated on init
    # siTime.read_SiT_config()  # Populated on init
    # siTime.read_SiT_operation()  # Populated on init
    # siTime.read_SiT_dynamic()  # Populated on init

    # (   SiT_config.total_offset_written,
    # SiT_config.pull_range,
    # SiT_config.aging_compensation,
    # SiT_config.max_freq_ramp_rate,
    # SiT_config.datetime) = SiT_config.read_file(settings_file, settings_section)

    # siTime.print_SiT_static()
    # siTime.print_SiT_operation()
    siTime.print_SiT_dynamic()
    # siTime.print_SiT_derived()

    # siTime.set_pull_value(new_pull_value)
    # siTime.set_pull_value_from_target(target_pull_value)  # For future instantaneous use
    # siTime.set_pull_range(new_pull_range)
    # siTime.set_aging_comp(new_aging_compensation)
    # siTime.set_max_freq_ramp_rate(new_max_freq_ramp_rate)

    # siTime.read_SiT_config()
    # siTime.read_SiT_dynamic()  # Refresh!

    # print()
    # print("--- Updated:")
    # siTime.print_SiT_short()

    # print("pre-write:")
    # print_settings(settings_file, SiT_config.total_offset_written, SiT_config.pull_range, SiT_config.aging_compensation, SiT_config.max_freq_ramp_rate, SiT_config.datetime)

    return_value = 0

    if (
        SiT_config.is_default(
            siTime.pull_value,
            siTime.pull_range,
            siTime.aging_compensation,
            siTime.max_freq_ramp_rate,
        )
        == False
    ):

        SiT_config.total_offset_written = siTime.total_offset_written
        SiT_config.pull_range = siTime.pull_range
        SiT_config.aging_compensation = siTime.aging_compensation
        SiT_config.max_freq_ramp_rate = siTime.max_freq_ramp_rate

        SiT_config.write_file(settings_file, settings_section)

        (
            SiT_config.total_offset_written,
            SiT_config.pull_range,
            SiT_config.aging_compensation,
            SiT_config.max_freq_ramp_rate,
            SiT_config.datetime,
            SiT_config.config_ver,
        ) = SiT_config.read_file(settings_file, settings_section)

        print()

        print("post-write:")
        SiT_config.print(settings_file, settings_section)

        print()

        if SiT_config.total_offset_written == siTime.total_offset_written:
            print("Total Offset Written  match!")
        else:
            print("Total Offset Written  MISMATCH!")
            return_value = 1

        if SiT_config.pull_range == siTime.pull_range:
            print("Pull Range            match!")
        else:
            print("Pull Range            MISMATCH!")
            return_value = 1

        if SiT_config.aging_compensation == siTime.aging_compensation:
            print("Aging compensation    match!")
        else:
            print("Aging compensation    MISMATCH!")
            return_value = 1

        if SiT_config.max_freq_ramp_rate == siTime.max_freq_ramp_rate:
            print("Max. Freq Ramp Rate   match!")
        else:
            print("Max. Freq Ramp Rate   MISMATCH!")
            return_value = 1

    else:
        print("Not saving, values are default!")
        return_value = 2

    return return_value


if __name__ == "__main__":
    capture = io.StringIO()
    with contextlib.redirect_stdout(Tee(sys.stdout, capture)):
        main()
    atomic_write_text(STATUS_FILE, capture.getvalue())
