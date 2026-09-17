"""
Fork-specific CAN steer limits for Hyundai, kept out of the stock CarControllerParams.

opendbc/car/hyundai/values.py calls apply_lat_tune_canfd_limits() and is otherwise
untouched by the tune, so the stock file stays close to its own upstream.
"""
import numpy as np

from opendbc.sunnypilot.car.hyundai.values import HyundaiFlagsSP

# Rate-limit schedule for the StarPilot CANFD tune. torqued fits the *applied* torque, so
# rate limiting adds lag but no gain error, and the fit is unaffected -- this is free to
# extend well past torqued's 15 m/s MIN_VEL. The 193-vs-194 A/B measured rate-limit
# saturation at 54-70 km/h falling 44% -> 3% of curve frames with no tracking cost, so we
# ramp rather than StarPilot's hard step at 15 m/s. Back to 2/3 by 19.4 m/s = 70 km/h.
CANFD_STEER_RATE_SPEED_BP = [17., 19.4]  # m/s
CANFD_STEER_DELTA_UP_V = [10, 2]
CANFD_STEER_DELTA_DOWN_V = [8, 3]

# StarPilot CANFD: flat 409 rail at every speed (opendbc/car/hyundai/values.py). A
# speed-scheduled 650 mid-band was a fork experiment; it is reverted. panda safety
# may still allow 650 -- that is an envelope, not the command.
STARPILOT_STEER_MAX = 409
STARPILOT_STEER_DRIVER_ALLOWANCE = 75    # StarPilot ships 100; softened per request
STARPILOT_STEER_DRIVER_MULTIPLIER = 2
STARPILOT_STEER_THRESHOLD = 100


def steer_max_for_speed(v_ego: float) -> int:
  return STARPILOT_STEER_MAX


def lat_accel_factor_for_speed(v_ego: float, base_factor: float) -> float:
  """Identity at the StarPilot rail: STEER_MAX is 409 at every speed."""
  return base_factor * steer_max_for_speed(v_ego) / STARPILOT_STEER_MAX


def friction_for_speed(v_ego: float, base_friction: float) -> float:
  """Identity at the StarPilot rail: STEER_MAX is 409 at every speed."""
  return base_friction * STARPILOT_STEER_MAX / steer_max_for_speed(v_ego)


# Flat limits for v3 (testing): stock v1 control law under high authority. 650 STEER_MAX
# and 10/8 rate across the whole speed band -- no speed schedule. The StarPilot rate ramp
# and STEER_MAX schedule are deliberately absent: this isolates v1's control behaviour.
V3_STEER_MAX = 650
V3_STEER_DELTA_UP = 10
V3_STEER_DELTA_DOWN = 8
V3_STEER_DRIVER_ALLOWANCE = 75
V3_STEER_DRIVER_MULTIPLIER = 2
V3_STEER_THRESHOLD = 100


def apply_lat_tune_canfd_limits(params, CP_SP, v_ego_raw: float) -> bool:
  """Apply the fork's CAN FD steer limits in place. Returns False if no fork tune is
  selected, in which case the caller applies the upstream limits verbatim."""
  if CP_SP is None:
    return False

  if CP_SP.flags & HyundaiFlagsSP.LAT_TUNE_V3:
    # v3: flat 650/10/8, no speed schedule.
    params.STEER_MAX = V3_STEER_MAX
    params.STEER_DRIVER_ALLOWANCE = V3_STEER_DRIVER_ALLOWANCE
    params.STEER_DRIVER_MULTIPLIER = V3_STEER_DRIVER_MULTIPLIER
    params.STEER_THRESHOLD = V3_STEER_THRESHOLD
    params.STEER_DELTA_UP = V3_STEER_DELTA_UP
    params.STEER_DELTA_DOWN = V3_STEER_DELTA_DOWN
    return True

  if not (CP_SP.flags & HyundaiFlagsSP.LAT_TUNE_STARPILOT):
    return False

  params.STEER_MAX = steer_max_for_speed(v_ego_raw)
  params.STEER_DRIVER_ALLOWANCE = STARPILOT_STEER_DRIVER_ALLOWANCE
  params.STEER_DRIVER_MULTIPLIER = STARPILOT_STEER_DRIVER_MULTIPLIER
  params.STEER_THRESHOLD = STARPILOT_STEER_THRESHOLD
  params.STEER_DELTA_UP = int(round(np.interp(v_ego_raw, CANFD_STEER_RATE_SPEED_BP, CANFD_STEER_DELTA_UP_V)))
  params.STEER_DELTA_DOWN = int(round(np.interp(v_ego_raw, CANFD_STEER_RATE_SPEED_BP, CANFD_STEER_DELTA_DOWN_V)))
  return True
