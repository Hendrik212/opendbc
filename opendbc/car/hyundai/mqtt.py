"""
MQTT Data Extraction for Hyundai Ioniq 6

Verified CAN Messages:
- 0x3b5 (Bus 1): Complete vehicle metrics in one message!
  * Byte 16: Range - Direct km value
  * Byte 22: Battery SOC - Divide by 3 for percentage
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

    Ioniq 6 data from message 0x3b5 (Bus 1):
    - Byte 16: Range in km (direct value)
    - Byte 22: SOC percentage (divide by 3)

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

            # Message 0x3b5: Complete vehicle metrics (Bus 1)
            # This single message contains both SOC and range!
            if address == 0x3b5 and msg_bus == 1:
                if len(data) >= 23:
                    # Byte 16: Range in kilometers (direct value)
                    range_km = data[16]
                    range_out = range_km

                    # Byte 22: Battery SOC (divide by 3 for percentage)
                    # Example: 106 / 3 = 35.3%
                    soc_byte = data[22]
                    soc_out = soc_byte / 3.0

            # Store raw data for debugging
            dat[address] = data

