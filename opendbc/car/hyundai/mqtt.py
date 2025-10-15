"""
MQTT Data Extraction for Hyundai Ioniq 6

Verified CAN Messages:
- 0x100 (Bus 0): Battery SOC - Byte 20, divide by 3 for percentage
- 0x3b5 (Bus 1): Range - Byte 16, direct km value
"""

import cereal.messaging as messaging
from opendbc.can.packer import CANPacker
from openpilot.selfdrive.pandad import can_list_to_can_capnp
from panda.python import Panda

# Output metrics - initialized to sentinel values
soc_out = -1.0
range_out = -1

# CAN bus configuration
sendcan = messaging.pub_sock('sendcan')
dbc_name = 'hyundai_canfd'  # Ioniq 6 uses CAN FD
packer = CANPacker(dbc_name)


def getParsedMessages(msgs, bus, dat):
    """
    Main parser function called by status.py to extract CAN data.

    Ioniq 6 has relevant data on MULTIPLE buses:
    - Bus 0: Message 0x100 (SOC)
    - Bus 1: Message 0x3b5 (Range)

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

            # Message 0x100: Battery SOC (Bus 0, Byte 20, divide by 3)
            if address == 0x100 and msg_bus == 0:
                if len(data) >= 21:
                    soc_byte = data[20]
                    soc_out = soc_byte / 3.0

            # Message 0x3b5: Range (Bus 1, Byte 16, direct km value)
            if address == 0x3b5 and msg_bus == 1:
                if len(data) >= 17:
                    range_km = data[16]
                    range_out = range_km

            # Store raw data for debugging
            dat[address] = data

