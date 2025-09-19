"""
PyScript: Morning Ramp Glide Follower

Goal: Make light changes imperceptibly smooth during the morning ramp.

How it works
- Every ~10s while `input_boolean.sleep_in_ramp_active` is on, it nudges a
  target light group to the latest Intelligent targets using an overlong
  transition so successive updates blend.

Setup
- Create a light group named `light.ramp_glide` with the lamps you want to glide.
  Settings → Helpers → Light Group → Entity ID: light.ramp_glide.
  If the group is missing, this script does nothing.
"""

from datetime import datetime


def _get(eid: str, default=None, attr: str | None = None):
    try:
        if attr:
            return (state.getattr(eid) or {}).get(attr, default)
        v = state.get(eid)
        return v if v not in (None, "unknown", "unavailable", "") else default
    except Exception:
        return default


def _exists(eid: str) -> bool:
    try:
        return state.get(eid) is not None or state.get(eid, attr="state") is not None
    except Exception:
        return False


def _apply_once():
    if _get("input_boolean.sleep_in_ramp_active") != "on":
        return
    if not _exists("light.ramp_glide"):
        return
    # Desired targets
    bri_target = int(float(_get("sensor.intelligent_brightness_master", 30)))
    kelvin = int(float(_get("sensor.intelligent_temperature_master", 3000)))
    # Clamp brightness change to at most 1% per tick
    last_bri = _get("sensor.ramp_glide_last_brightness", None)
    try:
        last_bri = int(float(last_bri)) if last_bri is not None else None
    except Exception:
        last_bri = None
    if last_bri is None:
        bri_apply = bri_target
    else:
        delta = bri_target - last_bri
        if delta > 1:
            bri_apply = last_bri + 1
        elif delta < -1:
            bri_apply = last_bri - 1
        else:
            bri_apply = bri_target

    # Use a transition slightly longer than update cadence to blend
    transition = 4
    try:
        service.call("light", "turn_on",
                     entity_id="light.ramp_glide",
                     brightness_pct=max(1, min(100, int(bri_apply))),
                     color_temp_kelvin=max(1500, min(6500, kelvin)),
                     transition=transition)
        # Remember last applied
        state.set("sensor.ramp_glide_last_brightness", int(bri_apply), {"friendly_name": "Ramp Glide Last Brightness", "unit_of_measurement": "%"})
    except Exception as e:
        log.error(f"[RampGlide] light.turn_on failed: {e}")


@state_trigger("input_boolean.sleep_in_ramp_active == 'on'")
def _on_ramp_start(value=None):
    _apply_once()


@time_trigger("startup", "period(3)")
def _tick_glide():
    _apply_once()
