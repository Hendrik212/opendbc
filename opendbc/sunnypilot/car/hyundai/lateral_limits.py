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

# Speed-scheduled STEER_MAX. carcontroller computes `torque * STEER_MAX`, so this is also
# the plant gain unless latAccelFactor is scaled with it (see lat_accel_factor_for_speed).
#
# Route 000001a4 tight corners at CAN 409: desired 2.91 vs actual 2.35; linear CAN to match
# was p50=509 / p90=625. 600 covers the median and most of p90. Unsaturated mapping is kept
# at the StarPilot 409/3.66 = 112 CAN per m/s^2 by scheduling latAccelFactor with STEER_MAX
# in the controller profile.
#
# 0-10 km/h (2.8 m/s) stays 409: that band rails on P/LSF with small |dLA|, and a taller
# rail is a bigger sawtooth, not more path. 600 is in by 4 m/s (14 km/h), before the
# 22-48 km/h corners that were torque-limited, and back to 409 by 17 m/s (before the
# 70 km/h weave and the rate ramp). Panda max_torque must match the peak (hyundai_canfd.h).
CANFD_STEER_MAX_SPEED_BP = [2.8, 4.0, 15.0, 17.0]  # m/s
STARPILOT_STEER_MAX_V = [409, 600, 600, 409]
STARPILOT_STEER_MAX_REF = 409  # StarPilot / unsaturated-gain reference
STARPILOT_STEER_MAX = 600  # panda envelope / worst case
STARPILOT_STEER_DRIVER_ALLOWANCE = 75    # StarPilot ships 100; softened per request
STARPILOT_STEER_DRIVER_MULTIPLIER = 2
STARPILOT_STEER_THRESHOLD = 100


def steer_max_for_speed(v_ego: float) -> int:
  return int(round(np.interp(v_ego, CANFD_STEER_MAX_SPEED_BP, STARPILOT_STEER_MAX_V)))


def lat_accel_factor_for_speed(v_ego: float, base_factor: float) -> float:
  """Keep CAN per m/s^2 constant as STEER_MAX changes: torque*STEER_MAX / (lataccel/factor)."""
  return base_factor * steer_max_for_speed(v_ego) / STARPILOT_STEER_MAX_REF


def apply_lat_tune_canfd_limits(params, CP_SP, v_ego_raw: float) -> bool:
  """Apply the fork's CAN FD steer limits in place. Returns False if no fork tune is
  selected, in which case the caller applies the upstream limits verbatim."""
  if CP_SP is None or not (CP_SP.flags & HyundaiFlagsSP.LAT_TUNE_STARPILOT):
    return False

  params.STEER_MAX = steer_max_for_speed(v_ego_raw)
  params.STEER_DRIVER_ALLOWANCE = STARPILOT_STEER_DRIVER_ALLOWANCE
  params.STEER_DRIVER_MULTIPLIER = STARPILOT_STEER_DRIVER_MULTIPLIER
  params.STEER_THRESHOLD = STARPILOT_STEER_THRESHOLD
  params.STEER_DELTA_UP = int(round(np.interp(v_ego_raw, CANFD_STEER_RATE_SPEED_BP, CANFD_STEER_DELTA_UP_V)))
  params.STEER_DELTA_DOWN = int(round(np.interp(v_ego_raw, CANFD_STEER_RATE_SPEED_BP, CANFD_STEER_DELTA_DOWN_V)))
  return True
