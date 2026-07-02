#!/bin/python3
import smbus
import struct
import datetime

bus = smbus.SMBus(0)
address = 0x60

new_pull_value_list = struct.pack('f', 0.000000000) # default 0.000000000
new_pull_range_list = struct.pack('f', 0.000010000) # default 0.000010000 (10E-06)
new_aging_compensation_list = struct.pack('f', 0.000000000) # default 0.000000000
new_max_freq_ramp_rate_list = struct.pack('f', 0.000010000) # default 0.000010000 (1.00E-05)


def error_status(flag):
    if (flag==7):
        error_status = "good"
    else:
        error_status = "ERROR"
    return error_status

def stability_status(flag):
    if (flag==1):
        stability_status = "stabilized"
    else:
        stability_status = "unstabilized"
    return stability_status


def main():
    part_num_str = ''.join([chr(item) for item in bus.read_i2c_block_data(address, 0x50, 32)])

    nomfreq_str = ''.join([chr(item) for item in bus.read_i2c_block_data(address, 0x52, 32)])

    lot_sn_str = ''.join([chr(item) for item in bus.read_i2c_block_data(address, 0x56, 32)])
    fab_date_str = ''.join([chr(item) for item in bus.read_i2c_block_data(address, 0x57, 32)])

    pull_value_float = struct.unpack('f', bytes(bus.read_i2c_block_data(address, 0x61, 4)))
    pull_range_float = struct.unpack('f', bytes(bus.read_i2c_block_data(address, 0x62, 4)))
    aging_compensation_float = struct.unpack('f', bytes(bus.read_i2c_block_data(address, 0x63, 4)))
    max_freq_ramp_rate_float = struct.unpack('f', bytes(bus.read_i2c_block_data(address, 0x64, 4)))

    uptime_uint = struct.unpack('I', bytes(bus.read_i2c_block_data(address, 0xA0, 4)))
    temperature_float = struct.unpack('f', bytes(bus.read_i2c_block_data(address, 0xA1, 4)))

    supply_voltage_float = struct.unpack('f', bytes(bus.read_i2c_block_data(address, 0xA3, 4)))

    heater_power_float = struct.unpack('f', bytes(bus.read_i2c_block_data(address, 0xA7, 4)))

    total_offset_written_float = struct.unpack('f', bytes(bus.read_i2c_block_data(address, 0xAB, 4)))

    error_status_flag_uint = struct.unpack('I', bytes(bus.read_i2c_block_data(address, 0xAE, 4)))
    stability_flag_uint = struct.unpack('I', bytes(bus.read_i2c_block_data(address, 0xAF, 4)))
    temperature_err_float = struct.unpack('f', bytes(bus.read_i2c_block_data(address, 0xB0, 4)))
    heater_power_target_float = struct.unpack('f', bytes(bus.read_i2c_block_data(address, 0xB1, 4)))

    error_status_str = error_status(int(''.join([str(item) for item in error_status_flag_uint])))
    stability_status_str = stability_status(int(''.join([str(item) for item in stability_flag_uint])))

    print("Part Number          ", part_num_str)
    print("Nominal frequency    ", nomfreq_str)
    print("Lot-SN               ", lot_sn_str)
    print("Fabrication          ", fab_date_str)
    print()
    print("Uptime                {:8d}s, {}".format(
        int(''.join([str(item) for item in uptime_uint])),
        str(datetime.timedelta(seconds=int(''.join([str(item) for item in uptime_uint]))))))
    print()
    print("Error status flag    ", error_status_str)
    print("stability flag       ", stability_status_str)
    print()
    print("Pull Value            {:=+.8g} ppm".format(float(''.join([str(item) for item in pull_value_float])) / pow(10, -6)))
    print("Pull Range             {:=.8g} ppm".format(float(''.join([str(item) for item in pull_range_float])) / pow(10, -6)))
    print("Aging compensation    {:=+.8g} ppm".format(float(''.join([str(item) for item in aging_compensation_float])) / pow(10, -6)))
    print("Max. Freq Ramp Rate    {:=.8g} ppm".format(float(''.join([str(item) for item in max_freq_ramp_rate_float])) / pow(10, -6)))
    print()
    print("Total offset written  {:=+.8g} ppm".format(float(''.join([str(item) for item in total_offset_written_float])) / pow(10, -6)))

    bus.write_i2c_block_data(address, 0x61, list(new_pull_value_list))
    bus.write_i2c_block_data(address, 0x62, list(new_pull_range_list))
    bus.write_i2c_block_data(address, 0x63, list(new_aging_compensation_list))
    bus.write_i2c_block_data(address, 0x64, list(new_max_freq_ramp_rate_list))

    pull_value_float = struct.unpack('f', bytes(bus.read_i2c_block_data(address, 0x61, 4)))
    pull_range_float = struct.unpack('f', bytes(bus.read_i2c_block_data(address, 0x62, 4)))
    aging_compensation_float = struct.unpack('f', bytes(bus.read_i2c_block_data(address, 0x63, 4)))
    max_freq_ramp_rate_float = struct.unpack('f', bytes(bus.read_i2c_block_data(address, 0x64, 4)))

    total_offset_written_float = struct.unpack('f', bytes(bus.read_i2c_block_data(address, 0xAB, 4)))

    error_status_flag_uint = struct.unpack('I', bytes(bus.read_i2c_block_data(address, 0xAE, 4)))
    error_status_str = error_status(int(''.join([str(item) for item in error_status_flag_uint])))

    print()
    print("--- Updated:")
    print("Error status flag    ", error_status_str)
    print("Pull Value            {:=+.8g} ppm".format(float(''.join([str(item) for item in pull_value_float])) / pow(10, -6)))
    print("Pull Range             {:=.8g} ppm".format(float(''.join([str(item) for item in pull_range_float])) / pow(10, -6)))
    print("Aging compensation    {:=+.8g} ppm".format(float(''.join([str(item) for item in aging_compensation_float])) / pow(10, -6)))
    print("Max. Freq Ramp Rate    {:=.8g} ppm".format(float(''.join([str(item) for item in max_freq_ramp_rate_float])) / pow(10, -6)))
    print()
    print("Total offset written  {:=+.8g} ppm".format(float(''.join([str(item) for item in total_offset_written_float])) / pow(10, -6)))


if __name__ == "__main__":
    main()
