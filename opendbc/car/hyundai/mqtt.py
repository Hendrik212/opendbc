"""
MQTT Data Extraction for Hyundai Ioniq 6

✅ VERIFIED CAN Messages (captured during charging session 24% -> 31%, 129km -> 164km):

- 0x2fa (762, Bus 1): Battery SOC
  * Byte 15: Battery SOC - Divide by 2 for percentage
  * Example: 48 / 2 = 24.0%, 61 / 2 = 30.5%
  * Verified progression: 24.0% -> 24.5% -> 25.0% -> 25.5% -> 26.0% -> 26.5% -> 28.0% -> 28.5% -> 29.0% -> 30.5%

- 0x2b5 (693, Bus 1): Estimated Range
  * Bytes 8-9: Range in kilometers (16-bit little-endian, direct value)
  * Verified progression during charging: 129 -> 130 -> 131 -> 132 -> 136 -> 142 -> 144 -> 160 km
  * Monotonically increasing (never drops) - cleanest signal
  * Example: 0x81 0x00 = 129 km, 0xA0 0x00 = 160 km
"""

import cereal.messaging as messaging

# Output metrics - initialized to sentinel values
soc_out = -1.0
range_out = -1

# CAN bus configuration
sendcan = messaging.pub_sock('sendcan')


def getParsedMessages(msgs, bus, dat):
    """
    Main parser function called by status.py to extract CAN data.

    Hyundai Ioniq 6 verified metrics:
    - 0x2fa (762) byte 15: SOC (divide by 2)
    - 0x2b5 (693) bytes 8-9: Range in km (16-bit little-endian)

    Args:
        msgs: List of CAN messages from cereal
        bus: CAN bus number (ignored - we check all buses)
        dat: Dictionary to store parsed data
    """
    global soc_out, range_out

    for msg in msgs:
        if msg.which() != 'can':
            continue

        for can_msg in msg.can:
            address = can_msg.address
            data = can_msg.dat
            msg_bus = can_msg.src

            # Message 0x2fa (762): Battery SOC (Bus 1)
            if address == 0x2fa and msg_bus == 1:
                if len(data) >= 16:
                    # Byte 15: Battery SOC (divide by 2 for percentage)
                    # Example: 48 / 2 = 24.0%, 61 / 2 = 30.5%
                    soc_byte = data[15]
                    soc_out = soc_byte / 2.0

            # Message 0x2b5 (693): Estimated Range (Bus 1)
            if address == 0x2b5 and msg_bus == 1:
                if len(data) >= 10:
                    # Bytes 8-9: Range in kilometers (16-bit little-endian)
                    # Little-endian: byte 8 is low byte, byte 9 is high byte
                    # Example: 0x81 0x00 = 129 km, 0xA0 0x00 = 160 km
                    range_km = data[8] | (data[9] << 8)
                    range_out = range_km

            # Store raw data for debugging
            dat[address] = data

