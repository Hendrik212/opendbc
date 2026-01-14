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

  * Bytes 22-23: Charging time remaining (16-bit little-endian, minutes)
    - Example: 0x0582 (1410) = 1410 minutes = 23.5 hours
    - Verified progression: 1410 -> 1400 -> 1380 -> 1350 -> 1320 -> 1270 minutes (decreasing as expected)

  * Bytes 24-25: Charging connector status (16-bit little-endian)
    - Non-zero (e.g., 0x026C = 620) = Connector plugged in
    - 0x0000 (0) = Connector not connected
    - Reliable regardless of charging port door state or car sleep/wake state

- 0x2b5 (693, Bus 1): Estimated Range
  * Bytes 8-9: Range in kilometers (16-bit little-endian, direct value)
    - Verified progression during charging: 129 -> 130 -> 131 -> 132 -> 136 -> 142 -> 144 -> 160 km
    - Monotonically increasing (never drops) - cleanest signal
    - Example: 0x81 0x00 = 129 km, 0xA0 0x00 = 160 km

Note: Charging status is now derived from charging power (voltage * current).
      If charging_power_out > 0, status is "active", otherwise "idle".
"""

import cereal.messaging as messaging
import time

# Debug flag: Enable raw message publishing for connector bit detection
DEBUG_RAW_MESSAGES = True

# Output metrics - initialized to sentinel values
soc_out = -1.0
range_out = -1
pack_voltage_out = -1.0
charging_current_out = -1.0
charging_power_out = -1.0
charging_time_remaining_out = -1
charging_status_out = "unknown"
connector_connected_out = False

# Raw message tracking for debug publishing
_prev_0x2fa = None
_prev_0x2b5 = None
_last_debug_publish_time = 0
_DEBUG_PUBLISH_INTERVAL = 10.0  # seconds

# CAN bus configuration
sendcan = messaging.pub_sock('sendcan')


def _bytes_to_hex(data):
    """Convert byte array to hex string (e.g., [72, 16, 79] -> '48104F')"""
    return ''.join(f'{b:02X}' for b in data)


def getParsedMessages(msgs, bus, dat, pm=None):
    """
    Main parser function called by status.py to extract CAN data.

    Hyundai Ioniq 6 verified metrics:
    - 0x2fa (762): SOC, pack voltage, charging current, charging time remaining
    - 0x2b5 (693): Range, charging status flag

    Args:
        msgs: List of CAN messages from cereal
        bus: CAN bus number (ignored - we check all buses)
        dat: Dictionary to store parsed data
        pm: Optional PubMaster for MQTT publishing (required for debug mode)
    """
    global soc_out, range_out, pack_voltage_out, charging_current_out
    global charging_power_out, charging_time_remaining_out, charging_status_out
    global connector_connected_out
    global _prev_0x2fa, _prev_0x2b5, _last_debug_publish_time

    # Track current messages for debug publishing
    current_0x2fa = None
    current_0x2b5 = None

    for msg in msgs:
        if msg.which() != 'can':
            continue

        for can_msg in msg.can:
            address = can_msg.address
            data = can_msg.dat
            msg_bus = can_msg.src

            # Message 0x2fa (762): Battery SOC and Charging Metrics (Bus 1)
            if address == 0x2fa and msg_bus == 1:
                # Track raw message for debug publishing
                current_0x2fa = bytes(data)

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

                    # Bytes 22-23: Charging time remaining (16-bit little-endian, direct minutes)
                    # Example: 0x0582 (1410) = 1410 minutes
                    charging_time_remaining_out = data[22] | (data[23] << 8)

                    # Bytes 24-25: Charging connector status (16-bit little-endian)
                    # Non-zero = connector plugged in, 0 = not connected
                    connector_raw = data[24] | (data[25] << 8)
                    connector_connected_out = (connector_raw > 0)

                    # Calculate charging power (voltage * current), convert W to kW
                    if pack_voltage_out > 0 and charging_current_out > 0:
                        charging_power_out = (pack_voltage_out * charging_current_out) / 1000.0
                    else:
                        charging_power_out = -1.0

                    # Determine charging status based on charging power
                    # If power > 0, the car is actively charging
                    charging_status_out = "active" if charging_power_out > 0 else "idle"

            # Message 0x2b5 (693): Estimated Range (Bus 1)
            if address == 0x2b5 and msg_bus == 1:
                # Track raw message for debug publishing
                current_0x2b5 = bytes(data)

                if len(data) >= 10:
                    # Bytes 8-9: Range in kilometers (16-bit little-endian, direct value)
                    # Example: 0x81 0x00 = 129 km, 0xA0 0x00 = 160 km
                    range_km = data[8] | (data[9] << 8)
                    range_out = range_km

            # Store raw data for debugging
            dat[address] = data

    # Debug mode: Publish raw messages when they change (rate-limited)
    if DEBUG_RAW_MESSAGES and pm is not None:
        current_time = time.time()

        # Check if either message changed
        msg_changed = False
        if current_0x2fa is not None and current_0x2fa != _prev_0x2fa:
            msg_changed = True
            _prev_0x2fa = current_0x2fa
        if current_0x2b5 is not None and current_0x2b5 != _prev_0x2b5:
            msg_changed = True
            _prev_0x2b5 = current_0x2b5

        # Publish if changed and rate limit allows
        if msg_changed and (current_time - _last_debug_publish_time) >= _DEBUG_PUBLISH_INTERVAL:
            from openpilot.system.mqttd import mqttd

            debug_data = {}
            if _prev_0x2fa is not None:
                debug_data["0x2fa"] = _bytes_to_hex(_prev_0x2fa)
            if _prev_0x2b5 is not None:
                debug_data["0x2b5"] = _bytes_to_hex(_prev_0x2b5)
            debug_data["timestamp"] = int(current_time)

            mqttd.publish(pm, "openpilot/car_debug/raw_messages", debug_data)
            _last_debug_publish_time = current_time

