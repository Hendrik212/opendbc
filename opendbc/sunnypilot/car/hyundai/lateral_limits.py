"""
Fork-specific CAN steer limits for Hyundai, kept out of the stock CarControllerParams.

opendbc/car/hyundai/values.py calls apply_lat_tune_canfd_limits() and is otherwise
untouched by the tune, so the stock file stays close to its own upstream.
"""
import numpy as np

from opendbc.car.lateral import apply_driver_steer_torque_limits
from opendbc.sunnypilot.car.hyundai.values import HyundaiFlagsSP

# Rate-limit schedule for the StarPilot CANFD tune. torqued fits the *applied* torque, so
# rate limiting adds lag but no gain error, and the fit is unaffected -- this is free to
# extend well past torqued's 15 m/s MIN_VEL. The 193-vs-194 A/B measured rate-limit
# saturation at 54-70 km/h falling 44% -> 3% of curve frames with no tracking cost, so we
# ramp rather than StarPilot's hard step at 15 m/s. Back to 2/3 by 19.4 m/s = 70 km/h.
CANFD_STEER_RATE_SPEED_BP = [17., 19.4]  # m/s
CANFD_STEER_DELTA_UP_V = [10, 2]
CANFD_STEER_DELTA_DOWN_V = [8, 3]  # low-speed end is live: SteerDeltaDownLow (default 10)

# StarPilot CANFD: flat 409 rail at every speed (opendbc/car/hyundai/values.py). A
# speed-scheduled 650 mid-band was a fork experiment; it is reverted. panda safety
# may still allow 650 -- that is an envelope, not the command.
STARPILOT_STEER_MAX = 409
STARPILOT_STEER_DRIVER_ALLOWANCE = 75    # StarPilot ships 100; softened per request
STARPILOT_STEER_DRIVER_MULTIPLIER = 2
STARPILOT_STEER_THRESHOLD = 100


def steer_max_for_speed(v_ego: float) -> int:
  return STARPILOT_STEER_MAX


# Saturation-only headroom (2026-10-16, routes 236-238). In corners under 25 m radius the
# StarPilot rail sat on 409 for 86% of the time before the driver stepped in, reaching 0.74
# of the requested lateral accel; the driver then added 290-470 CAN in 90% of them, and that
# hand torque is most of the felt "slow unwind" (exits track 1.0 when hands-off). The torque
# SCALE stays 409 -- latAccelFactor/friction and every unsaturated command are unchanged --
# only the clip opens, between 18 and 55 km/h. Creep (< 18 km/h) keeps 409: with a flat
# 10 CAN/frame slew a taller rail lengthens the creep sawtooth (reverted Sep 1, e61b28a0).
# The Sep 1 650 band did the same with a scaled latAccelFactor (5.82), reverted Sep 18 on feel.
HEADROOM_SPEED_BP = [5.0, 6.5, 13.9, 15.3]  # m/s: 18 / 23.4 / 50 / 55 km/h
DEFAULT_HEADROOM_CAN = 600
DEFAULT_DELTA_DOWN_LOW = 10
PANDA_MAX_TORQUE = 650  # opendbc/safety/modes/hyundai_canfd.h max_torque
PANDA_MAX_RATE_DOWN = 10  # ... max_rate_down

_live = {"headroom_can": DEFAULT_HEADROOM_CAN, "delta_down_low": DEFAULT_DELTA_DOWN_LOW}


def set_live_limits(headroom_can, delta_down_low) -> None:
  """card's params thread: SteerHeadroomCan (<= 409 = off), SteerDeltaDownLow (8 = previous)."""
  try:
    _live["headroom_can"] = int(min(max(float(headroom_can), STARPILOT_STEER_MAX), PANDA_MAX_TORQUE))
  except (TypeError, ValueError):
    _live["headroom_can"] = DEFAULT_HEADROOM_CAN
  try:
    _live["delta_down_low"] = int(min(max(int(float(delta_down_low)), 1), PANDA_MAX_RATE_DOWN))
  except (TypeError, ValueError):
    _live["delta_down_low"] = DEFAULT_DELTA_DOWN_LOW


def headroom_ratio(v_ego: float, headroom_can: float | None = None) -> float:
  """Torque clip relative to the 409 scale (1.0 = no headroom)."""
  h = _live["headroom_can"] if headroom_can is None else headroom_can
  h = min(max(float(h), STARPILOT_STEER_MAX), PANDA_MAX_TORQUE) / STARPILOT_STEER_MAX
  return float(np.interp(v_ego, HEADROOM_SPEED_BP, [1.0, h, h, 1.0]))


def apply_headroom_driver_limits(apply_torque: int, apply_torque_last: int, driver_torque: float, P) -> int:
  """apply_driver_steer_torque_limits with the driver bound computed from the 409 scale, so
  a driver opposing openpilot is limited exactly as before; only an unopposed command may
  use the headroom clip (P.STEER_MAX)."""
  base, cap = P.STEER_SCALE, P.STEER_MAX
  if cap <= base:
    return apply_driver_steer_torque_limits(apply_torque, apply_torque_last, driver_torque, P)
  driver_max = base + (P.STEER_DRIVER_ALLOWANCE + driver_torque * P.STEER_DRIVER_FACTOR) * P.STEER_DRIVER_MULTIPLIER
  driver_min = -base + (-P.STEER_DRIVER_ALLOWANCE + driver_torque * P.STEER_DRIVER_FACTOR) * P.STEER_DRIVER_MULTIPLIER
  max_allowed = cap if driver_max >= base else max(driver_max, 0)
  min_allowed = -cap if driver_min <= -base else min(driver_min, 0)
  apply_torque = np.clip(apply_torque, min_allowed, max_allowed)
  if apply_torque_last > 0:
    apply_torque = np.clip(apply_torque, max(apply_torque_last - P.STEER_DELTA_DOWN, -P.STEER_DELTA_UP),
                           apply_torque_last + P.STEER_DELTA_UP)
  else:
    apply_torque = np.clip(apply_torque, apply_torque_last - P.STEER_DELTA_UP,
                           min(apply_torque_last + P.STEER_DELTA_DOWN, P.STEER_DELTA_UP))
  return int(round(float(apply_torque)))


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

  params.STEER_SCALE = steer_max_for_speed(v_ego_raw)
  params.STEER_MAX = int(round(params.STEER_SCALE * headroom_ratio(v_ego_raw)))
  params.STEER_DRIVER_ALLOWANCE = STARPILOT_STEER_DRIVER_ALLOWANCE
  params.STEER_DRIVER_MULTIPLIER = STARPILOT_STEER_DRIVER_MULTIPLIER
  params.STEER_THRESHOLD = STARPILOT_STEER_THRESHOLD
  params.STEER_DELTA_UP = int(round(np.interp(v_ego_raw, CANFD_STEER_RATE_SPEED_BP, CANFD_STEER_DELTA_UP_V)))
  params.STEER_DELTA_DOWN = int(round(np.interp(v_ego_raw, CANFD_STEER_RATE_SPEED_BP,
                                                [_live["delta_down_low"], CANFD_STEER_DELTA_DOWN_V[1]])))
  return True
