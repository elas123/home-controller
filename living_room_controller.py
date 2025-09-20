"""
Living Room lighting controller.

Responsibilities:
- Keep the living room lamps aligned with Home Controller modes (Evening, Night, Early Morning).
- Ensure lamps are on before the evening pre-ramp/ramp so color transitions always have fixtures to act on.
- Allow the morning ramp to take control of the lamps when it activates.
"""

from __future__ import annotations

from typing import Iterable

try:
    from home_controller import (
        EV_RAMP_BRI,
        EV_RAMP_END_K,
        EV_RAMP_START_K,
        WORK_RAMP_START_BRIGHTNESS,
        WORK_RAMP_START_TEMP,
    )
except Exception:  # pragma: no cover - defensive in case of standalone execution
    EV_RAMP_BRI = 50
    EV_RAMP_START_K = 4000
    EV_RAMP_END_K = 2000
    WORK_RAMP_START_BRIGHTNESS = 10
    WORK_RAMP_START_TEMP = 2000

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
EVENING_RAMP_STARTED_FLAG = "pyscript.evening_ramp_started_today"

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


def _current_light_levels() -> tuple[int | None, int | None]:
    for entity in _living_room_targets():
        try:
            attrs = state.getattr(entity) or {}
        except Exception:
            continue

        brightness_attr = attrs.get("brightness")
        kelvin = attrs.get("color_temp_kelvin")

        if kelvin is None:
            mired = attrs.get("color_temp")
            if mired not in (None, "", "unknown", "unavailable"):
                try:
                    kelvin = int(1_000_000 / max(1, int(float(mired))))
                except Exception:
                    kelvin = None

        brightness_pct = None
        if brightness_attr not in (None, "", "unknown", "unavailable"):
            try:
                brightness_pct = int(round((int(brightness_attr) / 255) * 100))
            except Exception:
                brightness_pct = None

        if brightness_pct is not None or kelvin is not None:
            return brightness_pct, kelvin

    return None, None


def _clamp_int(value, minimum: int, maximum: int, default: int) -> int:
    try:
        coerced = int(float(value))
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, coerced))


def _evening_targets() -> tuple[int, int]:
    ramp_started = str(_state(EVENING_RAMP_STARTED_FLAG, "off")).lower() == "on"

    if ramp_started:
        current_brightness, current_kelvin = _current_light_levels()
        brightness = _clamp_int(
            current_brightness if current_brightness is not None else EV_RAMP_BRI,
            1,
            100,
            EV_RAMP_BRI,
        )
        kelvin = _clamp_int(
            current_kelvin if current_kelvin is not None else EV_RAMP_END_K,
            EV_RAMP_END_K,
            EV_RAMP_START_K,
            EV_RAMP_END_K,
        )
        return brightness, kelvin

    brightness_raw = _state(EVENING_START_BRIGHTNESS)
    brightness = _clamp_int(
        brightness_raw if brightness_raw is not None else EV_RAMP_BRI,
        1,
        100,
        EV_RAMP_BRI,
    )
    if brightness != EV_RAMP_BRI:
        _log_info(
            f"Adjusting evening brightness to spec {EV_RAMP_BRI}% (helper {EVENING_START_BRIGHTNESS}={brightness_raw})"
        )
        brightness = EV_RAMP_BRI

    temp_raw = _state(EVENING_START_TEMP)
    kelvin = _clamp_int(
        temp_raw if temp_raw is not None else EV_RAMP_START_K,
        EV_RAMP_END_K,
        EV_RAMP_START_K,
        EV_RAMP_START_K,
    )
    if kelvin != EV_RAMP_START_K:
        _log_info(
            f"Adjusting evening start temperature to spec {EV_RAMP_START_K}K "
            f"(helper {EVENING_START_TEMP}={temp_raw})"
        )
        kelvin = EV_RAMP_START_K

    return brightness, kelvin


def _ramp_brightness(default: int | None = None) -> int:
    fallback = WORK_RAMP_START_BRIGHTNESS if default is None else default
    raw = _state(SLEEP_RAMP_BRIGHTNESS)
    return _clamp_int(raw if raw is not None else fallback, 1, 100, fallback)


def _ramp_temperature(default: int | None = None) -> int:
    fallback = WORK_RAMP_START_TEMP if default is None else default
    raw = _state(SLEEP_RAMP_TEMP)
    return _clamp_int(raw if raw is not None else fallback, WORK_RAMP_START_TEMP, 6500, fallback)


def _apply_light_settings(
    lights: Iterable[str],
    brightness_pct: int,
    kelvin: int,
    reason: str,
    *,
    min_kelvin: int | None = None,
) -> None:
    lights = list(lights)
    if not lights:
        return

    if brightness_pct <= 0:
        brightness_pct = 1
    if min_kelvin is not None:
        kelvin = max(min_kelvin, kelvin)

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
    brightness, kelvin = _evening_targets()
    _apply_light_settings(
        _living_room_targets(),
        brightness,
        kelvin,
        reason,
        min_kelvin=EV_RAMP_END_K,
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
