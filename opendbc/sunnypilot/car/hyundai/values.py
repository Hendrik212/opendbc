"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""

from enum import IntFlag


class RadarType:
  OFF = 0
  LEAD_ONLY = 1
  FULL_RADAR = 2


class HyundaiSafetyFlagsSP:
  DEFAULT = 0
  ESCC = 1
  LONG_MAIN_CRUISE_TOGGLEABLE = 2
  HAS_LDA_BUTTON = 4
  NON_SCC = 8


class HyundaiFlagsSP(IntFlag):
  """
    Flags for Hyundai specific quirks within sunnypilot.
  """
  ENHANCED_SCC = 1
  HAS_LFA_BUTTON = 2  # Deprecated in favor of HyundaiFlags.HAS_LDA_BUTTON
  LONGITUDINAL_MAIN_CRUISE_TOGGLEABLE = 2 ** 2
  ENABLE_RADAR_TRACKS_DEPRECATED = 2 ** 3
  LONG_TUNING_DYNAMIC = 2 ** 4
  LONG_TUNING_PREDICTIVE = 2 ** 5
  NON_SCC = 2 ** 6
  NON_SCC_RADAR_FCA = 2 ** 7  # most with FCA come from the camera
  NON_SCC_NO_FCA = 2 ** 8  # not all have FCA
  SPEED_LIMIT_AVAILABLE = 2 ** 9  # platforms with speed limit data available
  HAS_LKAS12 = 2 ** 10
  RADAR_LEAD_ONLY = 2 ** 12
  RADAR_FULL_RADAR = 2 ** 13
  LAT_TUNE_STARPILOT = 2 ** 14  # Ioniq 6: StarPilot lateral tune (see latcontrol_ioniq6_tune.py)


# StarPilot Ioniq 6 lateral tune baseline. The controller owns these (see
# latcontrol_torque_v2.py): they are NOT written into CP at fingerprint time, so a
# live tune switch never depends on a stale CarParams blob. torqued learns the
# unmultiplied latAccelFactor; the controller applies the 1.22 multiplier on use.
#
# The old fingerprint-time path also set CP.maxLateralAccel = 3.0. That field is read
# only by the UI torque bar's display scale (torque_bar.py) and by docs/tests -- never
# by control -- so it is deliberately left at the override.toml value now.
IONIQ6_STARPILOT_TORQUE = {'LAT_ACCEL_FACTOR': 3.0, 'FRICTION': 0.09}

# TorqueControlTune value that selects the StarPilot tune (v2). Kept next to the flag
# so the one definition is shared.
TORQUE_CONTROL_TUNE_STARPILOT = 2.0


def is_starpilot_lat_tune(CP, torque_control_tune, enforce_torque_control) -> bool:
  """Single source of truth for 'is the StarPilot lateral tune selected?'.

  Both processes derive the answer from the SAME params instead of from a separate
  stored flag, so they cannot disagree about which tune is active for longer than
  their respective poll intervals:
    - card (carcontroller): 10 Hz params_thread -> sets LAT_TUNE_STARPILOT on CP_SP,
      and CarControllerParams is rebuilt per-frame from it, so the 409 ceiling and
      rate ramp follow live.
    - controlsd: ~1 Hz check_lateral_control_version -> rebuilds the controller.
  Making the predicate derived rather than stored is what makes the "StarPilot
  limits + upstream control law" hybrid unrepresentable.

  enforce_torque_control must be included: initialize_lateral_control falls back to
  LatControlTorqueV0 whenever EnforceTorqueControl is off, IGNORING TorqueControlTune.
  Deriving the limits from the tune version alone would then hand v0's control law the
  StarPilot 409 ceiling -- persistently, not just for a poll interval.
  """
  # Local import: opendbc.car.hyundai.values imports HyundaiFlagsSP from this module,
  # so a top-level import here would be circular.
  from opendbc.car.hyundai.values import HyundaiFlags

  if not enforce_torque_control:
    return False
  if CP.brand != 'hyundai' or not (CP.flags & HyundaiFlags.CANFD):
    return False
  try:
    return float(torque_control_tune or 0.0) == TORQUE_CONTROL_TUNE_STARPILOT
  except (TypeError, ValueError):
    return False
