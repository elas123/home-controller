# /config/pyscript/kitchen_motion.py
# Kitchen motion → WLED + Main lights (per-mode brightness), debounced clear
# Entities confirmed by you (sink & fridge have preset selects)
# FIXED: Main lights blocked in Night mode

from datetime import datetime
import time
import asyncio

# ===== Entities =====
SINK_PRESET   = "select.sink_wled_preset"
FRIDGE_PRESET = "select.frig_strip_preset"
SINK_LIGHT    = "light.sink_wled"          # used to turn sink strip off on clear
FRIDGE_LIGHT  = "light.frig_strip"         # not strictly needed with presets but kept for safety

KITCHEN_MAIN  = "light.kitchen_main_lights"  # <-- now actively controlled

MOTION_1      = "binary_sensor.aqara_motion_sensor_p1_occupancy"
MOTION_2      = "binary_sensor.kitchen_iris_frig_occupancy"
HOME_STATE_PRIMARY = "pyscript.home_state"
HOME_STATE_FALLBACK = "input_select.home_state"
ALLOWED_MODES = {"Day", "Evening", "Night", "Early Morning"}  # mains are NOT blocked in Evening
WLED_BLOCKED_MODES = {"Day", "Away"}
NIGHT_MAIN_RESUME_HOUR = 4
NIGHT_MAIN_RESUME_MINUTE = 45

# Brightness source toggles / sensors (follow controller priority stack)
RAMP_ACTIVE = "input_boolean.sleep_in_ramp_active"
RAMP_BRIGHTNESS = "sensor.sleep_in_ramp_brightness"
ADAPTIVE_LEARNING_ENABLED = "input_boolean.adaptive_learning_enabled"
LEARNED_BRIGHTNESS = "sensor.learned_brightness_kitchen"
ALL_ROOMS_USE_PYSCRIPT = "input_boolean.all_rooms_use_pyscript"
PYSCRIPT_BRIGHTNESS = "pyscript.test_kitchen_brightness"
INTELLIGENT_LIGHTING_ENABLED = "input_boolean.intelligent_lighting_enable"
INTELLIGENT_BRIGHTNESS = "sensor.intelligent_brightness_kitchen"

# ===== Behavior knobs =====
CLEAR_DEBOUNCE_SEC = 5
TEST_BYPASS_MODE   = False       # set True to ignore mode gating while testing

# Fallback brightness for the main lights when upstream sources are unavailable
FALLBACK_BRIGHTNESS = {
    "Day": 70,            # matches controller fallback for Day target brightness
    "Evening": 60,        # comfortable brightness for Evening
    "Night": 10,          # only used after the 04:45 resume guard while still Night
    "Early Morning": 35,  # soft pre-dawn level
}
FALLBACK_DEFAULT_BRIGHTNESS = 60
# Turn mains off when motion clears?
TURN_MAIN_OFF_ON_CLEAR = True
# ===========================

# --- helpers ---
def _state(eid, d=None):
    try:
        v = state.get(eid)
        return v if v not in (None, "unknown", "unavailable") else d
    except Exception:
        return d


def _home_state() -> str:
    """Use controller home state with input_select fallback."""
    hs = _state(HOME_STATE_PRIMARY)
    if hs in (None, "", "unknown", "unavailable"):
        hs = _state(HOME_STATE_FALLBACK, "unknown")
    return hs or "unknown"

def _info(msg):  log.info(f"[KitchenALS] {msg}")
def _warn(msg):  log.warning(f"[KitchenALS] {msg}")
def _error(msg): log.error(f"[KitchenALS] {msg}")

def _set_preset(entity_id: str, option: str):
    try:
        service.call("select", "select_option", entity_id=entity_id, option=option)
        _info(f"Preset -> {entity_id} = {option}")
    except Exception as e:
        _error(f"Preset error on {entity_id}: {e}")

def _light_on(entity_id: str, **kwargs):
    try:
        service.call("light", "turn_on", entity_id=entity_id, **kwargs)
        _info(f"Light ON  -> {entity_id} {kwargs if kwargs else ''}")
    except Exception as e:
        _error(f"Light on error on {entity_id}: {e}")

def _light_off(entity_id: str):
    try:
        service.call("light", "turn_off", entity_id=entity_id)
        _info(f"Light OFF -> {entity_id}")
    except Exception as e:
        _error(f"Light off error on {entity_id}: {e}")

def _any_motion_active() -> bool:
    return (_state(MOTION_1) == "on") or (_state(MOTION_2) == "on")


def _clamp_pct(value) -> int | None:
    try:
        pct = int(float(value))
    except (TypeError, ValueError):
        return None
    return max(1, min(100, pct))


def _fallback_brightness_for(mode: str) -> int:
    return FALLBACK_BRIGHTNESS.get(mode, FALLBACK_DEFAULT_BRIGHTNESS)


def _resolve_kitchen_brightness(home_mode: str) -> int:
    """Resolve kitchen brightness using controller priority stack."""

    invalid = {None, "", "unknown", "unavailable"}

    try:
        if _state(RAMP_ACTIVE) == "on":
            ramp = _state(RAMP_BRIGHTNESS)
            if ramp not in invalid:
                val = _clamp_pct(ramp)
                if val is not None:
                    _info(f"Brightness source: Morning Ramp ({val}%)")
                    return val

        if _state(ADAPTIVE_LEARNING_ENABLED) == "on":
            learned = _state(LEARNED_BRIGHTNESS)
            if learned not in invalid:
                using_learned = False
                try:
                    attrs = state.getattr(LEARNED_BRIGHTNESS) or {}
                    using_learned = bool(attrs.get("using_learned"))
                except Exception:
                    using_learned = False
                if using_learned:
                    val = _clamp_pct(learned)
                    if val is not None:
                        _info(f"Brightness source: Adaptive Learning ({val}%)")
                        return val

        if _state(ALL_ROOMS_USE_PYSCRIPT) == "on":
            pys_val = _state(PYSCRIPT_BRIGHTNESS)
            if pys_val not in invalid:
                val = _clamp_pct(pys_val)
                if val is not None:
                    _info(f"Brightness source: PyScript Engine ({val}%)")
                    return val

        if _state(INTELLIGENT_LIGHTING_ENABLED) == "on":
            intelligent = _state(INTELLIGENT_BRIGHTNESS)
            if intelligent not in invalid:
                val = _clamp_pct(intelligent)
                if val is not None:
                    _info(f"Brightness source: Intelligent System ({val}%)")
                    return val

    except Exception as exc:
        _warn(f"Brightness resolution failed: {exc}")

    fallback = _fallback_brightness_for(home_mode)
    label = f"Fallback {home_mode}" if home_mode in FALLBACK_BRIGHTNESS else "Fallback Default"
    _info(f"Brightness source: {label} ({fallback}%)")
    return fallback


def _night_mains_window_active(now=None) -> bool:
    """Return True if mains may run while home state is Night."""
    if now is None:
        now = datetime.now()

    hour = now.hour
    minute = now.minute

    if hour < NIGHT_MAIN_RESUME_HOUR:
        return False
    if hour == NIGHT_MAIN_RESUME_HOUR and minute < NIGHT_MAIN_RESUME_MINUTE:
        return False
    # Guard against late-night Night mode by requiring this to run before noon.
    if hour >= 12:
        return False

    return True

# --- core behavior ---
def _ensure_wled_off(reason: str | None = None):
    if reason:
        _info(f"WLED off ({reason})")
    _light_off(SINK_LIGHT)
    _light_off(FRIDGE_LIGHT)


def _apply_for_motion(active: bool, reason: str):
    hs = _home_state()
    if not TEST_BYPASS_MODE and hs not in ALLOWED_MODES:
        if hs in WLED_BLOCKED_MODES:
            _ensure_wled_off(f"mode={hs} disallows WLED (reason={reason})")
        _info(f"SKIP (mode={hs}) reason={reason}")
        return

    _info(f"APPLY motion_active={active} mode={hs} reason={reason}")

    now = datetime.now()
    night_mode = hs == "Night"
    night_hold_active = night_mode and not _night_mains_window_active(now)
    if TEST_BYPASS_MODE:
        wled_allowed = True
    else:
        wled_allowed = hs not in WLED_BLOCKED_MODES

    if active:
        if wled_allowed:
            # WLEDs on preset night-100
            _set_preset(SINK_PRESET, "night-100")
            _set_preset(FRIDGE_PRESET, "night-100")
        else:
            _ensure_wled_off("mode disallows WLED during motion")

        if night_hold_active:
            _info("SKIPPING main lights – Night mode hold active (pre-04:45)")
        else:
            if night_mode:
                _info("Night resume window reached (>=04:45) – turning mains on")
            br = _resolve_kitchen_brightness(hs if not night_mode else "Night")
            _light_on(KITCHEN_MAIN, brightness_pct=br)

    else:
        if wled_allowed:
            # WLED behavior: sink OFF, fridge to night
            _light_off(SINK_LIGHT)
            _set_preset(FRIDGE_PRESET, "night")
        else:
            _ensure_wled_off("mode disallows WLED on clear")

        if TURN_MAIN_OFF_ON_CLEAR:
            if night_hold_active:
                _info("Leaving main lights alone – Night hold still active")
            else:
                _light_off(KITCHEN_MAIN)

# --- listeners (no YAML automation needed) ---
@state_trigger(MOTION_1, state_check_now=False)
@state_trigger(MOTION_2, state_check_now=False)
async def kitchen_motion_listener(**kwargs):
    eid = kwargs.get("var_name")
    new = _state(eid)
    _info(f"Listener: {eid} -> {new} @ {datetime.now().strftime('%H:%M:%S')}")

    if _any_motion_active():
        _apply_for_motion(True, reason=f"{eid} active")
    else:
        await asyncio.sleep(CLEAR_DEBOUNCE_SEC)
        if _any_motion_active():
            _info("Clear aborted (motion returned during debounce)")
            return
        _apply_for_motion(False, reason="debounced clear")


@state_trigger(HOME_STATE_PRIMARY)
@state_trigger(HOME_STATE_FALLBACK)
def kitchen_mode_change_guard(**kwargs):
    hs = _home_state()
    if hs in {"Day", "Away"}:
        _ensure_wled_off(f"home mode -> {hs}")

# --- manual tests ---
@service("pyscript.kitchen_wled_smoke_test")
def kitchen_wled_smoke_test():
    """Sets both strips to 'night-100', mains on (Evening level), then sink OFF + fridge 'night'."""
    _info("SMOKE: WLEDs -> night-100; mains on; then sink OFF, fridge -> night")
    _set_preset(SINK_PRESET, "night-100")
    _set_preset(FRIDGE_PRESET, "night-100")
    _light_on(KITCHEN_MAIN, brightness_pct=_fallback_brightness_for("Evening"))
    time.sleep(2)
    _light_off(SINK_LIGHT)
    _set_preset(FRIDGE_PRESET, "night")
    if TURN_MAIN_OFF_ON_CLEAR:
        _light_off(KITCHEN_MAIN)

@service("pyscript.kitchen_wled_force")
def kitchen_wled_force(mode: str = "active"):
    """Force 'active' or 'clear' immediately (ignores mode gating)."""
    if mode not in ("active", "clear"):
        _warn(f"force: unknown mode '{mode}'")
        return
    _apply_for_motion(mode == "active", reason=f"forced {mode}")

@service("pyscript.kitchen_debug_status")
def kitchen_debug_status():
    """Debug current state of all kitchen components"""
    _info("=== KITCHEN DEBUG STATUS ===")
    _info(f"Home State: {_home_state()}")
    _info(f"Motion 1: {_state(MOTION_1)}")
    _info(f"Motion 2: {_state(MOTION_2)}")
    _info(f"Any Motion Active: {_any_motion_active()}")
    _info(f"Sink Preset: {_state(SINK_PRESET)}")
    _info(f"Fridge Preset: {_state(FRIDGE_PRESET)}")
    _info(f"Sink Light: {_state(SINK_LIGHT)}")
    _info(f"Kitchen Main: {_state(KITCHEN_MAIN)}")
    _info(f"Test Bypass: {TEST_BYPASS_MODE}")
    _info("=== END DEBUG ===")
