#!/bin/python3
import smbus
import struct
import datetime
from zoneinfo import ZoneInfo
import configparser
import contextlib
import io
import os
import sys
import tempfile

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

settings_file = sys.argv[1] if len(sys.argv) > 1 else "SiT-settings2.ini"
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

    def create_file(self, settings_file):

        with open(settings_file, "w") as configfile:
            self.config.write(configfile)

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

        # else:
        # self.create_file(settings_file)
        # self.config.read(settings_file)

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


def main():
    # config = configparser.ConfigParser()
    siTime = SiT5721(bus, address)
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
