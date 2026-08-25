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

# STEER_MAX is speed-scheduled: 500 through the band where the controller actually rails,
# 409 above it. carcontroller computes `torque * STEER_MAX`, so this raises the EFFECTIVE
# GAIN at low speed as well as the ceiling -- 500/3.66 = 137 CAN per m/s^2 below the
# breakpoint vs 409/3.66 = 112 above. That is intended here (more low-speed authority), but
# it is not free headroom, so it must be read as a tune change.
#
# The earlier scheduled version (0be6b7fe, 409 low -> 270 high) failed for a reason that no
# longer applies: torqued learns latAccelFactor only above its MIN_VEL = 15 m/s, so it
# calibrated against the high-speed normalization and the low-speed band inherited a gain it
# never observed. The StarPilot profile declines live torque params entirely
# (use_live_torque_params = False) and owns a fixed 3.66, so there is no longer a learned
# factor to desynchronise.
#
# Breakpoints from measured saturation on route 0000019b (engaged, hands-off, blinker off):
# full-ceiling frames were 4.32% below 3 m/s, 3.78% at 3-8, 3.49% at 8-15, and 0.00% above
# 15 m/s. So the schedule holds 500 through 15 m/s and is back to 409 by 17 m/s, completing
# before the rate ramp starts (CANFD_STEER_RATE_SPEED_BP).
#
# The 1.22 multiplier is applied in the controller (see lateral_tunes/ioniq6_starpilot.py),
# not here.
CANFD_STEER_MAX_SPEED_BP = [15., 17.]  # m/s
STARPILOT_STEER_MAX_V = [500, 409]
STARPILOT_STEER_MAX = 500  # panda envelope / worst case
STARPILOT_STEER_DRIVER_ALLOWANCE = 75    # StarPilot ships 100; softened per request
STARPILOT_STEER_DRIVER_MULTIPLIER = 2
STARPILOT_STEER_THRESHOLD = 100


def apply_lat_tune_canfd_limits(params, CP_SP, v_ego_raw: float) -> bool:
  """Apply the fork's CAN FD steer limits in place. Returns False if no fork tune is
  selected, in which case the caller applies the upstream limits verbatim."""
  if CP_SP is None or not (CP_SP.flags & HyundaiFlagsSP.LAT_TUNE_STARPILOT):
    return False

  params.STEER_MAX = int(round(np.interp(v_ego_raw, CANFD_STEER_MAX_SPEED_BP, STARPILOT_STEER_MAX_V)))
  params.STEER_DRIVER_ALLOWANCE = STARPILOT_STEER_DRIVER_ALLOWANCE
  params.STEER_DRIVER_MULTIPLIER = STARPILOT_STEER_DRIVER_MULTIPLIER
  params.STEER_THRESHOLD = STARPILOT_STEER_THRESHOLD
  params.STEER_DELTA_UP = int(round(np.interp(v_ego_raw, CANFD_STEER_RATE_SPEED_BP, CANFD_STEER_DELTA_UP_V)))
  params.STEER_DELTA_DOWN = int(round(np.interp(v_ego_raw, CANFD_STEER_RATE_SPEED_BP, CANFD_STEER_DELTA_DOWN_V)))
  return True
