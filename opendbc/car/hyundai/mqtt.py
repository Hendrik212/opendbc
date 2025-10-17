"""
MQTT Data Extraction for Hyundai Ioniq 6

✅ VERIFIED CAN Messages (captured during charging session 24% -> 31%, 129km -> 164km):

- 0x2fa (762, Bus 1): Battery SOC AND Range - BOTH in ONE message!
  * Byte 15: Battery SOC - Divide by 2 for percentage (0.5% resolution)
    - Example: 48 / 2 = 24.0%, 61 / 2 = 30.5%
    - Verified progression: 24.0% -> 24.5% -> 25.0% -> 25.5% -> 26.0% -> 26.5% -> 28.0% -> 28.5% -> 29.0% -> 30.5%

  * Bytes 30-31: Estimated Range - 16-bit little-endian, divide by 4 (0.25 km resolution)
    - Example: 0x0223 (547) / 4 = 136.75 km, 0x029C (668) / 4 = 167.00 km
    - Verified progression: 136.75 -> 137.00 -> 138.00 -> 138.50 ... -> 167.00 km
    - Monotonically increasing, higher precision than 0x2b5
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

    Hyundai Ioniq 6 verified metrics - BOTH in one message!
    - 0x2fa (762) byte 15: SOC (divide by 2, 0.5% resolution)
    - 0x2fa (762) bytes 30-31: Range (16-bit LE, divide by 4, 0.25 km resolution)

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

            # Message 0x2fa (762): Battery SOC AND Range (Bus 1)
            # Single message contains both metrics!
            if address == 0x2fa and msg_bus == 1:
                if len(data) >= 32:
                    # Byte 15: Battery SOC (divide by 2 for percentage, 0.5% resolution)
                    # Example: 48 / 2 = 24.0%, 61 / 2 = 30.5%
                    soc_byte = data[15]
                    soc_out = soc_byte / 2.0

                    # Bytes 30-31: Estimated Range (16-bit little-endian, divide by 4, 0.25 km resolution)
                    # Little-endian: byte 30 is low byte, byte 31 is high byte
                    # Example: 0x0223 (547) / 4 = 136.75 km, 0x029C (668) / 4 = 167.00 km
                    range_raw = data[30] | (data[31] << 8)
                    range_out = range_raw / 4.0

            # Store raw data for debugging
            dat[address] = data

