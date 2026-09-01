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
# was p50=509 / p90=625. The mid band ceiling was 600 (covering the median and most of p90)
# and is now 650 -- raised after the Aug 31 600-drive analysis showed tight-corner torque
# demand reaching the rail (|output|>0.95 on 2-6% of tight-corner frames, actuators.torque
# clipped at 1.0 ~92% of those), giving more headroom for the tightest low-speed corners.
# Unsaturated mapping is kept at the StarPilot 409/3.66 = 112 CAN per m/s^2 by scheduling
# latAccelFactor with STEER_MAX in the controller profile.
#
# The low end stays 409. A flat-650 low end was briefly deployed (e61b28a0, Sep 1) on the
# argument that "normalized output swings +/-1.0 either way, so 650 only raises peak CAN,
# not the sawtooth." That is backwards and is reverted here: the EPS sees CAN, and
# STEER_DELTA_UP is a flat 10 CAN/frame below 17 m/s (CANFD_STEER_RATE_SPEED_BP), so a
# taller rail LENGTHENS every rail-to-rail traversal -- lower flip frequency, larger wheel
# excursion per half-cycle. Route 000001c5's own analysis found the sub-23 km/h problem is
# P-relay pegging plus the angle-assist handoff, explicitly "not torque starvation", which
# argues against a taller creep rail rather than for one.
#
# NOTE: restoring 409 is NOT a fix for the creep ping-pong. c5 was driven at 17:44 with the
# 409 floor already in place and still had extreme sub-10 km/h ping-pong; the flat-650
# commit landed later at 19:25 and was never driven. This revert only returns to the known
# baseline instead of shipping an undriven change predicted to be worse. The actual creep
# fix is a control change: fade the lateral-accel PID out below ~2 m/s and let the low-speed
# angle assist own the loop (it also survives standstill steering).
CANFD_STEER_MAX_SPEED_BP = [5.0, 6.5, 15.0, 17.0]  # m/s
STARPILOT_STEER_MAX_V = [409, 650, 650, 409]
STARPILOT_STEER_MAX_REF = 409  # StarPilot / unsaturated-gain reference
STARPILOT_STEER_MAX = 650  # worst-case envelope (carcontroller + safety)
STARPILOT_STEER_DRIVER_ALLOWANCE = 75    # StarPilot ships 100; softened per request
STARPILOT_STEER_DRIVER_MULTIPLIER = 2
STARPILOT_STEER_THRESHOLD = 100


def steer_max_for_speed(v_ego: float) -> int:
  return int(round(np.interp(v_ego, CANFD_STEER_MAX_SPEED_BP, STARPILOT_STEER_MAX_V)))


def lat_accel_factor_for_speed(v_ego: float, base_factor: float) -> float:
  """Keep CAN per m/s^2 constant as STEER_MAX changes: torque*STEER_MAX / (lataccel/factor)."""
  return base_factor * steer_max_for_speed(v_ego) / STARPILOT_STEER_MAX_REF


def friction_for_speed(v_ego: float, base_friction: float) -> float:
  """Keep the friction term's CAN contribution constant as STEER_MAX changes.

  Scaling latAccelFactor (above) holds the P/I/FF paths at 112 CAN per m/s^2, but it does
  NOT cover friction: get_friction returns +/-friction*latAccelFactor in lat-accel space
  (opendbc/car/lateral.py) and the controller divides the summed feedforward by
  latAccelFactor on the way out, so the two cancel and friction's NORMALIZED torque is
  exactly `friction`. Its CAN value is therefore friction*STEER_MAX, and raising the
  ceiling alone turns a 0.09*409 = 37 CAN breakaway kick into 0.09*650 = 58.5 -- a 58% gain
  change on the one term that is a square wave through every error sign change, landing in
  the same band that already flips 1.6-1.8 times a second.

  This is not a pure restoration: holding friction's CAN constant means its lat-accel-space
  contribution shrinks inside the 650 band. That is the right invariant only because
  409/3.66 is what was actually tuned and driven.
  """
  return base_friction * STARPILOT_STEER_MAX_REF / steer_max_for_speed(v_ego)


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
