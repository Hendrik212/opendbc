"""
MQTT Data Extraction for Hyundai Ioniq 6

✅ VERIFIED CAN Messages (captured during charging session 24% -> 31%, 129km -> 164km):

- 0x2fa (762, Bus 1): Battery SOC and Charging Metrics
  * Byte 15: Battery SOC - Divide by 2 for percentage (0.5% resolution)
    - Example: 48 / 2 = 24.0%, 61 / 2 = 30.5%
    - Verified progression: 24.0% -> 24.5% -> 25.0% -> 25.5% -> 26.0% -> 26.5% -> 28.0% -> 28.5% -> 29.0% -> 30.5%

  * Bytes 4-5: Pack voltage (16-bit little-endian, 0.1V resolution)
    - Example: 0x104F (4175) * 0.1 = 417.5V
    - Verified range: 417.5V - 417.6V during AC charging

  * Bytes 8-9: Charging current (16-bit little-endian signed, 0.4A resolution)
    - Negative values in CAN indicate charging current
    - Example: 0xFFE8 (-24) * -0.4 = 9.6A charging
    - Corrected resolution to match actual charging power measurements

  * Bytes 24-25: Charging time remaining (16-bit little-endian, minutes)
    - Example: 0x0582 (1410) = 1410 minutes = 23.5 hours
    - Verified progression: 1410 -> 1400 -> 1380 -> 1350 -> 1320 -> 1270 minutes (decreasing as expected)

- 0x2b5 (693, Bus 1): Estimated Range and Charging Status
  * Bytes 8-9: Range in kilometers (16-bit little-endian, direct value)
    - Verified progression during charging: 129 -> 130 -> 131 -> 132 -> 136 -> 142 -> 144 -> 160 km
    - Monotonically increasing (never drops) - cleanest signal
    - Example: 0x81 0x00 = 129 km, 0xA0 0x00 = 160 km

  * Byte 4 bit 0: Charging status flag
    - Bit = 1: Charging handshake/idle
    - Bit = 0: Charging active
"""

import cereal.messaging as messaging

# Output metrics - initialized to sentinel values
soc_out = -1.0
range_out = -1
pack_voltage_out = -1.0
charging_current_out = -1.0
charging_power_out = -1.0
charging_time_remaining_out = -1
charging_status_out = "unknown"

# CAN bus configuration
sendcan = messaging.pub_sock('sendcan')


def getParsedMessages(msgs, bus, dat):
    """
    Main parser function called by status.py to extract CAN data.

    Hyundai Ioniq 6 verified metrics:
    - 0x2fa (762): SOC, pack voltage, charging current, charging time remaining
    - 0x2b5 (693): Range, charging status flag

    Args:
        msgs: List of CAN messages from cereal
        bus: CAN bus number (ignored - we check all buses)
        dat: Dictionary to store parsed data
    """
    global soc_out, range_out, pack_voltage_out, charging_current_out
    global charging_power_out, charging_time_remaining_out, charging_status_out

    for msg in msgs:
        if msg.which() != 'can':
            continue

        for can_msg in msg.can:
            address = can_msg.address
            data = can_msg.dat
            msg_bus = can_msg.src

            # Message 0x2fa (762): Battery SOC and Charging Metrics (Bus 1)
            if address == 0x2fa and msg_bus == 1:
                if len(data) >= 26:
                    # Byte 15: Battery SOC (divide by 2 for percentage, 0.5% resolution)
                    # Example: 48 / 2 = 24.0%, 61 / 2 = 30.5%
                    soc_byte = data[15]
                    soc_out = soc_byte / 2.0

                    # Bytes 4-5: Pack voltage (16-bit little-endian, 0.1V resolution)
                    # Example: 0x104F (4175) * 0.1 = 417.5V
                    voltage_raw = data[4] | (data[5] << 8)
                    pack_voltage_out = voltage_raw * 0.1

                    # Bytes 8-9: Charging current (16-bit little-endian signed, 0.4A resolution)
                    # Negative values in CAN = charging current, convert to positive
                    # Example: 0xFFE8 (-24) * -0.4 = 9.6A
                    current_raw = data[8] | (data[9] << 8)
                    # Convert to signed 16-bit
                    if current_raw > 32767:
                        current_raw -= 65536
                    charging_current_out = current_raw * -0.4

                    # Bytes 24-25: Charging time remaining (16-bit little-endian, direct minutes)
                    # Example: 0x0582 (1410) = 1410 minutes
                    charging_time_remaining_out = data[24] | (data[25] << 8)

                    # Calculate charging power (voltage * current), convert W to kW
                    if pack_voltage_out > 0 and charging_current_out > 0:
                        charging_power_out = (pack_voltage_out * charging_current_out) / 1000.0
                    else:
                        charging_power_out = -1.0

            # Message 0x2b5 (693): Estimated Range and Charging Status (Bus 1)
            if address == 0x2b5 and msg_bus == 1:
                if len(data) >= 10:
                    # Bytes 8-9: Range in kilometers (16-bit little-endian, direct value)
                    # Example: 0x81 0x00 = 129 km, 0xA0 0x00 = 160 km
                    range_km = data[8] | (data[9] << 8)
                    range_out = range_km

                    # Byte 4 bit 0: Charging status flag
                    # Bit = 1: Charging handshake/idle, Bit = 0: Charging active
                    charging_flag = data[4] & 0x01
                    charging_status_out = "idle" if charging_flag == 1 else "active"

            # Store raw data for debugging
            dat[address] = data

