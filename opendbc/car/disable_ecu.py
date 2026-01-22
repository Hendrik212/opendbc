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
  WARNING: THIS DISABLES AEB!

  Args:
    can_recv: CAN receive callback
    can_send: CAN send callback
    bus: CAN bus number
    addr: ECU diagnostic address
    sub_addr: ECU sub-address (if applicable)
    com_cont_req: Communication control request bytes
    timeout: Timeout for each UDS query attempt
    retry: Number of retry attempts
    verify_silence_addrs: List of CAN addresses to monitor for silence after disable.
                          If provided, will wait until no messages from these addresses are seen.
    verify_silence_timeout: Max time to wait for ECU silence verification (seconds)
    post_disable_delay: Fixed delay after disable command (seconds). If None, uses DEFAULT_DISABLE_DELAY
                        when verify_silence_addrs is not provided.

  Returns:
    True if ECU was successfully disabled, False otherwise
  """
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
          # Use explicit delay if provided
          carlog.warning(f"waiting {post_disable_delay}s for ECU to stop transmitting ...")
          time.sleep(post_disable_delay)
        else:
          # Default delay when no verification is requested
          carlog.warning(f"waiting {DEFAULT_DISABLE_DELAY}s for ECU to stop transmitting ...")
          time.sleep(DEFAULT_DISABLE_DELAY)

        return True

    except Exception:
      carlog.exception("ecu disable exception")

    carlog.error(f"ecu disable retry ({i + 1}) ...")
  carlog.error("ecu disable failed")
  return False


def _verify_ecu_silence(can_recv, bus, addrs, timeout):
  """Wait until no messages from specified addresses are seen for a short period.

  Args:
    can_recv: CAN receive callback
    bus: CAN bus to monitor
    addrs: List of CAN addresses to check for silence
    timeout: Maximum time to wait for silence

  Returns:
    True if silence was verified, False if timeout reached while still seeing messages
  """
  silence_duration = 0.3  # How long we need to see no messages to consider ECU silent
  check_interval = 0.02   # How often to check for messages

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

    # Check if we've had enough silence
    if time.monotonic() - last_message_time >= silence_duration:
      return True

    time.sleep(check_interval)

  return False
