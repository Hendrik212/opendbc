import time

from opendbc.car.carlog import carlog
from opendbc.car.isotp_parallel_query import IsoTpParallelQuery

EXT_DIAG_REQUEST = b'\x10\x03'
EXT_DIAG_RESPONSE = b'\x50\x03'

COM_CONT_RESPONSE = b''

# Default delay after sending disable command to allow ECU to stop transmitting
DEFAULT_DISABLE_DELAY = 0.5


def disable_ecu(can_recv, can_send, bus=0, addr=0x7d0, sub_addr=None, com_cont_req=b'\x28\x83\x01', timeout=0.1, retry=10,
                verify_silence_addrs=None, verify_silence_timeout=1.5, post_disable_delay=None):
  """Silence an ECU by disabling sending and receiving messages using UDS 0x28.
  The ECU will stay silent as long as openpilot keeps sending Tester Present.

  This is used to disable the radar in some cars. Openpilot will emulate the radar.
  WARNING: THIS DISABLES AEB!"""
  carlog.warning(f"ecu disable {hex(addr), sub_addr} ...")

  for i in range(retry):
    try:
      query = IsoTpParallelQuery(can_send, can_recv, bus, [(addr, sub_addr)], [EXT_DIAG_REQUEST], [EXT_DIAG_RESPONSE])

      for _, _ in query.get_data(timeout).items():
        carlog.warning("communication control disable tx/rx ...")

        query = IsoTpParallelQuery(can_send, can_recv, bus, [(addr, sub_addr)], [com_cont_req], [COM_CONT_RESPONSE])
        query.get_data(0)

        carlog.warning("ecu disabled")

        # Verify ECU has stopped transmitting by monitoring specified addresses
        if verify_silence_addrs:
          carlog.warning(f"verifying ECU silence on addrs {[hex(a) for a in verify_silence_addrs]} ...")
          silence_verified = _verify_ecu_silence(can_recv, bus, verify_silence_addrs, verify_silence_timeout)
          if silence_verified:
            carlog.warning("ECU silence verified")
          else:
            carlog.warning(f"ECU silence verification timed out after {verify_silence_timeout}s, proceeding anyway")
        elif post_disable_delay is not None:
          carlog.warning(f"waiting {post_disable_delay}s for ECU to stop transmitting ...")
          time.sleep(post_disable_delay)
        else:
          carlog.warning(f"waiting {DEFAULT_DISABLE_DELAY}s for ECU to stop transmitting ...")
          time.sleep(DEFAULT_DISABLE_DELAY)

        return True

    except Exception:
      carlog.exception("ecu disable exception")

    carlog.error(f"ecu disable retry ({i + 1}) ...")
  carlog.error("ecu disable failed")
  return False


def _verify_ecu_silence(can_recv, bus, addrs, timeout):
  """Wait until no messages from specified addresses are seen for a short period."""
  silence_duration = 0.3
  check_interval = 0.02

  start_time = time.monotonic()
  last_message_time = start_time

  while time.monotonic() - start_time < timeout:
    packets = can_recv()
    message_seen = False

    for pkt in packets:
      for msg in pkt:
        if msg.src == bus and msg.address in addrs:
          message_seen = True
          last_message_time = time.monotonic()
          break
      if message_seen:
        break

    if time.monotonic() - last_message_time >= silence_duration:
      return True

    time.sleep(check_interval)

  return False
