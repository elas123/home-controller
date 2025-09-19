# COMPLETE PyScript bathroom controller — motion + door hold + brightness selection
from datetime import datetime, time as dt_time
import asyncio

# ===== Entities =====
BATHROOM_LIGHT = "light.bathroom_2_main_lights"
MOTION_1 = "binary_sensor.bathroom_iris_occupancy"
DOOR_SENSOR = "binary_sensor.bathroom_contact_contact"  # off = closed
HOME_STATE = "input_select.home_state"
ALLOWED_MODES = {"Day", "Evening", "Night", "Early Morning"}  # no actions while Away

# ===== Configuration =====
MOTION_TIMEOUT_SECONDS = 30
HOLD_TIMEOUT_MINUTES = 30
DOOR_CLOSED_BRIGHTNESS = 100
DOOR_OPEN_GRACE_SECONDS = 5

# Fallback brightness (used only if none of the upstream sources are available)
FALLBACK_DAY_BRIGHTNESS = 70
FALLBACK_EVENING_BRIGHTNESS = 50
FALLBACK_NIGHT_BRIGHTNESS = 1

# External brightness sources (preferred)
RAMP_ACTIVE = "input_boolean.sleep_in_ramp_active"
RAMP_BRIGHTNESS = "sensor.sleep_in_ramp_brightness"
ADAPTIVE_LEARNING_ENABLED = "input_boolean.adaptive_learning_enabled"
INTELLIGENT_LIGHTING_ENABLED = "input_boolean.intelligent_lighting_enable"
ALL_ROOMS_USE_PYSCRIPT = "input_boolean.all_rooms_use_pyscript"
LEARNED_BRIGHTNESS = "sensor.learned_brightness_bathroom"
INTELLIGENT_BRIGHTNESS = "sensor.intelligent_brightness_bathroom"
PYSCRIPT_BRIGHTNESS = "pyscript.test_bathroom_brightness"

# State
hold_mode_active = False
hold_mode_task = None
door_open_grace_until = 0.0
_debug_log_enabled = False

# --- Helpers ---
def _state(eid, d=None):
    try:
        v = state.get(eid)
        return v if v not in (None, "unknown", "unavailable") else d
    except Exception:
        return d


def _info(msg):
    if _debug_log_enabled:
        log.info(f"[BathroomALS] {msg}")


def _warn(msg):
    log.warning(f"[BathroomALS] {msg}")


def _error(msg):
    log.error(f"[BathroomALS] {msg}")


def _any_motion_active() -> bool:
    return _state(MOTION_1) == "on"


def _door_closed() -> bool:
    return _state(DOOR_SENSOR) == "off"


def _cancel_hold_timer(reason: str | None = None):
    """Cancel any pending hold timer task and swallow cancellation errors."""
    global hold_mode_task
    task_ref = hold_mode_task
    if not task_ref:
        return

    hold_mode_task = None

    def _finalize_cancel(task_obj):
        try:
            task_obj.result()
        except asyncio.CancelledError:
            if reason:
                _info(f"Hold timer cancelled ({reason})")
            else:
                _info("Hold timer cancelled")
        except Exception as exc:
            _warn(f"Hold timer cancellation raised: {exc}")
        else:
            if reason:
                _info(f"Hold timer completed early ({reason})")

    if task_ref.done():
        _finalize_cancel(task_ref)
        return

    task_ref.add_done_callback(_finalize_cancel)
    task_ref.cancel()


# --- Brightness Calculation (prefers external sources; falls back if none available) ---
def calculate_bathroom_brightness():
    try:
        if _state(RAMP_ACTIVE) == "on":
            ramp_bri = _state(RAMP_BRIGHTNESS)
            if ramp_bri not in ["unavailable", "unknown", None]:
                _info(f"Brightness: Morning Ramp {ramp_bri}%")
                return max(1, min(100, int(float(ramp_bri))))

        if _state(HOME_STATE) == "Night":
            _info(f"Brightness: Night Lock {FALLBACK_NIGHT_BRIGHTNESS}%")
            return FALLBACK_NIGHT_BRIGHTNESS

        if _state(ADAPTIVE_LEARNING_ENABLED) == "on":
            learned = _state(LEARNED_BRIGHTNESS)
            ok = False
            try:
                a = state.getattr(LEARNED_BRIGHTNESS) or {}
                ok = bool(a.get("using_learned", False))
            except Exception:
                pass
            if learned not in ["unavailable", "unknown", None] and ok:
                _info(f"Brightness: Learned {learned}%")
                return max(1, min(100, int(float(learned))))

        if _state(ALL_ROOMS_USE_PYSCRIPT) == "on":
            pys_bri = _state(PYSCRIPT_BRIGHTNESS)
            if pys_bri not in ["unavailable", "unknown", None]:
                _info(f"Brightness: PyScript {pys_bri}%")
                return max(1, min(100, int(float(pys_bri))))

        if _state(INTELLIGENT_LIGHTING_ENABLED) == "on":
            ib = _state(INTELLIGENT_BRIGHTNESS)
            if ib not in ["unavailable", "unknown", None]:
                _info(f"Brightness: Intelligent {ib}%")
                return max(1, min(100, int(float(ib))))

        mode = _state(HOME_STATE, "unknown")
        if mode in ["Evening", "Early Morning"]:
            _info(f"Brightness: Fallback Evening {FALLBACK_EVENING_BRIGHTNESS}%")
            return FALLBACK_EVENING_BRIGHTNESS
        elif mode == "Day":
            _info(f"Brightness: Fallback Day {FALLBACK_DAY_BRIGHTNESS}%")
            return FALLBACK_DAY_BRIGHTNESS
        _info("Brightness: Default 50%")
        return 50
    except Exception as e:
        import traceback as _tb
        service.call("pyscript", "pys_explain_event",
                     context="Bathroom:motion", level="ERROR",
                     msg="calculate_bathroom_brightness failed",
                     data={"home_state": _state(HOME_STATE)},
                     exception=str(e),
                     traceback_text=_tb.format_exc())
        return 50


def _light_on(brightness_pct: int, transition: int | None = None):
    try:
        data = {"entity_id": BATHROOM_LIGHT, "brightness_pct": int(max(1, min(100, brightness_pct)))}
        if isinstance(transition, (int, float)) and transition > 0:
            data["transition"] = int(transition)
        service.call("light", "turn_on", **data)
        _info(f"Light ON {brightness_pct}% (t={data.get('transition','-')})")
    except Exception as e:
        import traceback as _tb
        service.call("pyscript", "pys_explain_event",
                     context="Bathroom:motion", level="ERROR",
                     msg="light_on failed",
                     data={"brightness_pct": brightness_pct},
                     exception=str(e),
                     traceback_text=_tb.format_exc())


def _light_off():
    try:
        service.call("light", "turn_off", entity_id=BATHROOM_LIGHT)
        _info("Light OFF")
    except Exception as e:
        import traceback as _tb
        service.call("pyscript", "pys_explain_event",
                     context="Bathroom:motion", level="ERROR",
                     msg="light_off failed",
                     exception=str(e),
                     traceback_text=_tb.format_exc())


def _apply_for_motion(active: bool, reason: str):
    global hold_mode_active, door_open_grace_until
    hs = _state(HOME_STATE, "unknown")

    # Don’t turn on lights in Away
    if hs == "Away":
        _warn("Skip (Away mode)")
        return
    if hs not in ALLOWED_MODES:
        _warn(f"Skip (invalid mode: {hs})")
        return

    _info(f"APPLY motion={active} mode={hs} reason={reason}")

    if active:
        now_ts = datetime.now().timestamp()
        door_override_active = door_open_grace_until and now_ts < door_open_grace_until

        closed = _door_closed()
        if door_override_active and closed:
            _info(f"Door grace active until {door_open_grace_until:.1f} (now={now_ts:.1f}) -> ignoring closed state")
            closed = False

        if closed:
            if not hold_mode_active:
                _info("Door closed -> 100% hold")
            _cancel_hold_timer("door closed hold")
            hold_mode_active = True
            _light_on(DOOR_CLOSED_BRIGHTNESS)
            return

        if hold_mode_active:
            _info("Door opened -> exit hold")
        hold_mode_active = False
        door_open_grace_until = max(door_open_grace_until, now_ts + DOOR_OPEN_GRACE_SECONDS)
        _info(f"Set door grace window to {door_open_grace_until:.1f}")
        target = calculate_bathroom_brightness()

        # Skip needless on-command if already at similar brightness
        cur = _state(BATHROOM_LIGHT)
        if cur == "on":
            try:
                raw = (state.getattr(BATHROOM_LIGHT) or {}).get("brightness", 0)
                cur_pct = int((raw / 255) * 100) if raw else 0
                if abs(cur_pct - target) < 3:
                    _info(f"Already ~{cur_pct}%, target {target}% → skip")
                    return
            except Exception:
                pass

        _light_on(target)
    else:
        if not hold_mode_active:
            _cancel_hold_timer("motion cleared")
            _light_off()
        else:
            _info("Hold mode active → keep on")


# --- Motion Listeners ---
@state_trigger(MOTION_1)
async def bathroom_motion_listener(**kwargs):
    global hold_mode_task
    eid = kwargs.get("var_name")
    new = _state(eid)
    _info(f"Motion: {eid} -> {new} @ {datetime.now().strftime('%H:%M:%S')}")

    if _any_motion_active():
        _cancel_hold_timer("motion active")
        # Optional: trigger ramp service when appropriate
        _apply_for_motion(True, reason=f"{eid} active")
    else:
        await asyncio.sleep(MOTION_TIMEOUT_SECONDS)
        if _any_motion_active():
            _info("Motion returned during debounce")
            return
        if _door_closed():
            _info(f"Door closed → start {HOLD_TIMEOUT_MINUTES} min hold timer")
            hold_mode_task = task.create(_hold_timeout())
        else:
            _apply_for_motion(False, reason="motion cleared")


async def _hold_timeout():
    global hold_mode_active, hold_mode_task
    current_task = asyncio.current_task()
    try:
        await asyncio.sleep(HOLD_TIMEOUT_MINUTES * 60)
        if not _any_motion_active():
            hold_mode_active = False
            _light_off()
            _info("Hold timeout → off")
    except asyncio.CancelledError:
        raise
    finally:
        if hold_mode_task is current_task:
            hold_mode_task = None


# --- Door Sensor Listener ---
@state_trigger(DOOR_SENSOR)
def bathroom_door_listener(**kwargs):
    global hold_mode_active, hold_mode_task, door_open_grace_until
    new = _state(DOOR_SENSOR)
    closed = _door_closed()
    now_ts = datetime.now().timestamp()
    _info(f"Door -> {new} (closed={closed}) grace={door_open_grace_until:.1f} now={now_ts:.1f}")

    if closed and _state(BATHROOM_LIGHT) == "on":
        _cancel_hold_timer("door closed sensor")
        hold_mode_active = True
        door_open_grace_until = 0.0
        _light_on(DOOR_CLOSED_BRIGHTNESS)
        _info("Door closed → 100% hold")
    elif not closed:
        _cancel_hold_timer("door opened")
        hold_mode_active = False
        door_open_grace_until = datetime.now().timestamp() + DOOR_OPEN_GRACE_SECONDS
        _info(f"Door open -> extend grace to {door_open_grace_until:.1f}")
        if _any_motion_active():
            _apply_for_motion(True, reason="door_open_refresh")
        elif _state(BATHROOM_LIGHT) == "on":
            tgt = calculate_bathroom_brightness()
            _light_on(tgt)
            _info(f"Door opened → adjust to {tgt}%")


# --- Mode-based Control ---
@state_trigger("input_select.home_state == 'Away'")
def bathroom_away_mode():
    global hold_mode_active
    hold_mode_active = False
    _info("Away mode → turning off lights")
    _light_off()


# --- Manual services ---
@service("pyscript.bathroom_force")
def bathroom_force(mode: str = "on"):
    if mode == "on":
        _light_on(calculate_bathroom_brightness())
    else:
        _light_off()


@service("pyscript.bathroom_debug_status")
def bathroom_debug_status():
    _info("=== BATHROOM DEBUG ===")
    _info(f"Home State: {_state(HOME_STATE)}")
    _info(f"Motion: {_state(MOTION_1)}")
    _info(f"Door: {_state(DOOR_SENSOR)} (closed={_door_closed()})")
    _info(f"Light: {_state(BATHROOM_LIGHT)}")
    _info(f"Hold: {hold_mode_active}")
    _info("======================")


@service("pyscript.bathroom_debug_toggle")
def bathroom_debug_toggle(enable: bool = True):
    global _debug_log_enabled
    _debug_log_enabled = bool(enable)
    state.set("pyscript.bathroom_debug_enabled", "on" if _debug_log_enabled else "off")
    log.info(f"[BathroomALS] Debug logging {'enabled' if _debug_log_enabled else 'disabled'}")


@service("pyscript.bathroom_simulate")
async def bathroom_simulate(sequence: list[str] = None, delay: float = 1.0):
    """Simulate door/motion events. sequence accepts tokens like 'motion_on', 'motion_off', 'door_open', 'door_closed'."""
    global _debug_log_enabled
    if not sequence:
        sequence = [
            "motion_on",
            "door_closed",
            "sleep",
            "door_open",
            "sleep",
            "motion_on",
            "sleep",
            "motion_off",
        ]

    prev_debug = _debug_log_enabled
    _debug_log_enabled = True
    log.info(f"[BathroomALS] Simulation start: {sequence}")

    try:
        for step in sequence:
            if step == "motion_on":
                state.set(MOTION_1, "on")
                _info("Sim: motion_on")
            elif step == "motion_off":
                state.set(MOTION_1, "off")
                _info("Sim: motion_off")
            elif step == "door_open":
                state.set(DOOR_SENSOR, "on")
                _info("Sim: door_open")
            elif step == "door_closed":
                state.set(DOOR_SENSOR, "off")
                _info("Sim: door_closed")
            elif step == "sleep":
                await asyncio.sleep(delay)
            else:
                _warn(f"Unknown simulation step: {step}")
                await asyncio.sleep(delay)
            await asyncio.sleep(delay)
    finally:
        _debug_log_enabled = prev_debug
        log.info("[BathroomALS] Simulation end")


@time_trigger("startup")
def bathroom_startup():
    _info("Bathroom system startup")
    _info(f"Door closed: {_door_closed()}")
    _info(f"Motion active: {_any_motion_active()}")

