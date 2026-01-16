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

- 0x2b5 (693, Bus 1): Estimated Range
  * Bytes 8-9: Range in kilometers (16-bit little-endian, direct value)
    - Verified progression during charging: 129 -> 130 -> 131 -> 132 -> 136 -> 142 -> 144 -> 160 km
    - Monotonically increasing (never drops) - cleanest signal
    - Example: 0x81 0x00 = 129 km, 0xA0 0x00 = 160 km

- 0x035 (53, Bus 1): Connector Status
  * Byte 16, bit 2: Charging connector plugged status
    - 0x06 (bit 2 set) = Connector plugged in
    - 0x02 (bit 2 clear) = Connector not connected
    - Verified across 3 plug/unplug cycles - reliable indicator

Note: Charging status is now derived from charging power (voltage * current).
      If charging_power_out > 0, status is "active", otherwise "idle".
"""

import cereal.messaging as messaging
import time
from panda import Panda
from opendbc.car.structs import CarParams

# Debug flag: Enable raw message publishing for connector bit detection
DEBUG_RAW_MESSAGES = True

# Discovery mode: Scan Bus 1 for all active message IDs
DISCOVERY_MODE = True

# Message scanner mode: Capture full content of all discovered messages
MESSAGE_SCANNER_MODE = True

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

# Discovery mode tracking
_discovered_messages = {}  # {address: {"count": int, "first_seen": float}}
_last_discovery_publish_time = 0
_DISCOVERY_PUBLISH_INTERVAL = 30.0  # seconds

# Message scanner tracking
_message_scanner_content = {}  # {address: bytes}
_prev_scanner_content = {}  # {address: bytes} - previous published state
_last_scanner_publish_time = 0
_SCANNER_PUBLISH_INTERVAL = 10.0  # seconds

# UDS Tester Present service type
UDS_TESTER_PRESENT = 0x3E

# Wake CAN bus addresses for Hyundai CAN FD
# Try multiple ECU addresses to wake various systems
WAKE_ADDRESSES = [
    0x7df,  # OBD2 functional broadcast - reaches ALL ECUs
    0x7e4,  # BMS (Battery Management System) - common Hyundai address
    0x7e2,  # OBD/Powertrain ECU
    0x7d0,  # ADAS ECU
    0x7b1,  # Body ECU
    0x7c4,  # Instrument cluster
]
# Try both buses - ECAN (0) and ACAN (1) for CAN FD
WAKE_BUSES = [0, 1]

# UDS Services to try
UDS_READ_DATA_BY_ID = 0x22  # Read Data By Identifier
UDS_DIAGNOSTIC_SESSION = 0x10  # Diagnostic Session Control


def wakeCanBus():
    """
    Send UDS Tester Present messages to wake the CAN bus.

    Uses Panda with SAFETY_ALLOUTPUT to bypass normal safety restrictions.
    Sends to multiple ECU addresses on both ECAN (bus 0) and ACAN (bus 1).

    Returns True if messages were sent successfully, False otherwise.
    """
    import traceback
    try:
        with open("/tmp/wake_debug.log", "a") as f:
            f.write("wakeCanBus called\n")
        print("[MQTT] Connecting to Panda for wake...", flush=True)
        panda = Panda()
        with open("/tmp/wake_debug.log", "a") as f:
            f.write("Panda connected\n")
        panda.set_safety_mode(CarParams.SafetyModel.allOutput)
        with open("/tmp/wake_debug.log", "a") as f:
            f.write("Safety mode set to ALLOUTPUT\n")
        print("[MQTT] Panda connected, safety mode set to ALLOUTPUT", flush=True)

        for bus in WAKE_BUSES:
            for addr in WAKE_ADDRESSES:
                # Try multiple UDS services to maximize wake chance

                # 1. Diagnostic Session Control - Default Session (0x01)
                # This often wakes ECUs that are in sleep mode
                dat_session = bytes([0x02, UDS_DIAGNOSTIC_SESSION, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00])
                for _ in range(20):
                    panda.can_send(addr, dat_session, bus)

                # 2. Tester Present with suppress response
                dat_tester = bytes([0x02, UDS_TESTER_PRESENT, 0x80, 0x00, 0x00, 0x00, 0x00, 0x00])
                for _ in range(20):
                    panda.can_send(addr, dat_tester, bus)

                # 3. Read Data By ID - try reading SOC (common PID F45B for Hyundai EVs)
                dat_read = bytes([0x03, UDS_READ_DATA_BY_ID, 0xF4, 0x5B, 0x00, 0x00, 0x00, 0x00])
                for _ in range(10):
                    panda.can_send(addr, dat_read, bus)

                with open("/tmp/wake_debug.log", "a") as f:
                    f.write(f"Sent wake sequence to 0x{addr:03x} on bus {bus}\n")
                print(f"[MQTT] Sent wake sequence to 0x{addr:03x} on bus {bus}", flush=True)

        return True
    except Exception as e:
        with open("/tmp/wake_debug.log", "a") as f:
            f.write(f"EXCEPTION: {e}\n")
            f.write(traceback.format_exc())
        print(f"[MQTT] Wake CAN bus failed: {e}", flush=True)
        return False


def _bytes_to_hex(data):
    """Convert byte array to hex string (e.g., [72, 16, 79] -> '48104F')"""
    return ''.join(f'{b:02X}' for b in data)


def getParsedMessages(msgs, bus, dat, pm=None):
    """
    Main parser function called by status.py to extract CAN data.

    Hyundai Ioniq 6 verified metrics:
    - 0x2fa (762): SOC, pack voltage, charging current, charging time remaining
    - 0x2b5 (693): Range
    - 0x035 (53): Connector plugged status

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
    global _discovered_messages, _last_discovery_publish_time
    global _message_scanner_content, _prev_scanner_content, _last_scanner_publish_time

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

            # Discovery mode: Track all Bus 1 message IDs
            if DISCOVERY_MODE and msg_bus == 1:
                current_time = time.time()
                if address not in _discovered_messages:
                    _discovered_messages[address] = {
                        "count": 0,
                        "first_seen": current_time
                    }
                _discovered_messages[address]["count"] += 1

            # Message scanner mode: Capture full content of all Bus 1 messages
            if MESSAGE_SCANNER_MODE and msg_bus == 1:
                _message_scanner_content[address] = bytes(data)

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

                    # Bytes 24-25: Charging time remaining (16-bit little-endian, direct minutes)
                    # Example: 0x0582 (1410) = 1410 minutes
                    charging_time_remaining_out = data[24] | (data[25] << 8)

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

            # Message 0x035 (53): Connector Status (Bus 1)
            if address == 0x035 and msg_bus == 1:
                if len(data) >= 17:
                    # Byte 16, bit 2: Connector plugged status
                    # 0x06 (bit 2 set) = Plugged, 0x02 (bit 2 clear) = Unplugged
                    # Verified across 3 plug/unplug cycles
                    connector_connected_out = (data[16] & 0x04) != 0

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

    # Discovery mode: Publish discovered message IDs periodically
    if DISCOVERY_MODE and pm is not None:
        current_time = time.time()
        if (current_time - _last_discovery_publish_time) >= _DISCOVERY_PUBLISH_INTERVAL:
            from openpilot.system.mqttd import mqttd

            # Format discovered IDs as hex strings and sort by ID
            discovered_ids = sorted([f"0x{addr:03x}" for addr in _discovered_messages.keys()])

            # Build stats dictionary with hex IDs
            stats = {}
            for addr, data in _discovered_messages.items():
                hex_id = f"0x{addr:03x}"
                stats[hex_id] = {
                    "count": data["count"],
                    "first_seen": int(data["first_seen"])
                }

            discovery_data = {
                "bus": 1,
                "discovered_ids": discovered_ids,
                "stats": stats,
                "timestamp": int(current_time)
            }

            mqttd.publish(pm, "openpilot/car_debug/message_discovery", discovery_data)
            _last_discovery_publish_time = current_time

    # Message scanner mode: Publish all message contents when changed (rate-limited)
    if MESSAGE_SCANNER_MODE and pm is not None:
        current_time = time.time()

        # Check if any message content changed
        content_changed = False
        for addr, content in _message_scanner_content.items():
            if addr not in _prev_scanner_content or _prev_scanner_content[addr] != content:
                content_changed = True
                break

        # Publish if changed and rate limit allows
        if content_changed and (current_time - _last_scanner_publish_time) >= _SCANNER_PUBLISH_INTERVAL:
            from openpilot.system.mqttd import mqttd

            # Build messages dictionary with hex strings
            messages = {}
            for addr, content in _message_scanner_content.items():
                hex_id = f"0x{addr:03x}"
                messages[hex_id] = _bytes_to_hex(content)

            scanner_data = {
                "messages": messages,
                "timestamp": int(current_time)
            }

            mqttd.publish(pm, "openpilot/car_debug/message_scanner", scanner_data)
            _prev_scanner_content = _message_scanner_content.copy()
            _last_scanner_publish_time = current_time

