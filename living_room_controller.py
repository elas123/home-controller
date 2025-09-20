"""
Living Room lighting controller.

Responsibilities:
- Keep the living room lamps aligned with Home Controller modes (Evening, Night, Early Morning).
- Ensure lamps are on before the evening pre-ramp/ramp so color transitions always have fixtures to act on.
- Allow the morning ramp to take control of the lamps when it activates.
"""

from __future__ import annotations

from typing import Iterable

# Entities
LIVING_ROOM_LIGHTS: tuple[str, ...] = (
    "light.lamp_1",
    "light.lamp_2",
)

HOME_STATE_PRIMARY = "pyscript.home_state"
HOME_STATE_FALLBACK = "input_select.home_state"
EVENING_MODE_FLAG = "input_boolean.evening_mode_active"
EVENING_PRERAMP_FLAG = "input_boolean.pys_evening_preramp_active"
EVENING_ENABLE_TOGGLE = "input_boolean.living_room_evening_ramp_enabled"
EVENING_START_BRIGHTNESS = "input_number.living_room_evening_start_brightness"
EVENING_START_TEMP = "input_number.living_room_evening_start_temp"

SLEEP_RAMP_ACTIVE = "input_boolean.sleep_in_ramp_active"
SLEEP_RAMP_BRIGHTNESS = "sensor.sleep_in_ramp_brightness"
SLEEP_RAMP_TEMP = "sensor.sleep_in_ramp_temperature"

AWAY_MODES = {"Away"}
LIGHT_DOMAIN = "light"


def _log_info(message: str) -> None:
    log.info(f"[LivingRoomCtrl] {message}")


def _log_warning(message: str) -> None:
    log.warning(f"[LivingRoomCtrl] {message}")


def _state(entity_id: str, default=None):
    try:
        value = state.get(entity_id)
    except Exception:
        return default
    if value in (None, "unknown", "unavailable", ""):
        return default
    return value


def _home_mode() -> str:
    mode = _state(HOME_STATE_PRIMARY)
    if mode:
        return mode
    fallback = _state(HOME_STATE_FALLBACK, "unknown")
    return fallback or "unknown"


def _living_room_targets() -> list[str]:
    return [entity for entity in LIVING_ROOM_LIGHTS if entity]


def _clamp_int(value, minimum: int, maximum: int, default: int) -> int:
    try:
        coerced = int(float(value))
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, coerced))


def _target_brightness(default: int = 50) -> int:
    raw = _state(EVENING_START_BRIGHTNESS)
    return _clamp_int(raw if raw is not None else default, 1, 100, default)


def _target_temperature(default: int = 2700) -> int:
    raw = _state(EVENING_START_TEMP)
    return _clamp_int(raw if raw is not None else default, 1800, 6500, default)


def _ramp_brightness(default: int = 10) -> int:
    raw = _state(SLEEP_RAMP_BRIGHTNESS)
    return _clamp_int(raw if raw is not None else default, 1, 100, default)


def _ramp_temperature(default: int = 2000) -> int:
    raw = _state(SLEEP_RAMP_TEMP)
    return _clamp_int(raw if raw is not None else default, 1500, 6500, default)


def _apply_light_settings(lights: Iterable[str], brightness_pct: int, kelvin: int, reason: str) -> None:
    lights = list(lights)
    if not lights:
        return

    if brightness_pct <= 0:
        brightness_pct = 1
    if kelvin < 1500:
        kelvin = 1500

    try:
        service.call(
            LIGHT_DOMAIN,
            "turn_on",
            entity_id=lights,
            brightness_pct=brightness_pct,
            kelvin=kelvin,
        )
        _log_info(f"Lights set to {brightness_pct}% @ {kelvin}K ({reason})")
    except Exception as exc:
        try:
            mired = int(1_000_000 / max(1, kelvin))
            service.call(
                LIGHT_DOMAIN,
                "turn_on",
                entity_id=lights,
                brightness_pct=brightness_pct,
                color_temp=mired,
            )
            _log_info(
                f"Lights set using mired fallback {brightness_pct}% @ {mired}mired ({reason})"
            )
        except Exception as fallback_exc:
            _log_warning(
                f"Failed to apply living room lighting ({reason}): {exc} / {fallback_exc}"
            )


def _turn_off_lights(reason: str) -> None:
    lights = _living_room_targets()
    if not lights:
        return
    if not any(str(_state(light, "off")).lower() == "on" for light in lights):
        return
    try:
        service.call(LIGHT_DOMAIN, "turn_off", entity_id=lights)
        _log_info(f"Lights off ({reason})")
    except Exception as exc:
        _log_warning(f"Failed to turn off lights ({reason}): {exc}")


def _apply_evening(reason: str) -> None:
    if str(_state(EVENING_ENABLE_TOGGLE, "on")).lower() != "on":
        _log_info(f"Skip evening activation ({reason}); toggle is off")
        return
    if _home_mode() in AWAY_MODES:
        _log_info(f"Skip evening activation ({reason}); home is Away")
        return
    _apply_light_settings(
        _living_room_targets(),
        _target_brightness(),
        _target_temperature(),
        reason,
    )


def _apply_sleep_ramp(reason: str) -> None:
    if _home_mode() in AWAY_MODES:
        _log_info(f"Skip ramp activation ({reason}); home is Away")
        return
    _apply_light_settings(
        _living_room_targets(),
        _ramp_brightness(),
        _ramp_temperature(),
        reason,
    )


@state_trigger(f"{EVENING_MODE_FLAG}")
def _on_evening_mode(value=None, old_value=None, **kwargs):
    new_state = str(value if value is not None else _state(EVENING_MODE_FLAG, "off")).lower()
    if new_state == "on":
        _apply_evening("evening_mode_on")
    else:
        _turn_off_lights("evening_mode_off")


@state_trigger(f"{EVENING_ENABLE_TOGGLE}")
def _on_evening_toggle(value=None, old_value=None, **kwargs):
    new_state = str(value if value is not None else _state(EVENING_ENABLE_TOGGLE, "off")).lower()
    if new_state == "on" and (
        str(_state(EVENING_MODE_FLAG, "off")).lower() == "on"
        or str(_state(EVENING_PRERAMP_FLAG, "off")).lower() == "on"
    ):
        _apply_evening("toggle_on")


@state_trigger(f"{EVENING_PRERAMP_FLAG}")
def _on_evening_preramp(value=None, old_value=None, **kwargs):
    new_state = str(value if value is not None else _state(EVENING_PRERAMP_FLAG, "off")).lower()
    if new_state == "on":
        _apply_evening("evening_preramp")


@state_trigger(f"{SLEEP_RAMP_ACTIVE}")
def _on_sleep_ramp(value=None, old_value=None, **kwargs):
    new_state = str(value if value is not None else _state(SLEEP_RAMP_ACTIVE, "off")).lower()
    if new_state == "on":
        _apply_sleep_ramp("sleep_ramp_start")


@state_trigger(f"{HOME_STATE_PRIMARY}")
def _on_home_state(value=None, old_value=None, **kwargs):
    mode = value if value is not None else _home_mode()
    if mode == "Evening" and str(_state(EVENING_MODE_FLAG, "off")).lower() == "on":
        _apply_evening("home_state_evening")
    elif mode in ("Night", "Away"):
        _turn_off_lights(f"home_state_{mode.lower()}")
    elif mode == "Early Morning" and str(_state(SLEEP_RAMP_ACTIVE, "off")).lower() == "on":
        _apply_sleep_ramp("home_state_em")


@time_trigger("startup")
def _sync_startup():
    if str(_state(SLEEP_RAMP_ACTIVE, "off")).lower() == "on":
        _apply_sleep_ramp("startup_ramp")
    elif (
        str(_state(EVENING_MODE_FLAG, "off")).lower() == "on"
        or str(_state(EVENING_PRERAMP_FLAG, "off")).lower() == "on"
    ):
        _apply_evening("startup_evening")
