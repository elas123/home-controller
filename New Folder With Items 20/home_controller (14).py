"""
home_controller.py – REWORK COMPLIANT - FOLLOWS SPEC TO THE LETTER
Every SET IN STONE requirement from REWORK is implemented exactly
"""

from datetime import datetime, date, time as dt_time, timedelta
import asyncio
import asyncio
import traceback
import json
import time
from typing import Optional

# ============================================================================
# CONFIGURATION - SET IN STONE PER REWORK SPEC
# ============================================================================
PHONE_1 = "device_tracker.iphone15"
PHONE_2 = "device_tracker.work_iphone"

BEDROOM_TV = "media_player.bedroom"
LIVINGROOM_TV = "media_player.apple_tv_4k_livingroom"

# SET IN STONE: Workday detection windows (NEVER CHANGE)
PREWORK_MOTION_START = dt_time(4, 45)  # 04:45 pre-work hold window start
WORKDAY_MOTION_START = dt_time(4, 50)  # 04:50
WORKDAY_MOTION_END = dt_time(5, 0)     # 05:00 (exclusive)
MORNING_MOTION_WINDOW_END = dt_time(10, 0)

# SET IN STONE: Work ramp specifications
WORK_RAMP_START_BRIGHTNESS = 10  # 10%
WORK_RAMP_END_BRIGHTNESS = 50    # 50%
WORK_RAMP_START_TEMP = 2000      # 2000K
WORK_RAMP_END_TEMP = 4000         # 4000K
WORK_RAMP_END_TIME = dt_time(5, 40)  # Ramp ends at 05:40

# SET IN STONE: Non-work ramp specifications
NONWORK_RAMP_START_BRIGHTNESS = 10   # 10%
NONWORK_RAMP_START_TEMP = 2000       # 2000K
NONWORK_RAMP_END_TEMP = 5000         # 5000K (different from work ramp)

# SET IN STONE: Evening window and ramp (20:00→21:00)
EVENING_DEFAULT_CUTOFF = dt_time(23, 0)
EVENING_START_OFFSET_MINUTES = 15
BEDROOM_TV_DEBOUNCE_SECONDS = 5

EV_RAMP_START_TIME = dt_time(20, 0)
EV_RAMP_END_TIME = dt_time(21, 0)
EV_RAMP_START_K = 4000
EV_RAMP_END_K = 2000
EV_RAMP_BRI = 50  # Hold at 50%

# Night waiting timeout (start only after LR TV turns OFF post-23:00)
WAIT_FOR_BR_TV_TIMEOUT_MIN = 30

# SET IN STONE: Temperature-capable lights (Lamp One, Lamp Two, Closet Light)
TEMP_CAPABLE_LIGHTS = [
    "light.lamp_1",      # Lamp One
    "light.lamp_2",      # Lamp Two
    "light.closet",      # Closet Light
]

# SET IN STONE: Monthly elevation targets for Day mode
MONTHLY_ELEV_TARGET = {
    1:12, 2:11, 3:10, 4:9, 5:9, 6:8, 
    7:8, 8:9, 9:10, 10:11, 11:11, 12:12
}

# Notification targets for errors
NOTIFY_TARGETS = [
    "notify.mobile_app_rrvqklh23h_iphone"]

# Global state tracking
_morning_motion_classified_date = None
_morning_motion_profile = None
_work_ramp_task = None
_nonwork_ramp_task = None
_bedroom_tv_task = None
_evening_brightness_ramp_task = None
_waiting_timeout_task = None
_classification_lock = asyncio.Lock()
_cached_evening_start = None
_cached_day_min_start = None
_cached_day_elev_target = None
_cached_cutoff_hm = None
_ramp_service_warned = False
_day_ready_hysteresis_active = False
_day_ready_last_state = False
_day_ready_candidate_state = None
_day_ready_candidate_since = None

_suppress_home_state_trigger = False
_suppress_brightness_trigger = False

_missing_helper_notified: set[str] = set()

_DAY_READY_DEBOUNCE_SECONDS = 120  # 2 minute debounce for day readiness
_MISSING_HELPER_NOTIFICATION_ID = "hc_missing_helper"
_MAX_RAMP_RUNTIME = timedelta(hours=6)
_DEFAULT_DAY_FLOOR = dt_time(7, 30)

_MQTT_PREFIX = "home/controller"


def _offish(s: str) -> bool:
    s = (s or "").lower()
    return s in ("off", "unavailable", "unknown", "", "none")

# ============================================================================
# ERROR HANDLING
# ============================================================================
def _send_home_controller_error_alert(func_name: str, error: Exception, context_data: dict = None):
    """Send error notification to user"""
    tb_text = traceback.format_exc()
    timestamp = datetime.now().strftime("%H:%M:%S")
    message = f"""HOME CONTROLLER ERROR

FUNCTION: {func_name}
ERROR: {str(error)}
TIME: {timestamp}

CONTEXT DATA:
{context_data or 'None'}

TRACEBACK:
{tb_text[:1500]}"""
    
    for target in NOTIFY_TARGETS:
        try:
            domain, service_name = target.split(".", 1)
            service.call(domain, service_name, 
                        title=f"Home Controller Error [{timestamp}]", 
                        message=message[:1200])
        except Exception:
            pass
    
    try:
        service.call("persistent_notification", "create",
                    title=f"Home Controller Error [{timestamp}]",
                    message=message,
                    notification_id=f"hc_error_{datetime.now().timestamp()}")
    except Exception:
        pass
    
    log.error(f"[HOME_CONTROLLER_ERROR] {func_name}: {str(error)}")

def catch_hc_error(name: str):
    """Decorator for error catching and reporting - supports both sync and async functions"""
    def deco(fn):
        if asyncio.iscoroutinefunction(fn):
            # Async function wrapper
            async def async_wrap(*args, **kw):
                try:
                    return await fn(*args, **kw)
                except Exception as e:
                    context = {
                        "args": str(args)[:200],
                        "kwargs": str(kw)[:200],
                        "home_state": str(state.get("pyscript.home_state") or "unknown"),
                        "phone1": str(state.get(PHONE_1) or "unknown"),
                        "phone2": str(state.get(PHONE_2) or "unknown"),
                    }
                    _send_home_controller_error_alert(name, e, context)
                    raise
            return async_wrap
        else:
            # Sync function wrapper
            def sync_wrap(*args, **kw):
                try:
                    return fn(*args, **kw)
                except Exception as e:
                    context = {
                        "args": str(args)[:200],
                        "kwargs": str(kw)[:200],
                        "home_state": str(state.get("pyscript.home_state") or "unknown"),
                        "phone1": str(state.get(PHONE_1) or "unknown"),
                        "phone2": str(state.get(PHONE_2) or "unknown"),
                    }
                    _send_home_controller_error_alert(name, e, context)
                    raise
            return sync_wrap
    return deco

def catch_hc_trigger_error(name: str):
    """Decorator for triggers that logs errors but does not re-raise - supports both sync and async functions"""
    def deco(fn):
        if asyncio.iscoroutinefunction(fn):
            # Async function wrapper
            async def async_wrap(*args, **kw):
                try:
                    return await fn(*args, **kw)
                except Exception as e:
                    context = {
                        "args": str(args)[:200],
                        "kwargs": str(kw)[:200],
                        "home_state": str(state.get("pyscript.home_state") or "unknown"),
                        "trigger": name
                    }
                    _send_home_controller_error_alert(name, e, context)
                    log.error(f"[HC][TRIGGER_ERR] {name}: {e}")
                    return None
            return async_wrap
        else:
            # Sync function wrapper
            def sync_wrap(*args, **kw):
                try:
                    return fn(*args, **kw)
                except Exception as e:
                    context = {
                        "args": str(args)[:200],
                        "kwargs": str(kw)[:200],
                        "home_state": str(state.get("pyscript.home_state") or "unknown"),
                        "trigger": name
                    }
                    _send_home_controller_error_alert(name, e, context)
                    log.error(f"[HC][TRIGGER_ERR] {name}: {e}")
                    return None
            return sync_wrap
    return deco

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================
@catch_hc_error("_get")
def _get(entity_id: str, default=None, attr: str = None):
    """Safe entity state getter"""
    try:
        if attr:
            attrs = state.getattr(entity_id)
            return attrs.get(attr, default) if attrs else default
        v = state.get(entity_id)
        return v if v not in (None, "unknown", "unavailable") else default
    except Exception:
        return default

@catch_hc_error("_now")
def _now() -> datetime:
    """Get current time, honoring simulator freeze if active"""
    try:
        freeze_active = str(_get("input_boolean.time_freeze_active") or "off").lower()
        if freeze_active == "on":
            override = _get("input_datetime.time_freeze_clock")
            if override:
                override_str = str(override)
                try:
                    if "T" in override_str or " " in override_str:
                        override_dt = datetime.fromisoformat(override_str)
                    else:
                        fmt = "%H:%M:%S" if override_str.count(":") == 2 else "%H:%M"
                        parsed_time = datetime.strptime(override_str, fmt).time()
                        override_dt = datetime.combine(datetime.now().date(), parsed_time)
                    today = datetime.now()
                    return override_dt.replace(year=today.year, month=today.month, day=today.day)
                except Exception as exc:
                    log.warning(f"[HC] Invalid simulated time '{override_str}': {exc}")
    except Exception:
        pass
    return datetime.now()

def _today_str() -> str:
    """Get today's date as ISO string"""
    return date.today().isoformat()

@catch_hc_error("_set_sensor")
def _set_sensor(entity_id: str, value, attrs: dict = None):
    """Set sensor state"""
    state.set(entity_id, value, attrs or {})


def _mqtt_publish(path: str, payload: dict):
    """Controller MQTT disabled; mqtt_bridge.py handles all MQTT."""
    return


@catch_hc_error("_get_persisted_evening_window")
def _get_persisted_evening_window() -> datetime | None:
    """Retrieve persisted evening window data from sensor (survives restarts)."""
    try:
        # Try to get evening start from the sensor that persists across restarts
        evening_start_raw = _get("sensor.evening_start_local")
        if evening_start_raw and evening_start_raw not in ("", "unknown", "unavailable"):
            try:
                evening_start_dt = datetime.fromisoformat(str(evening_start_raw))
                # Check if it's for today
                now = _now()
                if evening_start_dt.date() == now.date():
                    log.info(f"[HC] Retrieved persisted evening window: {evening_start_dt.strftime('%H:%M:%S')}")
                    return evening_start_dt
                else:
                    log.info(f"[HC] Persisted evening window is for different date: {evening_start_dt.date()} vs {now.date()}")
            except Exception as e:
                log.warning(f"[HC] Could not parse persisted evening window '{evening_start_raw}': {e}")
        return None
    except Exception as e:
        log.debug(f"[HC] Could not retrieve persisted evening window: {e}")
        return None


@catch_hc_error("_get_cached_sunset")
def _get_cached_sunset() -> datetime | None:
    """Retrieve cached sunset data from MQTT (cached at noon)."""
    try:
        # Try to get cached sunset from MQTT
        # Note: This is a simplified version - in practice you'd need to implement
        # proper MQTT retrieval in Home Assistant
        cached_sunset_raw = _get("sensor.cached_sunset_time")
        if cached_sunset_raw and cached_sunset_raw not in ("", "unknown", "unavailable"):
            try:
                sunset_dt = datetime.fromisoformat(str(cached_sunset_raw))
                now = _now()
                if sunset_dt.date() == now.date():
                    log.info(f"[HC] Retrieved cached sunset: {sunset_dt.strftime('%H:%M:%S')}")
                    return sunset_dt
                else:
                    log.info(f"[HC] Cached sunset is for different date: {sunset_dt.date()} vs {now.date()}")
            except Exception as e:
                log.warning(f"[HC] Could not parse cached sunset '{cached_sunset_raw}': {e}")
        return None
    except Exception as e:
        log.debug(f"[HC] Could not retrieve cached sunset: {e}")
        return None


def _publish_em_contract():
    """Publish Early Morning contract for restart recovery"""
    route = str(_get("input_text.em_route_key") or "")
    start = str(_get("input_datetime.em_start_ts") or "")
    until = str(_get("input_text.em_until") or "")
    active = _get_boolean_state("em_active") == "on"
    payload = {
        "route": route,
        "start": start,
        "until": until,
        "active": active,
        "updated_at": _now().isoformat(),
        "version": 1,
    }
    _mqtt_publish("em/contract", payload)


@catch_hc_error("_set_em_status")
def _set_em_status(status: str, extra: dict = None):
    """Record EM status for diagnostics"""
    details = {
        "timestamp": _now().isoformat()
    }
    if extra:
        details.update({k: str(v) for k, v in extra.items()})
    _set_sensor("sensor.pys_em_status", status, details)

@catch_hc_error("_set_boolean_state")
def _set_boolean_state(suffix: str, value: str):
    """Set a binary sensor or input boolean state"""
    entities = [
        f"binary_sensor.{suffix}",
        f"input_boolean.{suffix}",
        f"pyscript.{suffix}"
    ]
    for e in entities:
        if _get(e) is not None:
            if e.startswith("input_boolean."):
                try:
                    service.call("input_boolean",
                                 "turn_on" if str(value).lower() == "on" else "turn_off",
                                 entity_id=e)
                except Exception as exc:
                    log.warning(f"[HC] Failed to toggle {e}: {exc}")
                    _set_sensor(e, value)
            else:
                _set_sensor(e, value)
            return
    _set_sensor(f"pyscript.{suffix}", value)

@catch_hc_error("_get_boolean_state")
def _get_boolean_state(suffix: str) -> str:
    """Get a binary sensor or input boolean state"""
    entities = [
        f"binary_sensor.{suffix}",
        f"input_boolean.{suffix}",
        f"pyscript.{suffix}"
    ]
    for e in entities:
        v = _get(e)
        if v is not None:
            return v
    return "off"


@catch_hc_error("_set_input_text")
def _set_input_text(entity_id: str, value: str):
    """Set an input_text helper"""
    try:
        service.call("input_text", "set_value",
                     entity_id=entity_id,
                     value=value if value is not None else "")
    except Exception as e:
        log.warning(f"[HC] Failed to set {entity_id}: {e}")


@catch_hc_error("_set_input_datetime")
def _set_input_datetime(entity_id: str, dt_value):
    """Set an input_datetime helper"""
    try:
        if isinstance(dt_value, datetime):
            dt_str = dt_value.strftime("%Y-%m-%d %H:%M:%S")
        elif isinstance(dt_value, str):
            dt_str = dt_value
        elif dt_value is None:
            # Clear by writing today's midnight
            dt_str = _now().replace(hour=0, minute=0, second=0, microsecond=0).strftime("%Y-%m-%d %H:%M:%S")
        else:
            dt_str = str(dt_value)
        service.call("input_datetime", "set_datetime",
                     entity_id=entity_id,
                     datetime=dt_str)
    except Exception as e:
        log.warning(f"[HC] Failed to set {entity_id}: {e}")


@catch_hc_error("_set_input_number")
def _set_input_number(entity_id: str, value):
    """Set an input_number helper"""
    try:
        service.call("input_number", "set_value",
                     entity_id=entity_id,
                     value=float(value if value is not None else 0))
    except Exception as e:
        log.warning(f"[HC] Failed to set {entity_id}: {e}")

def _are_both_phones_home() -> bool:
    """Check if both phones are home"""
    return _get(PHONE_1) == "home" and _get(PHONE_2) == "home"

def _is_any_phone_away() -> bool:
    """Check if any tracked phone is away"""
    return _get(PHONE_1) != "home" or _get(PHONE_2) != "home"


def _get_on_temp_capable_lights() -> list[str]:
    """Return temperature-capable lights that are currently on"""
    result = []
    for entity in TEMP_CAPABLE_LIGHTS:
        if str(_get(entity) or "off").lower() == "on":
            result.append(entity)
    return result


def _cancel_task_if_running(existing_task, name: str):
    """Cancel an existing asyncio task if it is still running"""
    try:
        if existing_task and not existing_task.done():
            log.info(f"[HC][DEBUG] Cancelling task {name} - task state: {existing_task._state if hasattr(existing_task, '_state') else 'unknown'}")
            existing_task.cancel()
            log.info(f"[HC][DEBUG] Successfully cancelled running task: {name}")
        elif existing_task:
            log.info(f"[HC][DEBUG] Task {name} already done, not cancelling")
        else:
            log.info(f"[HC][DEBUG] No existing task {name} to cancel")
    except Exception as e:
        log.warning(f"[HC][DEBUG] Failed to cancel task {name}: {e}")

@catch_hc_error("_notify_missing_helper")
def _notify_missing_helper(helper_name: str, fallback_desc: str):
    """Notify user about missing helper sensor with fallback description"""
    global _missing_helper_notified
    if helper_name in _missing_helper_notified:
        return
    _missing_helper_notified.add(helper_name)
    try:
        service.call(
            "persistent_notification",
            "create",
            title=f"Home Controller Helper Missing: {helper_name}",
            message=f"{helper_name} unavailable. Using fallback: {fallback_desc}",
            notification_id=f"{_MISSING_HELPER_NOTIFICATION_ID}_{helper_name}"
        )
    except Exception as e:
        log.warning(f"[HC] Could not send missing helper notification for {helper_name}: {e}")


def _clear_missing_helper_warning(helper_name: str):
    """Clear persistent notification tracking when helper recovers"""
    global _missing_helper_notified
    if helper_name in _missing_helper_notified:
        _missing_helper_notified.remove(helper_name)
        try:
            service.call(
                "persistent_notification",
                "dismiss",
                notification_id=f"{_MISSING_HELPER_NOTIFICATION_ID}_{helper_name}"
            )
        except Exception:
            pass

@catch_hc_error("_get_home_state")
def _get_home_state() -> str:
    """Get current home state"""
    v = _get("input_select.home_state")
    if v and v not in ("unknown", "unavailable"):
        return v
    return _get("pyscript.home_state", "Day")

@catch_hc_error("_set_home_state")
def _set_home_state(mode: str):
    """Set home state"""
    valid = ["Early Morning", "Day", "Evening", "Night", "Away"]
    if mode not in valid:
        log.error(f"[HC][DEBUG] Invalid mode attempted: {mode}")
        return False

    global _suppress_home_state_trigger

    current_state = _get_home_state()
    log.info(f"[HC][DEBUG] State change requested: {current_state} → {mode}")

    ts = _now()
    if not hasattr(ts, "isoformat"):
        try:
            ts = datetime.fromtimestamp(ts)
        except Exception:
            ts = datetime.now()

    state.set("pyscript.home_state", mode, {
        "friendly_name": "Home State (PyScript)",
        "icon": "mdi:home-clock",
        "options": valid,
        "last_updated": ts.isoformat()
    })

    if _get("input_select.home_state") not in (None, "unavailable"):
        # Try to sync input_select with retry logic
        sync_success = False
        for attempt in range(3):  # 3 retry attempts
            try:
                _suppress_home_state_trigger = True
                log.info(f"[HC][DEBUG] Setting input_select.home_state to {mode} (attempt {attempt + 1})")
                service.call("input_select", "select_option",
                            entity_id="input_select.home_state", option=mode)
                sync_success = True
                break
            except Exception as e:
                log.warning(f"[HC][DEBUG] Could not set input_select.home_state (attempt {attempt + 1}): {e}")
                if attempt < 2:  # Not the last attempt
                    time.sleep(0.1)  # Brief delay before retry
            finally:
                _suppress_home_state_trigger = False

        if not sync_success:
            log.error(f"[HC][DEBUG] SYNC FAILED: input_select.home_state out of sync with pyscript.home_state = {mode}")
        else:
            log.info(f"[HC][DEBUG] Successfully synced both entities to {mode}")

    log.info(f"[HC][DEBUG] Mode successfully changed: {current_state} → {mode}")
    return True

@catch_hc_error("_enter_evening")
def _enter_evening(reason: str, force: bool = False) -> bool:
    """Enter Evening mode honoring locks and window"""
    if not force:
        if _get_home_state() == "Away":
            return False
        if _get("binary_sensor.in_evening_window") != "on":
            return False
        if _get_boolean_state("evening_done_today") == "on":
            return False
    
    current_state = _get_home_state()
    if current_state != "Evening":
        _set_home_state("Evening")

    _set_boolean_state("evening_mode_active", "on")
    _set_sensor("sensor.evening_last_reason", reason, {
        "friendly_name": "Evening Last Reason",
        "timestamp": _now().isoformat()
    })
    _set_last_action(f"evening_mode_started:{reason}")
    return True

@catch_hc_error("_end_evening")
def _end_evening(reason: str, mark_done: bool):
    """Clear evening lock and optionally mark evening done"""
    if _get_boolean_state("evening_mode_active") == "on":
        _set_boolean_state("evening_mode_active", "off")
    if mark_done:
        _set_boolean_state("evening_done_today", "on")
    if reason:
        _set_sensor("sensor.evening_last_reason", f"ended:{reason}", {
            "friendly_name": "Evening Last Reason",
            "timestamp": _now().isoformat()
        })

@catch_hc_error("_set_last_action")
def _set_last_action(msg: str):
    """Record last action for debugging"""
    ts = _now().strftime("%Y-%m-%d %H:%M:%S")
    prev_attrs = state.getattr("sensor.pys_last_action") or {}
    history = prev_attrs.get("history") or []
    if not isinstance(history, list):
        history = []
    history = (history + [f"{msg}@{ts}"])[-5:]
    state.set("sensor.pys_last_action", f"{msg} @ {ts}", {
        "friendly_name": "Home Controller Last Action",
        "icon": "mdi:clock-check",
        "timestamp": ts,
        "action": msg,
        "history": history
    })

@catch_hc_error("_mark_em_end")
def _mark_em_end(reason: str):
    """Mark Early Morning end with reason"""
    ts = _now().replace(microsecond=0).isoformat()
    state.set("sensor.pys_em_end_reason", reason, {"friendly_name":"EM End Reason"})
    state.set("sensor.pys_em_end_time", ts, {"friendly_name":"EM End Time"})
    _set_boolean_state("em_active", "off")
    _set_em_status("em_ended", {"reason": reason})
    _publish_em_contract()

@catch_hc_error("_is_controller_enabled")
def _is_controller_enabled() -> bool:
    """Check if controller is enabled"""
    v = state.get("pyscript.controller_enabled")
    if v in ("on","off"): return v == "on"
    v2 = state.get("input_boolean.use_pyscript_home_state")
    if v2 in ("on","off"): return v2 == "on"
    return True

@catch_hc_error("_get_evening_cutoff_time")
def _get_evening_cutoff_time() -> dt_time:
    """Get evening cutoff time from configuration"""
    cutoff = (_get("input_datetime.evening_time_cutoff") or
              _get("pyscript.evening_time_cutoff") or
              "23:00:00")
    try:
        s = str(cutoff)
        if "T" in s:
            return datetime.fromisoformat(s).time()
        parts = s.split(":")
        h = int(parts[0]); m = int(parts[1]) if len(parts)>1 else 0
        return dt_time(h, m, 0)
    except Exception as e:
        log.warning(f"[HC] Bad evening cutoff '{cutoff}': {e}; defaulting 23:00")
        return EVENING_DEFAULT_CUTOFF

@catch_hc_error("_get_day_earliest_time_floor")
def _get_day_earliest_time_floor() -> dt_time:
    """Get Day earliest time floor (default 07:30)"""
    floor = _get("input_datetime.day_earliest_time") or _get("pyscript.day_earliest_time") or "07:30:00"
    try:
        s = str(floor)
        if "T" in s:
            result = datetime.fromisoformat(s).time()
        else:
            parts = s.split(":")
            h = int(parts[0]); m = int(parts[1]) if len(parts) > 1 else 0
            result = dt_time(h, m, 0)
        _set_sensor("sensor.day_earliest_time", result.strftime("%H:%M:%S"))
        return result
    except Exception:
        fallback = dt_time(7, 30, 0)
        _set_sensor("sensor.day_earliest_time", fallback.strftime("%H:%M:%S"))
        return fallback

# ============================================================================
# MORNING RAMPS - SET IN STONE
# ============================================================================
@catch_hc_error("_calculate_ramp_brightness")
def _calculate_ramp_brightness(start_time: datetime, end_time: datetime, 
                               start_val: int, end_val: int) -> int:
    """Calculate current ramp brightness based on time"""
    now = _now()
    if now <= start_time:
        return start_val
    if now >= end_time:
        return end_val
    total_duration = (end_time - start_time).total_seconds()
    if total_duration <= 0:
        return end_val
    elapsed = (now - start_time).total_seconds()
    progress = elapsed / total_duration
    
    current = start_val + (end_val - start_val) * progress
    return int(round(current))

@catch_hc_error("_calculate_ramp_kelvin")
def _calculate_ramp_kelvin(start_time: datetime, end_time: datetime,
                             start_k: int, end_k: int) -> int:
    """Calculate current ramp color temperature based on time"""
    now = _now()
    if now <= start_time:
        return start_k
    if now >= end_time:
        return end_k

    total_duration = (end_time - start_time).total_seconds()
    if total_duration <= 0:
        return end_k
    elapsed = (now - start_time).total_seconds()
    progress = elapsed / total_duration

    current = start_k + (end_k - start_k) * progress
    return int(round(current))


def _calculate_ramp_progress(start_time: datetime, end_time: datetime) -> int:
    """Return ramp progress percentage between start and end"""
    now = _now()
    total = (end_time - start_time).total_seconds()
    if total <= 0:
        return 100
    if now <= start_time:
        return 0
    if now >= end_time:
        return 100
    return int(round(((now - start_time).total_seconds() / total) * 100))


def _set_ramp_temperature(value: int, attrs: dict | None = None):
    """Set both kelvin and legacy temperature sensors for ramp outputs"""
    _set_sensor("sensor.sleep_in_ramp_kelvin", value, attrs)

    temp_attrs = dict(attrs or {})
    friendly = temp_attrs.get("friendly_name")
    if isinstance(friendly, str):
        if "Kelvin" in friendly:
            temp_attrs["friendly_name"] = friendly.replace("Kelvin", "Temperature")
        else:
            temp_attrs["friendly_name"] = friendly
    else:
        temp_attrs["friendly_name"] = "Morning Ramp Temperature"

    temp_attrs.setdefault("unit_of_measurement", "K")
    _set_sensor("sensor.sleep_in_ramp_temperature", value, temp_attrs)


def _mirror_ramp_helpers(start_time: datetime, end_time: datetime, ramp_type: str):
    """Keep legacy helpers in sync for dashboards/tests"""
    duration_minutes = max(1, int((end_time - start_time).total_seconds() / 60))
    start_str = start_time.strftime("%Y-%m-%d %H:%M:%S")
    end_str = end_time.strftime("%Y-%m-%d %H:%M:%S")

    try:
        service.call("input_datetime", "set_datetime",
                     entity_id="input_datetime.ramp_start_time",
                     datetime=start_str)
    except Exception:
        pass

    try:
        service.call("input_datetime", "set_datetime",
                     entity_id="input_datetime.ramp_calculated_end_time",
                     datetime=end_str)
    except Exception:
        pass

    try:
        service.call("input_number", "set_value",
                     entity_id="input_number.calculated_ramp_duration",
                     value=duration_minutes)
    except Exception:
        pass

    progress = _calculate_ramp_progress(start_time, end_time)
    _set_sensor("sensor.sleep_in_ramp_progress", progress, {
        "friendly_name": "Morning Ramp Progress",
        "unit_of_measurement": "%",
        "ramp_type": ramp_type,
        "start_time": start_str,
        "end_time": end_str
    })

@catch_hc_error("_start_work_ramp")
async def _start_work_ramp(restore_from_time=None):
    """
    SET IN STONE: Work ramp 10%/2000K → 50%/4000K until 05:40
    """
    global _work_ramp_task
    
    # Determine start time - use restore time if provided (after restart)
    now = _now()
    resume_mode = bool(restore_from_time)
    if resume_mode:
        if isinstance(restore_from_time, str):
            try:
                start_time = datetime.fromisoformat(str(restore_from_time))
            except Exception:
                start_time = now
        else:
            start_time = restore_from_time
    else:
        start_time = now

    if not isinstance(start_time, datetime):
        try:
            start_time = datetime.fromisoformat(str(start_time))
        except Exception:
            start_time = now

    if start_time.tzinfo is not None:
        start_time = start_time.replace(tzinfo=None)
    start_time = start_time.replace(microsecond=0)

    end_time = start_time.replace(hour=5, minute=40, second=0, microsecond=0)
    if end_time <= start_time:
        log.warning(
            f"[HC] WORK RAMP: Computed end {end_time.strftime('%H:%M')} is not after start"
            "; clamping to start time"
        )
        end_time = start_time

    if resume_mode:
        log.info(
            f"[HC] WORK RAMP: Resuming from {start_time.strftime('%H:%M')} → 50%/4000K until {end_time.strftime('%H:%M')}"
        )
    else:
        log.info(
            f"[HC] WORK RAMP: Starting 10% → 50%/4000K until {end_time.strftime('%H:%M')}"
        )
    _set_sensor("sensor.pys_em_start_time", start_time.isoformat(), {
        "friendly_name": "Early Morning Start Time"
    })

    _set_boolean_state("em_active", "on")
    _set_input_datetime("input_datetime.em_start_ts", start_time)
    _set_input_text("input_text.em_until", end_time.strftime("%Y-%m-%d %H:%M:%S"))

    # Set initial state
    _set_boolean_state("sleep_in_ramp_active", "on")

    _mirror_ramp_helpers(start_time, end_time, "work")
    _set_em_status("work_ramp_active", {
        "start": start_time.strftime('%H:%M:%S'),
        "end": end_time.strftime('%H:%M:%S')
    })
    _publish_em_contract()

    # Calculate initial values based on actual start time
    initial_brightness = _calculate_ramp_brightness(
        start_time, end_time,
        WORK_RAMP_START_BRIGHTNESS, WORK_RAMP_END_BRIGHTNESS
    )
    initial_kelvin = _calculate_ramp_kelvin(
        start_time, end_time,
        WORK_RAMP_START_TEMP, WORK_RAMP_END_TEMP
    )
    _set_sensor("sensor.sleep_in_ramp_brightness", initial_brightness)
    _set_ramp_temperature(initial_kelvin)
    log.info(f"[HC] WORK RAMP: Initial values: {initial_brightness}% / {initial_kelvin}K")
    
    hard_stop = start_time + _MAX_RAMP_RUNTIME
    timed_out = False

    # Ramp loop until 05:40 or timeout
    while True:
        current_now = _now()
        if current_now >= end_time:
            break
        if current_now >= hard_stop:
            timed_out = True
            log.error(f"[HC] WORK RAMP: Exceeded max runtime {_MAX_RAMP_RUNTIME}; forcing completion")
            break
        # Calculate current values
        current_brightness = _calculate_ramp_brightness(
            start_time, end_time,
            WORK_RAMP_START_BRIGHTNESS, WORK_RAMP_END_BRIGHTNESS
        )
        current_kelvin = _calculate_ramp_kelvin(
            start_time, end_time,
            WORK_RAMP_START_TEMP, WORK_RAMP_END_TEMP
        )
        
        # Update sensors for other rooms to use
        _set_sensor("sensor.sleep_in_ramp_brightness", current_brightness, {
            "friendly_name": "Morning Ramp Brightness",
            "unit_of_measurement": "%",
            "ramp_type": "work",
            "target": WORK_RAMP_END_BRIGHTNESS,
            "end_time": end_time.isoformat(),
            "start_time": start_time.isoformat()
        })
        _set_ramp_temperature(current_kelvin, {
            "friendly_name": "Morning Ramp Kelvin",
            "unit_of_measurement": "K",
            "ramp_type": "work",
            "target": WORK_RAMP_END_TEMP,
            "end_time": end_time.isoformat(),
            "start_time": start_time.isoformat()
        })

        _set_sensor("sensor.sleep_in_ramp_progress", _calculate_ramp_progress(start_time, end_time), {
            "friendly_name": "Morning Ramp Progress",
            "unit_of_measurement": "%",
            "ramp_type": "work",
            "target": WORK_RAMP_END_BRIGHTNESS,
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat()
        })

        log.info(f"[HC] WORK RAMP: {current_brightness}% / {current_kelvin}K")

        # Wait 30 seconds before next update
        await asyncio.sleep(30)

    if timed_out:
        log.warning("[HC] WORK RAMP: Timeout reached; finalizing ramp early")

    # Ramp complete - hold at final values
    _set_sensor("sensor.sleep_in_ramp_brightness", WORK_RAMP_END_BRIGHTNESS)
    _set_ramp_temperature(WORK_RAMP_END_TEMP)
    _set_sensor("sensor.sleep_in_ramp_progress", 100, {
        "friendly_name": "Morning Ramp Progress",
        "unit_of_measurement": "%",
        "ramp_type": "work",
        "start_time": start_time.isoformat(),
        "end_time": end_time.isoformat()
    })
    _set_em_status("work_ramp_complete", {
        "end": end_time.strftime('%H:%M:%S')
    })
    _publish_em_contract()
    log.info(f"[HC] WORK RAMP: Complete, holding at {WORK_RAMP_END_BRIGHTNESS}% / {WORK_RAMP_END_TEMP}K")
    
    # After 05:40, stay in Early Morning at final levels until phones go Away
    # Do NOT change mode or turn off lights

@catch_hc_error("_start_nonwork_ramp")
async def _start_nonwork_ramp(start_time_override=None):
    """
    SET IN STONE: Non-work ramp 10%/2000K → dynamic%/5000K until Day commit
    """
    global _nonwork_ramp_task
    
    # Get Day commit time (when Day mode should start)
    commit_dt = _compute_day_commit_time()
    if not commit_dt:
        log.error("[HC] NONWORK RAMP: No Day commit time available")
        return
    
    # Get target brightness from priority stack
    target_brightness, source = _resolve_day_target_brightness()
    
    log.info(f"[HC] NONWORK RAMP: Starting 10%/2000K → {target_brightness}%/5000K until {commit_dt.strftime('%H:%M')}")
    
    now = _now()
    override_mode = bool(start_time_override)
    if override_mode:
        if isinstance(start_time_override, str):
            try:
                start_time = datetime.fromisoformat(str(start_time_override))
            except Exception:
                start_time = now
        else:
            start_time = start_time_override
    else:
        start_time = now

    if not isinstance(start_time, datetime):
        try:
            start_time = datetime.fromisoformat(str(start_time_override))
        except Exception:
            start_time = now

    if start_time.tzinfo is not None:
        start_time = start_time.replace(tzinfo=None)
    start_time = start_time.replace(microsecond=0)
    end_time = commit_dt
    if not end_time:
        log.error("[HC] NONWORK RAMP: Missing Day commit time; aborting ramp")
        return
    if not isinstance(end_time, datetime):
        try:
            end_time = datetime.fromisoformat(str(end_time))
        except Exception as exc:
            log.error(f"[HC] NONWORK RAMP: Invalid commit time '{commit_dt}': {exc}")
            return
    if end_time.tzinfo is not None:
        end_time = end_time.replace(tzinfo=None)
    end_time = end_time.replace(microsecond=0)
    if end_time <= start_time:
        log.warning(
            f"[HC] NONWORK RAMP: Commit {end_time.strftime('%H:%M')} is not after start"
            "; clamping to start time"
        )
        end_time = start_time

    _set_boolean_state("em_active", "on")
    _set_input_datetime("input_datetime.em_start_ts", start_time)
    _set_input_text("input_text.em_until", end_time.strftime("%Y-%m-%d %H:%M:%S"))

    # Set initial state
    _set_boolean_state("sleep_in_ramp_active", "on")
    _mirror_ramp_helpers(start_time, end_time, "nonwork")
    _set_em_status("day_off_ramp_active", {
        "start": start_time.strftime('%H:%M:%S'),
        "end": end_time.strftime('%H:%M:%S'),
        "target": target_brightness,
        "source": source
    })
    _publish_em_contract()
    _set_sensor("sensor.pys_em_start_time", start_time.isoformat(), {
        "friendly_name": "Early Morning Start Time"
    })

    # Calculate and publish the initial ramp values (supports resume scenarios)
    initial_brightness = _calculate_ramp_brightness(
        start_time, end_time,
        NONWORK_RAMP_START_BRIGHTNESS, target_brightness
    )
    initial_kelvin = _calculate_ramp_kelvin(
        start_time, end_time,
        NONWORK_RAMP_START_TEMP, NONWORK_RAMP_END_TEMP
    )

    brightness_attrs = {
        "friendly_name": "Morning Ramp Brightness",
        "unit_of_measurement": "%",
        "ramp_type": "nonwork",
        "target": target_brightness,
        "source": source,
        "end_time": end_time.isoformat()
    }
    _set_sensor("sensor.sleep_in_ramp_brightness", initial_brightness, brightness_attrs)

    kelvin_attrs = {
        "friendly_name": "Morning Ramp Kelvin",
        "unit_of_measurement": "K",
        "ramp_type": "nonwork",
        "target": NONWORK_RAMP_END_TEMP,
        "end_time": end_time.isoformat()
    }
    _set_ramp_temperature(initial_kelvin, kelvin_attrs)
    log.info(f"[HC] NONWORK RAMP: Initial values: {initial_brightness}% / {initial_kelvin}K")

    hard_stop = start_time + _MAX_RAMP_RUNTIME
    timed_out = False

    # Ramp loop until Day commit time or timeout
    while True:
        current_now = _now()
        if current_now >= end_time:
            break
        if current_now >= hard_stop:
            timed_out = True
            log.error(f"[HC] NONWORK RAMP: Exceeded max runtime {_MAX_RAMP_RUNTIME}; forcing completion")
            break
        # Calculate current values
        current_brightness = _calculate_ramp_brightness(
            start_time, end_time,
            NONWORK_RAMP_START_BRIGHTNESS, target_brightness
        )
        current_kelvin = _calculate_ramp_kelvin(
            start_time, end_time,
            NONWORK_RAMP_START_TEMP, NONWORK_RAMP_END_TEMP
        )
        
        # Update sensors
        _set_sensor("sensor.sleep_in_ramp_brightness", current_brightness, {
            "friendly_name": "Morning Ramp Brightness",
            "unit_of_measurement": "%",
            "ramp_type": "nonwork",
            "target": target_brightness,
            "source": source,
            "end_time": end_time.isoformat()
        })
        _set_ramp_temperature(current_kelvin, {
            "friendly_name": "Morning Ramp Kelvin",
            "unit_of_measurement": "K",
            "ramp_type": "nonwork",
            "target": NONWORK_RAMP_END_TEMP,
            "end_time": end_time.isoformat()
        })

        _set_sensor("sensor.sleep_in_ramp_progress", _calculate_ramp_progress(start_time, end_time), {
            "friendly_name": "Morning Ramp Progress",
            "unit_of_measurement": "%",
            "ramp_type": "nonwork",
            "target": target_brightness,
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat()
        })

        log.info(f"[HC] NONWORK RAMP: {current_brightness}% / {current_kelvin}K")

        # Wait 30 seconds before next update
        await asyncio.sleep(30)

    if timed_out:
        log.warning("[HC] NONWORK RAMP: Timeout reached; finalizing ramp early")

    # Ramp complete - transition to Day mode
    _set_sensor("sensor.sleep_in_ramp_brightness", target_brightness)
    _set_ramp_temperature(NONWORK_RAMP_END_TEMP)
    _set_boolean_state("sleep_in_ramp_active", "off")
    _set_sensor("sensor.sleep_in_ramp_progress", 100, {
        "friendly_name": "Morning Ramp Progress",
        "unit_of_measurement": "%",
        "ramp_type": "nonwork",
        "target": target_brightness,
        "start_time": start_time.isoformat(),
        "end_time": end_time.isoformat()
    })

    # Seamless handoff to Day mode
    _set_home_state("Day")
    _mark_em_end("nonwork_ramp_complete")
    _set_last_action("nonwork_ramp_to_day")
    _set_em_status("day_off_ramp_complete", {
        "end": end_time.strftime('%H:%M:%S')
    })
    _publish_em_contract()
    log.info(f"[HC] NONWORK RAMP: Complete, transitioned to Day at {target_brightness}% / {NONWORK_RAMP_END_TEMP}K")

@catch_hc_error("_enforce_workday_ramp_end")
def _enforce_workday_ramp_end():
    """Ensure workday ramps always target 05:40"""
    if _get_boolean_state("sleep_in_ramp_active") != "on":
        return

    profile = _morning_motion_profile or str(_get("sensor.pys_morning_ramp_profile") or "")
    if profile != "work":
        return

    now = _now()
    if now.time() >= WORK_RAMP_END_TIME:
        return

    start_raw = _get("input_datetime.ramp_start_time") or _get("sensor.pys_em_start_time")
    try:
        start_dt = datetime.fromisoformat(str(start_raw).replace("Z", "")) if start_raw else None
    except Exception:
        start_dt = None
    if not start_dt:
        return

    desired_end = now.replace(hour=WORK_RAMP_END_TIME.hour,
                              minute=WORK_RAMP_END_TIME.minute,
                              second=0,
                              microsecond=0)
    if desired_end <= start_dt:
        desired_end = start_dt.replace(hour=WORK_RAMP_END_TIME.hour,
                                       minute=WORK_RAMP_END_TIME.minute,
                                       second=0,
                                       microsecond=0)

    current_end_raw = _get("input_datetime.ramp_calculated_end_time")
    try:
        current_end_dt = datetime.fromisoformat(str(current_end_raw).replace("Z", "")) if current_end_raw else None
    except Exception:
        current_end_dt = None

    if not current_end_dt or abs((current_end_dt - desired_end).total_seconds()) > 30:
        _mirror_ramp_helpers(start_dt, desired_end, "work")

# ============================================================================
# ENTITY INITIALIZATION
# ============================================================================
@catch_hc_error("_ensure_entities")
def _ensure_entities():
    """Ensure all required entities exist"""
    if _get("pyscript.home_state") is None:
        _set_home_state("Day")
    
    entities_to_init = [
        ("sensor.night_started_on", ""),
        ("binary_sensor.pys_night_cutover_pending", "off"),
        ("sensor.day_earliest_time", "07:30:00"),
        ("sensor.day_min_start", ""),
        ("sensor.day_elev_target", 0),
        ("binary_sensor.day_ready_now", "off"),
        ("sensor.day_ready_reason", ""),
        ("sensor.evening_start_local", ""),
        ("binary_sensor.in_evening_window", "off"),
        ("sensor.day_commit_time", ""),
        ("sensor.day_target_brightness", 70),
        ("sensor.pys_morning_ramp_profile", "unknown"),
        ("sensor.pys_morning_ramp_reason", ""),
        ("sensor.pys_em_start_time", ""),
        ("sensor.pys_em_classification_time", ""),
        ("sensor.pys_em_end_reason", ""),
        ("sensor.pys_em_end_time", ""),
        ("pyscript.motion_work_day_detected", "off"),
        ("pyscript.evening_ramp_started_today", "off"),
        ("pyscript.evening_done_today", "off"),
        ("pyscript.evening_mode_active", "off"),
        ("binary_sensor.pys_evening_preramp_active", "off"),
        ("sensor.pys_evening_preramp_start_time", ""),
        ("sensor.evening_last_reason", ""),
        ("sensor.sleep_in_ramp_brightness", 10),
        ("sensor.sleep_in_ramp_kelvin", 2000),
        ("sensor.sleep_in_ramp_temperature", 2000),
        ("input_boolean.sleep_in_ramp_active", "off"),
        ("pyscript.sleep_in_ramp_active", "off"),
        ("sensor.night_last_reason", ""),
        ("sensor.learned_day_start", ""),
        ("sensor.day_learned_start", ""), 
        ("sensor.day_target_brightness_teaching", 70),
        ("sensor.day_target_brightness_adaptive", 70),
        ("sensor.day_target_brightness_intelligent", 70),
        ("pyscript.day_target_brightness_fallback", 70)]
    
    for eid, val in entities_to_init:
        if _get(eid) is None:
            _set_sensor(eid, val)
    
    if _get("pyscript.controller_enabled") is None:
        _set_sensor("pyscript.controller_enabled","on", {"friendly_name":"Home Controller Enabled"})

@catch_hc_error("_init_brightness_system")
def _init_brightness_system():
    """Initialize brightness target sensors with proper attributes"""
    
    # Teaching sensor (user manual overrides)
    if _get("sensor.day_target_brightness_teaching") is None:
        _set_sensor("sensor.day_target_brightness_teaching", "", {
            "friendly_name": "Day Target Brightness (Teaching)",
            "unit_of_measurement": "%",
            "priority": 1,
            "description": "Manual brightness teaching overrides"
        })
    
    # Adaptive sensor (learned from user behavior) 
    if _get("sensor.day_target_brightness_adaptive") is None:
        _set_sensor("sensor.day_target_brightness_adaptive", "", {
            "friendly_name": "Day Target Brightness (Adaptive)",
            "unit_of_measurement": "%", 
            "priority": 2,
            "description": "Brightness learned from user patterns"
        })
    
    # Intelligent sensor (ML/algorithm based)
    if _get("sensor.day_target_brightness_intelligent") is None:
        _set_sensor("sensor.day_target_brightness_intelligent", "", {
            "friendly_name": "Day Target Brightness (Intelligent)",
            "unit_of_measurement": "%",
            "priority": 3, 
            "description": "Algorithm-calculated brightness"
        })

@catch_hc_error("_init_day_start_sensors") 
def _init_day_start_sensors():
    """Initialize day start learning sensors"""
    
    if _get("sensor.learned_day_start") is None:
        _set_sensor("sensor.learned_day_start", "", {
            "friendly_name": "Learned Day Start Time",
            "description": "Machine learned optimal day start time"
        })
        
    if _get("sensor.day_learned_start") is None:
        _set_sensor("sensor.day_learned_start", "", {
            "friendly_name": "Day Learned Start (Alt)",
            "description": "Alternative learned day start sensor"
        })

# ============================================================================
# KITCHEN MOTION - COORDINATED CLASSIFICATION
# ============================================================================
@catch_hc_error("_coordinated_kitchen_motion_classification")
async def _coordinated_kitchen_motion_classification(entity_id: str):
    """Coordinated kitchen motion classification - prevents race with lighting"""

    # Check if kitchen lighting is currently being processed
    kitchen_motion_active = str(_get("binary_sensor.kitchen_motion_active") or "off").lower() == "on"

    log.info(f"[HC][DEBUG] Coordinated classification check for {entity_id} - kitchen_motion_active: {kitchen_motion_active}")

    if kitchen_motion_active:
        # Lighting is active - wait briefly to avoid race condition
        log.info(f"[HC][DEBUG] Kitchen lighting active - delaying classification by 100ms for {entity_id}")
        await asyncio.sleep(0.1)  # 100ms delay
        log.info(f"[HC][DEBUG] Delay complete, proceeding with classification for {entity_id}")

    # Now safe to run classification
    log.info(f"[HC][DEBUG] Calling _classify_kitchen_motion for {entity_id}")
    await _classify_kitchen_motion(entity_id)

# ============================================================================
# EARLY MORNING MODE - SET IN STONE
# ============================================================================
@catch_hc_error("_classify_kitchen_motion")
async def _classify_kitchen_motion(entity_id: str):
    """
    SET IN STONE: Kitchen motion classification
    - Kitchen motion 04:50-05:00 = WORKDAY
    - Kitchen motion >=05:00 = DAY OFF
    - Only kitchen motion starts Early Morning mode
    """
    global _morning_motion_classified_date, _morning_motion_profile, _work_ramp_task, _nonwork_ramp_task

    log.info(f"[HC][DEBUG] Kitchen motion classification triggered by: {entity_id}")
    log.info(f"[HC][DEBUG] Current state before classification: home_state={_get_home_state()}, motion_lock={_get_boolean_state('daily_motion_lock')}")
    log.info(f"[HC][DEBUG] Current classification state: date={_morning_motion_classified_date}, profile={_morning_motion_profile}")

    async with _classification_lock:
        log.info(f"[HC][DEBUG] Acquired classification lock for {entity_id}")
        if not entity_id:
            log.info(f"[HC][DEBUG] No entity_id provided, returning")
            return

        now = _now()
        current_time = now.time()

        # Skip if Away mode or daily lock active
        if _get_home_state() == "Away":
            log.info(f"[HC][DEBUG] Kitchen motion ignored - Away mode")
            return
        if _get_boolean_state("daily_motion_lock") == "on":
            log.info("[HC][DEBUG] Kitchen motion ignored - daily motion lock active")
            return

        # Skip if already classified today (persisted or in-memory)
        if _morning_motion_classified_date == now.date():
            log.info(f"[HC][DEBUG] Kitchen motion ignored - already classified today as {_morning_motion_profile}")
            return

        existing_classification = _get("sensor.pys_em_classification_time")
        if existing_classification:
            try:
                existing_dt = datetime.fromisoformat(str(existing_classification))
                if existing_dt.date() == now.date():
                    existing_profile = _get("sensor.pys_morning_ramp_profile")
                    if existing_profile in ("work", "day_off"):
                        _morning_motion_profile = existing_profile
                    _morning_motion_classified_date = existing_dt.date()
                    log.info(f"[HC] Kitchen motion ignored - persistent classification already set to {_morning_motion_profile}")
                    return
            except Exception as err:
                log.warning(f"[HC] Could not parse existing classification '{existing_classification}': {err}")
        
        # Only process motion between 04:45 and 10:00
        if current_time < PREWORK_MOTION_START or current_time >= MORNING_MOTION_WINDOW_END: 
            log.info(f"[HC] Kitchen motion at {current_time.strftime('%H:%M')} - outside window")
            return

        # SET IN STONE: Classification logic
        prework = PREWORK_MOTION_START <= current_time < WORKDAY_MOTION_START
        work_window = WORKDAY_MOTION_START <= current_time < WORKDAY_MOTION_END
        workday = prework or work_window
        profile = "work" if workday else "day_off"

        override = str(_get("input_select.morning_day_type_override") or "auto").lower()
        if override in ("work", "day_off"):
            profile = override
            workday = override == "work"
            prework = prework if workday else False
        
        # Mark as classified for today
        _morning_motion_classified_date = now.date()
        _morning_motion_profile = profile
        
        log.info(f"[HC] *** KITCHEN MOTION DETECTED at {current_time.strftime('%H:%M:%S')} ***")
        log.info(f"[HC] *** CLASSIFICATION: {profile.upper()} ***")

        _set_em_status("classified", {
            "route": profile,
            "prework": prework,
            "entity": entity_id,
            "time": current_time.strftime('%H:%M:%S')
        })
        _publish_em_contract()

        # Set all the sensors
        _set_sensor("sensor.pys_morning_ramp_profile", profile, {
            "source": entity_id, 
            "reason": f"motion@{now.strftime('%H:%M')}",
            "classified_at": now.isoformat()
        })
        _set_sensor("sensor.pys_em_classification_time", now.isoformat(), {
            "friendly_name": "Early Morning Classification Time"
        })
        _set_sensor("pyscript.motion_work_day_detected", "on" if workday else "off")
        reason_suffix = f"motion@{now.strftime('%H:%M')}"
        if prework:
            reason_suffix = "prework_hold"
        if override in ("work", "day_off"):
            reason_suffix = f"override_{override}"
        _set_sensor("sensor.pys_morning_ramp_reason", f"{entity_id} @ {reason_suffix}")

        _set_input_text("input_text.em_route_key", profile)
        _set_input_datetime("input_datetime.em_start_ts", now)
        _set_input_text("input_text.em_until", "")
        _set_boolean_state("em_active", "on")

        try:
            service.call("input_datetime", "set_datetime",
                         entity_id="input_datetime.first_kitchen_motion_today",
                         datetime=now.strftime("%Y-%m-%d %H:%M:%S"))
        except Exception:
            pass

        _set_boolean_state("daily_motion_lock", "on")
        
        # SET IN STONE: Set Early Morning mode IMMEDIATELY
        log.info(f"[HC][DEBUG] Setting EARLY MORNING mode for profile: {profile}")
        _set_home_state("Early Morning")
        _set_last_action(f"kitchen_motion_{profile}→Early_Morning")

        # Start the appropriate ramp
        classification_time = now
        if prework:
            classification_time = now.replace(hour=WORKDAY_MOTION_START.hour,
                                              minute=WORKDAY_MOTION_START.minute,
                                              second=0,
                                              microsecond=0)

        log.info(f"[HC][DEBUG] Starting ramp for profile {profile} at time {classification_time.strftime('%H:%M:%S')}")
        if workday:
            # Start work ramp (10% → 50% until 05:40)
            log.info(f"[HC][DEBUG] Cancelling existing tasks before starting work ramp")
            _cancel_task_if_running(_work_ramp_task, "work_ramp")
            _cancel_task_if_running(_nonwork_ramp_task, "nonwork_ramp")
            log.info(f"[HC][DEBUG] Creating work ramp task")
            _work_ramp_task = task.create(_start_work_ramp(restore_from_time=classification_time))
        else:
            # Start non-work ramp (10% → dynamic% until Day commit)
            log.info(f"[HC][DEBUG] Cancelling existing tasks before starting nonwork ramp")
            _cancel_task_if_running(_nonwork_ramp_task, "nonwork_ramp")
            _cancel_task_if_running(_work_ramp_task, "work_ramp")

            # SAFETY: Validate commit time exists before creating task
            try:
                test_commit = _compute_day_commit_time()
                if test_commit:
                    log.info(f"[HC][DEBUG] Creating nonwork ramp task - commit time: {test_commit.strftime('%H:%M')}")
                    _nonwork_ramp_task = task.create(_start_nonwork_ramp(start_time_override=classification_time))
                else:
                    log.error("[HC] Cannot start nonwork ramp - no valid commit time available")
                    _set_boolean_state("sleep_in_ramp_active", "off")
                    _set_sensor("sensor.sleep_in_ramp_brightness", 10)
                    _set_ramp_temperature(2000)
            except Exception as e:
                log.error(f"[HC] Failed to start nonwork ramp: {e}")
                _set_boolean_state("sleep_in_ramp_active", "off")

        log.info(f"[HC][DEBUG] Classification complete - profile: {profile}, tasks created")

# ============================================================================
# DAILY CONSTANTS CACHING
# ============================================================================
@catch_hc_error("_refresh_daily_constants")
def _refresh_daily_constants():
    """Compute daily constants once per day"""
    global _cached_evening_start, _cached_day_min_start, _cached_day_elev_target, _cached_cutoff_hm

    # Cache cutoff time
    cutoff = _get_evening_cutoff_time()
    _cached_cutoff_hm = (cutoff.hour, cutoff.minute)

    now = _now()

    # Try to retrieve persisted evening window data first (survives restarts)
    persisted_evening_start = _get_persisted_evening_window()
    if persisted_evening_start:
        _cached_evening_start = persisted_evening_start
        log.info(f"[HC] Using persisted evening window: {persisted_evening_start.strftime('%H:%M:%S')}")
        # Still update the sensor to ensure it's current
        _set_sensor("sensor.evening_start_local", persisted_evening_start.isoformat(), {
            "friendly_name": "Evening Start Local",
            "source": "persisted",
            "persisted": True
        })
    else:
        log.info("[HC] No valid persisted evening window found, calculating fresh")

    # Calculate evening_start_local = sunset_today - 15m
    # CRITICAL FIX: After sunset, use today's sunset, not tomorrow's
    # Try MQTT cached sunset first - use the correct sensor name
    cached_sunset = _get("sensor.cached_sunset_today")
    if cached_sunset:
        try:
            # Parse the cached sunset time
            cached_time_str = str(cached_sunset)
            if "T" in cached_time_str:
                sunset_dt = datetime.fromisoformat(cached_time_str)
            else:
                # Time-only format
                sunset_dt = datetime.combine(now.date(), _hc_parse_dt(cached_time_str).time())

            # Convert to local time and make naive
            if sunset_dt.tzinfo is not None:
                sunset_dt = sunset_dt.astimezone()
                sunset_dt = sunset_dt.replace(tzinfo=None)

            log.info(f"[HC] Using cached sunset: {sunset_dt.strftime('%H:%M')}")
            sunset_raw = sunset_dt.isoformat()
            sunset_today_raw = sunset_dt.isoformat()
        except Exception as e:
            log.warning(f"[HC] Error parsing cached sunset: {e}, falling back to live data")
            sunset_raw = _get("sun.sun", attr="next_setting")
            sunset_today_raw = _get("sun.sun", attr="setting")  # Today's sunset (None after sunset)
    else:
        log.info("[HC] No cached sunset available, using live sun.sun data")
        sunset_raw = _get("sun.sun", attr="next_setting")
        sunset_today_raw = _get("sun.sun", attr="setting")  # Today's sunset (None after sunset)

    if sunset_raw:
        try:
            # Handle both timezone-aware and naive datetime strings
            sunset_str = str(sunset_raw)
            if "T" in sunset_str:
                # ISO format with timezone
                try:
                    sunset_dt = datetime.fromisoformat(sunset_str)
                except ValueError:
                    # Try without timezone part
                    sunset_str = sunset_str.split('+')[0].split('-')[-1]  # Remove timezone
                    sunset_dt = datetime.fromisoformat(sunset_str)
            else:
                # Legacy format
                sunset_dt = datetime.fromisoformat(sunset_str)

            # Convert to local time and make naive
            if sunset_dt.tzinfo is not None:
                sunset_dt = sunset_dt.astimezone()  # Convert UTC to local
                sunset_dt = sunset_dt.replace(tzinfo=None)  # Remove timezone

            # CRITICAL: If sunset is tomorrow, we're already past today's sunset
            # Use cached today's sunset if available
            now = _now()
            if sunset_dt.date() > now.date():
                cached_time = _get("sensor.cached_sunset_today")
                if cached_time:
                    try:
                        if cached_time and cached_time != "None": time_only = datetime.fromisoformat("2000-01-01T" + str(cached_time)).time()
                        sunset_dt = now.replace(hour=time_only.hour, minute=time_only.minute, second=0)
                        log.info(f"[HC] Using cached sunset: {sunset_dt.strftime('%H:%M')}")
                    except Exception:
                        # Fallback estimate
                        sunset_dt = now.replace(hour=19, minute=20, second=0)
                else:
                    # No cache, estimate
                    sunset_dt = now.replace(hour=19, minute=20, second=0)
                    log.warning("[HC] No cached sunset, estimating 19:20")

            start_dt = sunset_dt - timedelta(minutes=EVENING_START_OFFSET_MINUTES)
            _cached_evening_start = start_dt

            # Store in MQTT for restart resilience
            mqtt_payload = {
                "evening_start": start_dt.isoformat(),
                "sunset": sunset_dt.isoformat(),
                "calculated_at": now.isoformat(),
                "date": now.date().isoformat(),
                "post_sunset_fix": sunset_dt.date() == now.date()
            }
            _mqtt_publish("daily_constants/evening_window", mqtt_payload)

            _set_sensor("sensor.evening_start_local", start_dt.isoformat(), {
                "friendly_name": "Evening Start Local",
                "source": "sun.sun",
                "sunset": sunset_dt.isoformat(),
                "offset_minutes": EVENING_START_OFFSET_MINUTES,
                "post_sunset_fix_applied": sunset_dt.date() == now.date(),
                "mqtt_stored": True
            })
            log.info(f"[HC] Evening window calculated: sunset={sunset_dt.strftime('%H:%M:%S')}, start={start_dt.strftime('%H:%M:%S')}, post_sunset_fix={sunset_dt.date() == now.date()}, stored_in_mqtt=True")
        except Exception as e:
            log.warning(f"[HC] sunset parse error: {e}, raw: {sunset_raw}")
            _cached_evening_start = None
            _set_sensor("sensor.evening_start_local", "", {
                "error": "parse_failed",
                "raw_value": str(sunset_raw),
                "error_detail": str(e)
            })
            _notify_missing_helper("sun.sun", "Evening window disabled until helper restores")
    else:
        _cached_evening_start = None
        _set_sensor("sensor.evening_start_local", "", {"error": "missing"})
        _notify_missing_helper("sun.sun", "Evening window disabled until helper restores")
        _set_sensor("binary_sensor.in_evening_window", "off", {"reason": "sunset_missing"})
    
    # Calculate day_min_start = sunrise_today + 30m
    sunrise_raw = _get("sun.sun", attr="next_rising")
    if sunrise_raw:
        try:
            # Handle both timezone-aware and naive datetime strings
            sunrise_str = str(sunrise_raw)
            if "T" in sunrise_str:
                # ISO format with timezone
                try:
                    sunrise_dt = datetime.fromisoformat(sunrise_str)
                except ValueError:
                    # Try without timezone part
                    sunrise_str = sunrise_str.split('+')[0].split('-')[-1]  # Remove timezone
                    sunrise_dt = datetime.fromisoformat(sunrise_str)
            else:
                # Legacy format
                sunrise_dt = datetime.fromisoformat(sunrise_str)

            # Convert to local time and make naive
            if sunrise_dt.tzinfo is not None:
                sunrise_dt = sunrise_dt.astimezone()  # Convert UTC to local
                sunrise_dt = sunrise_dt.replace(tzinfo=None)  # Remove timezone

            dms = sunrise_dt + timedelta(minutes=30)
            _cached_day_min_start = dms
            _set_sensor("sensor.day_min_start", dms.isoformat(), {
                "friendly_name": "Day Min Start",
                "source": "sun.sun",
                "sunrise": sunrise_dt.isoformat(),
                "offset_minutes": 30
            })
            log.info(f"[HC] Day min start calculated: sunrise={sunrise_dt.strftime('%H:%M:%S')}, day_start={dms.strftime('%H:%M:%S')}")
        except Exception as e:
            log.warning(f"[HC] sunrise parse error: {e}, raw: {sunrise_raw}")
            fallback_dt = now.replace(hour=7, minute=30, second=0, microsecond=0)
            _cached_day_min_start = fallback_dt
            _set_sensor("sensor.day_min_start", fallback_dt.isoformat(), {
                "fallback": "07:30",
                "error": "parse_failed",
                "raw_value": str(sunrise_raw),
                "error_detail": str(e)
            })
            _notify_missing_helper("sun.sun", "Day readiness locked to 07:30 floor")
    else:
        fallback_dt = now.replace(hour=7, minute=30, second=0, microsecond=0)
        _cached_day_min_start = fallback_dt
        _set_sensor("sensor.day_min_start", fallback_dt.isoformat(), {"fallback": "07:30"})
        _notify_missing_helper("sun.sun", "Day readiness locked to 07:30 floor")
    
    # Get monthly elevation target
    mon = _now().month
    target = MONTHLY_ELEV_TARGET.get(mon, 10)
    override = _get("pyscript.current_day_threshold")
    try:
        if override is not None:
            target = int(override)
    except Exception:
        pass
    _cached_day_elev_target = target
    _set_sensor("sensor.day_elev_target", target, {"unit_of_measurement":"°"})
    
    # Compute and publish Day commit time and brightness
    _publish_day_commit_and_target()
    
    _set_last_action("daily_constants_refreshed")

@catch_hc_error("_update_in_evening_window_flag")
def _update_in_evening_window_flag():
    """Update evening window flag (called minutely)"""
    start_dt = _cached_evening_start
    cutoff_hm = _cached_cutoff_hm or (_get_evening_cutoff_time().hour, _get_evening_cutoff_time().minute)
    
    if not start_dt:
        _set_sensor("binary_sensor.in_evening_window", "off", {"reason":"missing_sunset"})
        return
    
    now = _now()
    cutoff_time = dt_time(cutoff_hm[0], cutoff_hm[1])

    # Ensure start_dt is naive for comparison
    if hasattr(start_dt, 'tzinfo') and start_dt.tzinfo is not None:
        start_dt = start_dt.astimezone()  # Convert to local
        start_dt = start_dt.replace(tzinfo=None)  # Make naive

    in_window = (now >= start_dt and now.time() < cutoff_time and now.hour >= 15)
    
    _set_sensor("binary_sensor.in_evening_window", "on" if in_window else "off", {
        "start": start_dt.isoformat(),
        "cutoff": f"{cutoff_hm[0]:02d}:{cutoff_hm[1]:02d}:00"
    })

@catch_hc_error("_update_day_ready_flag")
def _update_day_ready_flag():
    """Update day ready flag with hysteresis"""
    global _day_ready_hysteresis_active, _day_ready_last_state, _day_ready_candidate_state, _day_ready_candidate_since

    dms = _cached_day_min_start
    target = _cached_day_elev_target if _cached_day_elev_target is not None else 10
    
    if not dms:
        _set_sensor("binary_sensor.day_ready_now", "off")
        _set_sensor("sensor.day_ready_reason", "waiting_for_day_constants")
        _day_ready_candidate_state = None
        _day_ready_candidate_since = None
        return
    
    now = _now()
    floor_time = _get_day_earliest_time_floor()
    floor_dt = now.replace(hour=floor_time.hour, minute=floor_time.minute, second=0, microsecond=0)
    dms_dt = dms
    if isinstance(dms_dt, str):
        try:
            dms_dt = datetime.fromisoformat(dms_dt)
        except Exception:
            dms_dt = now.replace(hour=floor_time.hour, minute=floor_time.minute, second=0, microsecond=0)
    if isinstance(dms_dt, datetime) and dms_dt.tzinfo is not None:
        dms_dt = dms_dt.replace(tzinfo=None)
    time_ok = now >= max(dms_dt, floor_dt)
    
    elev = _get("sun.sun", attr="elevation")
    try:
        elev = float(elev) if elev is not None else -90.0
    except Exception:
        elev = -90.0
    
    # Hysteresis: different thresholds for on/off
    threshold = float(target) - 3.0 if _day_ready_last_state else float(target)
    elev_ok = elev >= threshold
    
    not_in_evening = (_get("binary_sensor.in_evening_window") != "on")
    conditions_met = time_ok and elev_ok and not_in_evening

    if conditions_met != _day_ready_last_state:
        if _day_ready_candidate_state != conditions_met:
            _day_ready_candidate_state = conditions_met
            _day_ready_candidate_since = now
        elif _day_ready_candidate_since and (now - _day_ready_candidate_since).total_seconds() >= _DAY_READY_DEBOUNCE_SECONDS:
            _day_ready_last_state = conditions_met
            _day_ready_candidate_state = None
            _day_ready_candidate_since = None
    else:
        _day_ready_candidate_state = None
        _day_ready_candidate_since = None

    ready = _day_ready_last_state
    _set_sensor("binary_sensor.day_ready_now", "on" if ready else "off")

    debounce_note = "idle"
    if _day_ready_candidate_state is not None and _day_ready_candidate_since:
        elapsed = (now - _day_ready_candidate_since).total_seconds()
        remaining = max(0, int(_DAY_READY_DEBOUNCE_SECONDS - elapsed))
        state_label = "awaiting_on" if _day_ready_candidate_state else "awaiting_off"
        debounce_note = f"{state_label}:{remaining}s"

    comparator = "≥" if elev >= threshold else "<"
    reason = (
        f"time_ok={str(time_ok).lower()}, elev={elev:.1f}° {comparator} {threshold:.1f}° (target={float(target):.1f}°), "
        f"not_in_evening={str(not_in_evening).lower()}, debounce={debounce_note}"
    )
    _set_sensor("sensor.day_ready_reason", reason)


@catch_hc_error("_maybe_transition_to_day")
def _maybe_transition_to_day(reason: str) -> bool:
    """Transition to Day mode when conditions allow"""
    if _get("binary_sensor.day_ready_now") != "on":
        return False
    if _get("binary_sensor.in_evening_window") == "on":
        return False

    current = _get_home_state()
    if current == "Night":
        _clear_cutover_pending()
        _set_home_state("Day")
        _set_last_action(f"day_ready→Day:{reason}")
        return True

    if current == "Early Morning" and _get_boolean_state("sleep_in_ramp_active") != "on":
        _mark_em_end("day_ready_transition")
        _set_home_state("Day")
        _set_last_action(f"day_ready→Day:{reason}")
        return True

    return False

# ============================================================================
# DAY COMMIT TIME AND BRIGHTNESS TARGET
# ============================================================================
@catch_hc_error("_compute_day_commit_time")
def _compute_day_commit_time() -> datetime | None:
    """Compute day_commit_time = max(day_min_start, floor, learned_day_start)"""
    now = _now()

    def _coerce_to_datetime(raw_value, source_name: str) -> datetime | None:
        if raw_value in (None, "", "None"):
            return None
        try:
            text = str(raw_value).replace("Z", "").strip()
            if not text:
                return None
            if "T" in text or " " in text:
                candidate = datetime.fromisoformat(text)
            else:
                parts = text.split(":")
                hh = int(parts[0])
                mm = int(parts[1]) if len(parts) > 1 else 0
                ss = int(parts[2]) if len(parts) > 2 else 0
                candidate = now.replace(hour=hh, minute=mm, second=ss, microsecond=0)
            return candidate.replace(microsecond=0)
        except Exception as exc:
            log.warning(f"[HC] DAY COMMIT: Failed to parse {source_name}='{raw_value}': {exc}")
            return None

    def _resolve_helper_datetime(source_names: list[str], fallback_desc: str) -> tuple[datetime | None, str | None]:
        sources = [(name, _get(name)) for name in source_names]
        missing_names: list[str] = []
        for name, raw in sources:
            candidate = _coerce_to_datetime(raw, name)
            if candidate:
                if candidate.tzinfo is not None:
                    candidate = candidate.astimezone().replace(tzinfo=None)
                _clear_missing_helper_warning(name)
                return candidate, name
            if raw in (None, "", "None"):
                missing_names.append(name)
            else:
                _notify_missing_helper(name, fallback_desc)
        for name in missing_names:
            _notify_missing_helper(name, fallback_desc)
        return None, None

    default_floor_dt = now.replace(
        hour=_DEFAULT_DAY_FLOOR.hour,
        minute=_DEFAULT_DAY_FLOOR.minute,
        second=0,
        microsecond=0
    )

    floor_dt, floor_source = _resolve_helper_datetime([
        "input_datetime.day_earliest_time",
        "pyscript.day_earliest_time"], f"Using default earliest floor {_DEFAULT_DAY_FLOOR.strftime('%H:%M')}")

    if floor_dt:
        floor_candidate = floor_dt.replace(second=0, microsecond=0)
        floor_time_str = floor_candidate.strftime("%H:%M:%S")
    else:
        floor_candidate = default_floor_dt
        floor_time_str = floor_candidate.strftime("%H:%M:%S")
        log.warning(f"[HC] DAY COMMIT: No valid earliest floor helper value; defaulting to {floor_time_str}")
        floor_source = "default_floor"

    try:
        _set_sensor("sensor.day_earliest_time", floor_time_str)
    except Exception:
        pass

    candidates = [floor_candidate]
    fallback_desc = f"Using earliest floor {floor_candidate.strftime('%H:%M')}"

    dms, dms_source = _resolve_helper_datetime([
        "sensor.day_min_start",
        "pyscript.day_min_start"
    ], fallback_desc)
    if dms:
        candidates.append(dms)
    else:
        dms_source = None

    learned, learned_source = _resolve_helper_datetime([
        "sensor.learned_day_start",
        "sensor.day_learned_start",
        "input_datetime.learned_day_start",
        "pyscript.learned_day_start"], fallback_desc)
    if learned:
        candidates.append(learned)
    else:
        learned_source = None

    if not candidates:
        fallback_dt = now.replace(second=0, microsecond=0)
        log.error("[HC] DAY COMMIT: No valid candidates available; defaulting to current time")
        return fallback_dt

    commit = max(candidates)
    if commit < now:
        log.warning(f"[HC] DAY COMMIT: Computed commit time {commit.strftime('%H:%M')} is in the past; clamping to now")
        commit = now.replace(second=0, microsecond=0)

    def _describe(source_name: str | None, candidate: datetime | None) -> str:
        if not candidate:
            return "missing"
        source_label = source_name or "unspecified"
        return f"{source_label}@{candidate.strftime('%H:%M')}"

    log.info(
        "[HC] DAY COMMIT: floor=%s, day_min=%s, learned=%s → %s",
        _describe(floor_source, floor_candidate),
        _describe(dms_source, dms),
        _describe(learned_source, learned),
        commit.strftime("%H:%M"),
    )

    return commit

@catch_hc_error("_resolve_day_target_brightness")
def _resolve_day_target_brightness() -> tuple[int, str]:
    """Get Day target brightness following priority: teaching → adaptive → intelligent → fallback"""
    sources = [
        ("sensor.day_target_brightness_teaching", _get("sensor.day_target_brightness_teaching")),
        ("sensor.day_target_brightness_adaptive", _get("sensor.day_target_brightness_adaptive")),
        ("sensor.day_target_brightness_intelligent", _get("sensor.day_target_brightness_intelligent")),
        ("input_number.day_target_brightness_fallback", _get("input_number.day_target_brightness_fallback")),
        ("pyscript.day_target_brightness_fallback", _get("pyscript.day_target_brightness_fallback"))]
    
    for name, val in sources:
        try:
            if val not in (None, "unknown", "unavailable"):
                b = int(float(val))
                b = max(0, min(100, b))
                return b, name
        except Exception:
            continue
    
    return 70, "hardcoded_fallback_70"

@catch_hc_error("_publish_day_commit_and_target")
def _publish_day_commit_and_target():
    """Publish day commit time and brightness target sensors"""
    global _suppress_brightness_trigger

    commit = _compute_day_commit_time()
    if commit:
        state.set("sensor.day_commit_time", commit.isoformat(sep=" "), {
            "friendly_name": "Day Commit Time",
        })
        if _get("input_datetime.ramp_calculated_end_time") not in (None, "unavailable"):
            try:
                service.call("input_datetime","set_datetime",
                            entity_id="input_datetime.ramp_calculated_end_time",
                            datetime=commit.strftime("%Y-%m-%d %H:%M:%S"))
            except Exception as e:
                log.warning(f"[HC] Could not mirror commit time: {e}")
    else:
        state.set("sensor.day_commit_time", "", {
            "friendly_name": "Day Commit Time",
            "reason":"insufficient_inputs"
        })

    bri, src = _resolve_day_target_brightness()
    # Suppress brightness trigger to prevent loops when setting our own sensors
    try:
        _suppress_brightness_trigger = True
        state.set("sensor.day_target_brightness", bri, {
            "friendly_name": "Day Target Brightness",
            "unit_of_measurement": "%",
            "source": src,
            "updated_at": _now().isoformat()
        })
    finally:
        _suppress_brightness_trigger = False

# ============================================================================
# NIGHT MODE - SET IN STONE
# ============================================================================
def _night_started_on() -> str:
    """Get date when Night mode started"""
    return str(_get("sensor.night_started_on") or "")

@catch_hc_error("_set_night_started_today")
def _set_night_started_today():
    """Mark that Night started today"""
    _set_sensor("sensor.night_started_on", _today_str(), {
        "friendly_name":"Night Started On",
        "icon":"mdi:calendar-check"
    })

@catch_hc_error("_clear_cutover_pending")
def _clear_cutover_pending():
    """Clear Night cutover pending flag"""
    if _get("binary_sensor.pys_night_cutover_pending") != "on":
        return
    _set_sensor("binary_sensor.pys_night_cutover_pending", "off")
    _set_last_action("night_cutover_pending_false")

@catch_hc_error("_set_cutover_pending")
def _set_cutover_pending():
    """Set Night cutover pending flag (LR TV exception)"""
    if _get("binary_sensor.pys_night_cutover_pending") == "on":
        return
    _set_sensor("binary_sensor.pys_night_cutover_pending", "on")
    _set_last_action("night_cutover_pending_true")

@catch_hc_error("_run_night_cutover")
def _run_night_cutover():
    """SET IN STONE: Turn off every light that is ON except WLEDs"""
    try:
        lights = state.names(domain="light")
        on_lights = [
            entity
            for entity in lights
            if str(_get(entity)).lower() == "on" and "wled" not in entity.lower()
        ]

        if on_lights:
            log.info(f"[HC] Night cutover turning off: {on_lights}")
            for entity in on_lights:
                service.call("light", "turn_off", entity_id=entity)
        else:
            log.info("[HC] Night cutover: no eligible lights were on")

        _set_last_action("night_cutover_run")
    except Exception as e:
        log.warning(f"[HC] night_cutover error: {e}")


@catch_hc_error("_is_waiting_for_bedroom_tv")
def _is_waiting_for_bedroom_tv() -> bool:
    """Return True if we are waiting for the bedroom TV to turn on."""
    return str(_get_boolean_state("waiting_for_bedroom_tv") or "off").lower() == "on"


@catch_hc_error("_set_waiting_for_bedroom_tv")
def _set_waiting_for_bedroom_tv(source: Optional[str] = None):
    """Mark that Night mode is waiting for the bedroom TV."""
    reason = source or "unknown"
    status = "refresh" if _is_waiting_for_bedroom_tv() else "start"
    _set_boolean_state("waiting_for_bedroom_tv", "on")
    _set_sensor(
        "sensor.night_waiting_reason",
        reason,
        {
            "friendly_name": "Night Waiting Reason",
            "timestamp": _now().isoformat(),
            "status": "waiting",
            "source": reason,
            "mode": status,
        },
    )
    _set_last_action(f"night_waiting:{status}:{reason}")


@catch_hc_error("_postpone_night_until_bedroom_tv")
def _postpone_night_until_bedroom_tv(reason: str):
    """Force Evening and wait for bedroom TV before entering Night."""
    log.info(f"[HC] Postponing Night; waiting for bedroom TV ({reason}).")
    _set_waiting_for_bedroom_tv(reason)
    _cancel_waiting_timeout("postpone_waiting_reset")
    if _get_home_state() != "Evening":
        _enter_evening(f"waiting_for_bedroom_tv:{reason}", force=True)


@catch_hc_error("_start_waiting_timeout")
def _start_waiting_timeout():
    """Start/replace the post-23:00 waiting timeout (30 min) for BR TV."""
    global _waiting_timeout_task
    if _waiting_timeout_task and not getattr(_waiting_timeout_task, "done", lambda: True)():
        log.info("[HC] Waiting timeout already active; keeping existing countdown.")
        return
    _cancel_task_if_running(_waiting_timeout_task, "start_waiting_timeout")
    _waiting_timeout_task = task.create(_waiting_timeout_runner())


@catch_hc_error("_cancel_waiting_timeout")
def _cancel_waiting_timeout(reason: str = "cancel_waiting_timeout"):
    """Cancel the BR-TV waiting timeout, if any."""
    global _waiting_timeout_task
    _cancel_task_if_running(_waiting_timeout_task, reason)
    _waiting_timeout_task = None


@catch_hc_error("_waiting_timeout_runner")
async def _waiting_timeout_runner():
    """If BR TV never turns on after LR TV went off, force Night after 30 minutes."""
    try:
        await asyncio.sleep(WAIT_FOR_BR_TV_TIMEOUT_MIN * 60)
        if _is_waiting_for_bedroom_tv() and _get_home_state() not in ("Night", "Away"):
            log.info("[HC] Waiting timeout expired; BR TV did not turn on. Forcing Night.")
            _clear_waiting_for_bedroom_tv("waiting_timeout_expired")
            _enter_night(run_cutover=True, reason="waiting_timeout")
    except asyncio.CancelledError:
        raise
    except Exception as e:
        log.warning(f"[HC] waiting_timeout_runner error: {e}")


@catch_hc_error("_clear_waiting_for_bedroom_tv")
def _clear_waiting_for_bedroom_tv(source: Optional[str] = None):
    if not _is_waiting_for_bedroom_tv():
        return
    reason = source or "unknown"
    _cancel_waiting_timeout("clear_waiting_flag")
    _set_boolean_state("waiting_for_bedroom_tv", "off")
    _set_sensor(
        "sensor.night_waiting_reason",
        f"cleared:{reason}",
        {
            "friendly_name": "Night Waiting Reason",
            "timestamp": _now().isoformat(),
            "status": "cleared",
            "source": reason,
        },
    )
    _set_last_action(f"night_waiting:cleared:{reason}")


@catch_hc_error("_enter_night")
def _enter_night(run_cutover: bool, reason: str):
    """Enter Night mode"""
    _cancel_waiting_timeout("enter_night")  # cancel countdown
    now = _now()
    evening_started_today = False
    try:
        attrs = state.getattr("sensor.evening_last_reason") or {}
        ts = attrs.get("timestamp")
        if ts:
            ts_dt = datetime.fromisoformat(str(ts))
            evening_started_today = ts_dt.date() == now.date()
        elif _get("sensor.evening_last_reason"):
            evening_started_today = True
    except Exception:
        if _get("sensor.evening_last_reason"):
            evening_started_today = True

    _end_evening(reason or "night", mark_done=True)
    _set_home_state("Night")
    _set_night_started_today()
    _set_sensor("sensor.night_last_reason", reason, {
        "friendly_name": "Night Last Reason",
        "timestamp": now.isoformat()
    })
    
    _set_last_action(f"night_set:{reason}")
    
    if not run_cutover and not evening_started_today:
        run_cutover = True

    if run_cutover:
        _clear_cutover_pending()
        _run_night_cutover()
    else:
        _set_last_action("night_cutover_skipped_lr_tv_active")
        _set_cutover_pending()

@catch_hc_error("_bedroom_tv_trigger_to_night")
def _bedroom_tv_trigger_to_night():
    """Bedroom TV trigger for Night mode (with debounce)"""
    global _bedroom_tv_task
    _cancel_task_if_running(_bedroom_tv_task, "bedroom_tv_to_night")
    _bedroom_tv_task = task.create(_bedroom_tv_debounced())

async def _bedroom_tv_debounced():
    """Debounced Bedroom TV to Night transition"""
    try:
        await asyncio.sleep(BEDROOM_TV_DEBOUNCE_SECONDS)
        br_state = str(_get(BEDROOM_TV) or "").lower()
        if not _offish(br_state):  # BR TV ON-ish
            if _get("binary_sensor.pys_night_cutover_pending") == "on":
                if _is_waiting_for_bedroom_tv():
                    _clear_waiting_for_bedroom_tv("bedroom_tv_on_cutover")
                _clear_cutover_pending()
                _run_night_cutover()
                _set_last_action("night_cutover_resolved_bedroom_tv")
                return

            lr_state = str(_get(LIVINGROOM_TV) or "").lower()
            if _offish(lr_state):
                if _is_waiting_for_bedroom_tv():
                    _clear_waiting_for_bedroom_tv("bedroom_tv_on")
                _enter_night(run_cutover=True, reason=f"bedroom_tv_triggered_night:{br_state}")
            else:
                _set_last_action("bedroom_tv_on_but_living_room_still_on")
    except Exception as e:
        log.warning(f"[HC] debounce error: {e}")

@catch_hc_error("_failsafe_23_handler")
def _failsafe_23_handler():
    """23:00 failsafe for Night mode"""
    if _get_home_state() == "Away": 
        return
    if _night_started_on() == _today_str():
        return

    lr_st = str(_get(LIVINGROOM_TV) or "").lower()
    if not _offish(lr_st):
        _postpone_night_until_bedroom_tv("failsafe_23_lr_tv_on")
        return

    _enter_night(run_cutover=True, reason="failsafe_23")

# ============================================================================
# EVENING BRIGHTNESS PRE-RAMP (19:50-20:00)
# ============================================================================
@catch_hc_error("_start_evening_brightness_ramp")
async def _start_evening_brightness_ramp(restore_from_time=None):
    """
    Smoothly transition brightness of evening lights to the target 50%
    over 10 minutes before the color temp ramp begins.
    """
    global _evening_brightness_ramp_task

    # Guard: Don't start if already active (additional safety check)
    if _get_boolean_state("pys_evening_preramp_active") == "on" and not restore_from_time:
        log.info("[HC] Evening brightness pre-ramp already active - not starting new instance")
        return

    try:
        _set_boolean_state("pys_evening_preramp_active", "on")
        
        now = _now()
        end_time = now.replace(hour=20, minute=0, second=0, microsecond=0)

        if restore_from_time:
            if isinstance(restore_from_time, str):
                start_time = datetime.fromisoformat(str(restore_from_time))
            else:
                start_time = restore_from_time
            log.info(f"[HC] Resuming 10-minute evening brightness pre-ramp.")
        else:
            start_time = now
            _set_sensor("sensor.pys_evening_preramp_start_time", start_time.isoformat())
            log.info("[HC] Starting 10-minute evening brightness pre-ramp to 50%")

        active_lights = _get_on_temp_capable_lights()
        if not active_lights:
            log.info("[HC] Evening pre-ramp skipped; no temperature-capable lights are currently on.")
            return

        start_brightness_pct = None
        if restore_from_time:
            stored_start = _get("input_number.evening_preramp_start_brightness")
            try:
                start_brightness_pct = int(float(stored_start)) if stored_start not in (None, "", "unknown", "unavailable") else None
            except Exception:
                start_brightness_pct = None
        if start_brightness_pct is None:
            start_brightness_pct = 0

        # Determine starting brightness only if it's a fresh start
        if not restore_from_time:
            for light_entity in active_lights:
                try:
                    brightness_8bit = state.getattr(light_entity).get('brightness')
                    if brightness_8bit is not None:
                        start_brightness_pct = int(round((int(brightness_8bit) / 255) * 100))
                        log.info(f"[HC] Found starting brightness {start_brightness_pct}% from {light_entity}")
                        break 
                except Exception:
                    pass  # Ignore if attributes can't be read
            if start_brightness_pct == 0:
                log.info("[HC] Evening pre-ramp: unable to read brightness attribute; starting from 0%.")
            _set_input_number("input_number.evening_preramp_start_brightness", start_brightness_pct)

        # Pre-ramp loop until 20:00
        while _now() < end_time:
            current_lights = [l for l in active_lights if str(_get(l) or "off").lower() == "on"]
            if not current_lights:
                log.info("[HC] Evening pre-ramp ending early; all target lights are off.")
                break

            if start_brightness_pct is not None:
                current_brightness = _calculate_ramp_brightness(
                    start_time, end_time,
                    start_brightness_pct, EV_RAMP_BRI
                )
                try:
                    service.call("light", "turn_on", 
                                 entity_id=current_lights, 
                                 brightness_pct=current_brightness)
                    log.info(f"[HC] Evening Pre-Ramp: {current_brightness}%")
                except Exception as e:
                    log.warning(f"[HC] Evening pre-ramp brightness update failed: {e}")
            else:
                log.info("[HC] Evening pre-ramp resume without stored start brightness; jumping to target at completion.")
                break

            # Sleep for 15 seconds
            await asyncio.sleep(15)
            
        # Ensure final brightness is set
        final_lights = [l for l in active_lights if str(_get(l) or "off").lower() == "on"]
        if final_lights:
            service.call("light", "turn_on", entity_id=final_lights, brightness_pct=EV_RAMP_BRI)
            log.info(f"[HC] Evening brightness pre-ramp complete at {EV_RAMP_BRI}%.")
        _set_input_number("input_number.evening_preramp_start_brightness", EV_RAMP_BRI)

    finally:
        _set_boolean_state("pys_evening_preramp_active", "off")


# ============================================================================
# EVENING RAMP - SET IN STONE (20:00→21:00)
# ============================================================================
@catch_hc_error("_start_evening_ramp_if_needed")
def _start_evening_ramp_if_needed():
    """
    SET IN STONE: Evening ramp 20:00→21:00
    - Hold brightness at 50%
    - Smooth color temp from 4000K→2000K
    - Only for temperature-capable lights (Lamp One, Two, Closet)
    """
    if _get_home_state() in ("Away", "Night"):
        return
    if str(_get("binary_sensor.in_evening_window") or "off").lower() != "on":
        return
    if _get_home_state() != "Evening":
        return
    
    now = _now()
    t = now.time()
    
    if not (EV_RAMP_START_TIME <= t < EV_RAMP_END_TIME):
        return
    
    if _get_boolean_state("evening_ramp_started_today") == "on":
        return
    
    end_dt = now.replace(hour=EV_RAMP_END_TIME.hour, minute=EV_RAMP_END_TIME.minute, 
                         second=0, microsecond=0)
    remaining = int(max(0, (end_dt - now).total_seconds()))
    
    if remaining < 5:
        return
    
    lights = _get_on_temp_capable_lights()

    if not lights:
        log.info("[HC] Evening ramp skipped; no temperature-capable lights are currently on.")
        return
    
    try:
        service.call("light", "turn_on", entity_id=lights,
                    kelvin=EV_RAMP_END_K, brightness_pct=EV_RAMP_BRI, 
                    transition=remaining)
        log.info(f"[HC] Evening ramp: transitioning to 2000K over {remaining}s")
    except Exception as e:
        try:
            end_mired = int(1000000 / EV_RAMP_END_K)
            service.call("light", "turn_on", entity_id=lights,
                        color_temp=end_mired, brightness_pct=EV_RAMP_BRI, 
                        transition=remaining)
            log.info(f"[HC] Evening ramp: using mireds fallback")
        except Exception as ex:
            log.warning(f"[HC] Evening ramp transition failed: {e} / {ex}")
            return
    
    _set_boolean_state("evening_ramp_started_today", "on")
    state.set("sensor.evening_ramp_started_at", now.isoformat(), {
        "friendly_name": "Evening Ramp Started At",
        "target_end": end_dt.isoformat(),
        "start_kelvin": EV_RAMP_START_K,
        "end_kelvin": EV_RAMP_END_K,
        "brightness_pct": EV_RAMP_BRI
    })
    _set_last_action("evening_ramp_started")

# ============================================================================
# MINUTELY EVALUATION
# ============================================================================
@catch_hc_error("_minutely_tick")
def _minutely_tick():
    """Minutely update of flags and state transitions"""
    if _get_home_state() == "Away": 
        return

    _enforce_workday_ramp_end()

    _update_in_evening_window_flag()
    _update_day_ready_flag()
    _maybe_transition_to_day("minutely")

    # Note: Non-work Early Morning → Day is handled by the ramp completion
    # The nonwork ramp automatically transitions to Day when complete

    # Clear pending cutover when leaving Night
    if _get_home_state() != "Night" and _get("binary_sensor.pys_night_cutover_pending") == "on":
        _clear_cutover_pending()
    
    # Check for Evening window entry
    evening_window_state = _get("binary_sensor.in_evening_window")
    home_state = _get_home_state()
    night_started = _night_started_on()
    evening_done = _get_boolean_state("evening_done_today")

    # Check for Evening window entry
    if (home_state == "Day" and
        evening_window_state == "on" and
        night_started != _today_str() and
        evening_done != "on"):
        log.info(f"[HC][DEBUG] Evening entry conditions met - entering evening mode")
        _enter_evening("auto_day_to_evening")
    else:
        log.info(f"[HC][DEBUG] Evening entry conditions NOT met:")
        log.info(f"[HC][DEBUG] - Home state is Day: {home_state == 'Day'} (actual: {home_state})")
        log.info(f"[HC][DEBUG] - Evening window is on: {evening_window_state == 'on'} (actual: {evening_window_state})")
        log.info(f"[HC][DEBUG] - Night not started today: {night_started != _today_str()} (night_started: {night_started}, today: {_today_str()})")
        log.info(f"[HC][DEBUG] - Evening not done today: {evening_done != 'on'} (actual: {evening_done})")

        # If we're in evening window but not in Day mode, show what mode we're in
        if evening_window_state == "on" and home_state != "Day":
            log.info(f"[HC][DEBUG] In evening window but wrong mode: {home_state}. Need to be in Day mode.")

# ============================================================================
# STARTUP AND EVALUATION
# ============================================================================
@catch_hc_error("_evaluate_startup_state")
def _evaluate_startup_state():
    """Evaluate state on startup - ROBUST time-based evaluation"""
    global _work_ramp_task, _nonwork_ramp_task, _morning_motion_classified_date, _morning_motion_profile

    log.info("[HC][STARTUP] ========== STARTUP STATE EVALUATION ==========")
    now = _now()
    current_time = now.strftime("%H:%M:%S")
    log.info(f"[HC][STARTUP] Current time: {current_time}")

    # Check presence first - highest priority
    if _is_any_phone_away():
        log.info("[HC][STARTUP] Phones are away - setting Away mode")
        _set_home_state("Away")
        _set_last_action("startup:phones_away→Away")
        return

    # Refresh daily constants to get current sunset/sunrise times
    log.info("[HC][STARTUP] Refreshing daily constants...")
    _refresh_daily_constants()

    # Get timing boundaries
    cutoff = _get_evening_cutoff_time()
    cutoff_str = cutoff.strftime("%H:%M:%S")
    log.info(f"[HC][STARTUP] Evening cutoff time: {cutoff_str}")

    # Check if we're in Night hours (>= 23:00)
    if now.time() >= cutoff:
        log.info(f"[HC][STARTUP] Current time {current_time} >= cutoff {cutoff_str} - Night hours")
        if _night_started_on() != _today_str():
            log.info("[HC][STARTUP] Night not started today - evaluating Night entry")
            lr_st = str(_get(LIVINGROOM_TV) or "").lower()
            if not _offish(lr_st):
                log.info("[HC][STARTUP] LR TV is on - postponing Night until BR TV")
                _postpone_night_until_bedroom_tv("startup_post_23_lr_on")
            else:
                log.info("[HC][STARTUP] LR TV is off - entering Night immediately")
                _enter_night(run_cutover=True, reason="startup_post_23")
        else:
            log.info("[HC][STARTUP] Night already started today - keeping Night mode")
            _set_home_state("Night")
            _set_last_action("startup:keep_Night")
        return

    # Update flags for current time evaluation
    _update_in_evening_window_flag()
    _update_day_ready_flag()

    # Check if Early Morning helpers indicate an active route
    em_route = str(_get("input_text.em_route_key") or "").lower()
    em_active_flag = _get_boolean_state("em_active") == "on"
    em_start_raw = _get("input_datetime.em_start_ts")
    em_start_dt = None
    if em_start_raw:
        try:
            em_start_dt = datetime.fromisoformat(str(em_start_raw))
        except Exception as e:
            log.warning(f"[HC][STARTUP] Could not parse em_start_ts '{em_start_raw}': {e}")

    # Check if manual reset is active - skip Early Morning restoration
    manual_reset_active = _get_boolean_state("manual_reset_active") == "on"
    if manual_reset_active:
        log.info("[HC][STARTUP] Manual reset active - skipping Early Morning restoration")
        _set_boolean_state("manual_reset_active", "off")  # Clear the flag
        return

    if em_route in ("work", "day_off") and em_active_flag and em_start_dt:
        log.info(f"[HC][STARTUP] Early Morning route detected: {em_route}")
        _morning_motion_profile = em_route
        _morning_motion_classified_date = em_start_dt.date()

        _set_sensor("sensor.pys_morning_ramp_profile", em_route, {
            "source": "rehydrate",
            "reason": f"startup_{em_route}",
            "classified_at": em_start_dt.isoformat()
        })
        _set_sensor("sensor.pys_em_classification_time", em_start_dt.isoformat(), {
            "friendly_name": "Early Morning Classification Time"
        })
        _set_sensor("sensor.pys_morning_ramp_reason", f"rehydrate_{em_route}")
        _set_sensor("sensor.pys_em_start_time", em_start_dt.isoformat(), {
            "friendly_name": "Early Morning Start Time"
        })
        _set_sensor("pyscript.motion_work_day_detected", "on" if em_route == "work" else "off")

        _set_home_state("Early Morning")
        _set_last_action("startup:keep_Early_Morning")
        _set_em_status("rehydrate_em", {
            "route": em_route,
            "start": em_start_dt.strftime('%H:%M:%S') if em_start_dt else "unknown"
        })
        _publish_em_contract()

        ramp_active = _get_boolean_state("sleep_in_ramp_active") == "on"
        commit_dt = _compute_day_commit_time() if em_route == "day_off" else None
        should_resume = (
            ramp_active or
            (em_route == "work" and now.time() < WORK_RAMP_END_TIME) or
            (em_route == "day_off" and (commit_dt is None or now < commit_dt))
        )

        if should_resume:
            log.info(f"[HC][STARTUP] Resuming {em_route} ramp")
            if em_route == "work":
                _cancel_task_if_running(_work_ramp_task, "work_ramp")
                _cancel_task_if_running(_nonwork_ramp_task, "nonwork_ramp")
                _work_ramp_task = task.create(_start_work_ramp(restore_from_time=em_start_dt))
            else:
                _cancel_task_if_running(_nonwork_ramp_task, "nonwork_ramp")
                _cancel_task_if_running(_work_ramp_task, "work_ramp")
                _nonwork_ramp_task = task.create(_start_nonwork_ramp(start_time_override=em_start_dt))
        return

    # Check if in Evening pre-ramp window (19:50-20:00) and it was active
    if _get_boolean_state("pys_evening_preramp_active") == "on" and now.time() < dt_time(20, 0):
        log.info("[HC][STARTUP] Evening pre-ramp was active - resuming")
        start_time_str = _get("sensor.pys_evening_preramp_start_time")
        if start_time_str:
            global _evening_brightness_ramp_task
            _cancel_task_if_running(_evening_brightness_ramp_task, "evening_brightness_ramp")
            _evening_brightness_ramp_task = task.create(_start_evening_brightness_ramp(restore_from_time=start_time_str))
        else:
            log.warning("[HC][STARTUP] Could not resume evening pre-ramp: start time sensor is missing")
        return

    # ROBUST Evening window evaluation - check time vs calculated evening window directly
    evening_window_state = _get("binary_sensor.in_evening_window")
    log.info(f"[HC][STARTUP] Evening window sensor state: {evening_window_state}")

    # Get evening start time directly from cached value or calculate it
    evening_start = _cached_evening_start
    if evening_start:
        log.info(f"[HC][STARTUP] Cached evening start: {evening_start.strftime('%H:%M:%S')}")
    else:
        log.warning("[HC][STARTUP] No cached evening start available")

    # Check if we're in evening window based on time calculation
    in_evening_window_by_time = False
    if evening_start and cutoff:
        in_evening_window_by_time = (now >= evening_start and now.time() < cutoff and now.hour >= 15)
        log.info(f"[HC][STARTUP] In evening window by time calculation: {in_evening_window_by_time}")

    # Use time-based calculation if sensor is unreliable, otherwise use sensor
    should_be_in_evening = in_evening_window_by_time or evening_window_state == "on"
    log.info(f"[HC][STARTUP] Should be in evening window: {should_be_in_evening}")

    if should_be_in_evening and _night_started_on() != _today_str():
        log.info("[HC][STARTUP] In evening window and Night not started - entering Evening mode")
        if _enter_evening("startup_evening_window", force=_get_home_state() == "Away"):
            _start_evening_ramp_if_needed()
        return

    # Check Day readiness
    day_ready_state = _get("binary_sensor.day_ready_now")
    log.info(f"[HC][STARTUP] Day ready sensor state: {day_ready_state}")

    if day_ready_state == "on":
        log.info("[HC][STARTUP] Day ready - setting Day mode")
        _set_home_state("Day")
        _set_last_action("startup:day_ready→Day")
        return

    # Default to Day mode if nothing else matches
    current = _get_home_state()
    log.info(f"[HC][STARTUP] No specific conditions met, current state: {current}")
    if current not in ("Early Morning","Evening","Night","Away","Day"):
        log.info("[HC][STARTUP] Setting default Day mode")
        _set_home_state("Day")
        _set_last_action("startup:default→Day")

    _publish_em_contract()
    log.info("[HC][STARTUP] ========== STARTUP STATE EVALUATION COMPLETE ==========")

# ============================================================================
# TRIGGERS - SET IN STONE
# ============================================================================

# Kitchen motion sensor triggers - WITH COORDINATION TO PREVENT RACE CONDITIONS
@state_trigger("binary_sensor.aqara_motion_sensor_p1_occupancy == 'on'")
@catch_hc_trigger_error("handle_kitchen_motion_1")
def _handle_kitchen_motion_1(value=None, old_value=None, **kwargs):
    """Handle kitchen motion sensor 1 - coordinated to prevent race with lighting"""
    entity = "binary_sensor.aqara_motion_sensor_p1_occupancy"
    new_state = value if value is not None else _get(entity)
    if str(new_state).lower() == "on":
        log.info(f"[HC][DEBUG] Kitchen motion sensor 1 triggered - state: {new_state}, old: {old_value}")
        log.info(f"[HC][DEBUG] Current time: {_now().strftime('%H:%M:%S.%f')}")
        task.create(_coordinated_kitchen_motion_classification(entity))

@state_trigger("binary_sensor.kitchen_iris_frig_occupancy == 'on'")
@catch_hc_trigger_error("handle_kitchen_motion_2")
def _handle_kitchen_motion_2(value=None, old_value=None, **kwargs):
    """Handle kitchen motion sensor 2 - coordinated to prevent race with lighting"""
    entity = "binary_sensor.kitchen_iris_frig_occupancy"
    new_state = value if value is not None else _get(entity)
    if str(new_state).lower() == "on":
        log.info(f"[HC][DEBUG] Kitchen motion sensor 2 triggered - state: {new_state}, old: {old_value}")
        log.info(f"[HC][DEBUG] Current time: {_now().strftime('%H:%M:%S.%f')}")
        task.create(_coordinated_kitchen_motion_classification(entity))

# Minutely evaluation
@time_trigger("cron(* * * * *)")
@catch_hc_trigger_error("minutely_evaluation")
def _minutely_evaluation():
    if not _is_controller_enabled():
        return
    _minutely_tick()


@state_trigger("binary_sensor.day_ready_now")
@catch_hc_trigger_error("day_ready_state_changed")
def _on_day_ready_state(value=None, old_value=None, **kwargs):
    if not _is_controller_enabled():
        return
    if value == "on":
        _maybe_transition_to_day("day_ready_sensor")

# Bedroom TV state changes
@state_trigger(f"{BEDROOM_TV}")
@catch_hc_trigger_error("bedroom_tv_changed")
def _bedroom_tv_changed(value=None, old_value=None, **kwargs):
    if not _is_controller_enabled():
        return
    st = str(value or _get(BEDROOM_TV) or "").lower()
    if not _offish(st):
        _bedroom_tv_trigger_to_night()


@state_trigger(f"{LIVINGROOM_TV}")
@catch_hc_trigger_error("livingroom_tv_change")
def _livingroom_tv_changed(value=None, old_value=None, **kwargs):
    """Handle LR TV state changes after 23:00 while waiting for BR TV."""
    if not _is_controller_enabled():
        return
    if not _is_waiting_for_bedroom_tv():
        return
    if _now().time() < dt_time(23, 0):
        return
    if _get_home_state() in ("Night", "Away"):
        return

    async def _maybe_start():
        try:
            await asyncio.sleep(2)  # small debounce
            curr = str(_get(LIVINGROOM_TV) or "").lower()
            if _is_waiting_for_bedroom_tv() and _get_home_state() not in ("Night", "Away") and _offish(curr):
                log.info("[HC] LR TV is OFF after 23:00 while waiting → starting 30-min BR-TV timer.")
                _start_waiting_timeout()
            # NOTE: If LR TV turns back ON, we do nothing; timer continues.
        except Exception as e:
            log.warning(f"[HC] livingroom_tv_changed apply error: {e}")

    task.create(_maybe_start())


# 23:00 failsafe
@time_trigger("cron(0 23 * * *)")
@catch_hc_trigger_error("failsafe_23")
def _at_23_failsafe():
    if not _is_controller_enabled():
        return
    _failsafe_23_handler()

# Evening brightness pre-ramp trigger at 19:50
@time_trigger("cron(50 19 * * *)")
@catch_hc_trigger_error("evening_brightness_ramp_trigger")
def _evening_brightness_ramp_trigger():
    global _evening_brightness_ramp_task
    if _get_home_state() in ("Away", "Night"):
        return

    # Guard: Don't start if pre-ramp is already active
    if _get_boolean_state("pys_evening_preramp_active") == "on":
        log.info("[HC] Evening brightness pre-ramp already active - ignoring trigger")
        return

    log.info("[HC] Triggering evening brightness pre-ramp.")
    _cancel_task_if_running(_evening_brightness_ramp_task, "evening_brightness_ramp")
    _evening_brightness_ramp_task = task.create(_start_evening_brightness_ramp())

# 04:30 daily reset (buffer before 04:50 work detection)
@time_trigger("cron(30 4 * * *)")
@catch_hc_trigger_error("morning_reset")
def _morning_reset():
    global _morning_motion_classified_date, _morning_motion_profile
    _morning_motion_classified_date = None
    _morning_motion_profile = None
    _set_sensor("pyscript.motion_work_day_detected", "off")
    _set_sensor("sensor.pys_morning_ramp_profile", "unknown", {
        "source":"reset",
        "reason":"daily_reset"
    })
    _set_boolean_state("sleep_in_ramp_active", "off")
    _set_boolean_state("daily_motion_lock", "off")
    _set_boolean_state("em_active", "off")
    _set_input_text("input_text.em_route_key", "")
    _set_input_text("input_text.em_until", "")
    _set_input_datetime("input_datetime.em_start_ts", None)
    try:
        service.call("input_datetime", "set_datetime",
                     entity_id="input_datetime.first_kitchen_motion_today",
                     datetime=_now().replace(hour=0, minute=0, second=0, microsecond=0).strftime("%Y-%m-%d %H:%M:%S"))
    except Exception:
        pass
    _set_last_action("morning_reset_04:30")
    _publish_em_contract()

def manual_morning_reset():
    """Manual reset function - call anytime to clear morning state like you never got up"""
    global _morning_motion_classified_date, _morning_motion_profile, _work_ramp_task, _nonwork_ramp_task

    log.info("[HC] MANUAL RESET: Clearing morning classification state")

    # Clear in-memory state
    _morning_motion_classified_date = None
    _morning_motion_profile = None

    # Cancel any running ramp tasks
    _cancel_task_if_running(_work_ramp_task, "work_ramp_manual_reset")
    _cancel_task_if_running(_nonwork_ramp_task, "nonwork_ramp_manual_reset")
    _work_ramp_task = None
    _nonwork_ramp_task = None

    # Reset all persistent sensors and states
    _set_sensor("pyscript.motion_work_day_detected", "off")
    _set_sensor("sensor.pys_morning_ramp_profile", "unknown", {
        "source": "manual_reset",
        "reason": "user_initiated_reset"
    })
    _set_sensor("sensor.pys_em_classification_time", "", {
        "source": "manual_reset",
        "friendly_name": "Early Morning Classification Time"
    })
    _set_sensor("sensor.pys_em_start_time", "", {
        "source": "manual_reset",
        "friendly_name": "Early Morning Start Time"
    })
    _set_sensor("sensor.pys_morning_ramp_reason", "manual_reset", {
        "source": "manual_reset",
        "friendly_name": "Morning Ramp Reason"
    })
    _set_sensor("sensor.pys_em_end_reason", "", {
        "source": "manual_reset",
        "friendly_name": "Early Morning End Reason"
    })
    _set_sensor("sensor.pys_em_end_time", "", {
        "source": "manual_reset",
        "friendly_name": "Early Morning End Time"
    })

    # Reset boolean states
    _set_boolean_state("sleep_in_ramp_active", "off")
    _set_boolean_state("daily_motion_lock", "off")
    _set_boolean_state("em_active", "off")
    _set_boolean_state("evening_ramp_started_today", "off")

    # Set flag to prevent startup from overriding our reset
    _set_boolean_state("manual_reset_active", "on")

    # Set system back to Night mode
    _set_home_state("Night")
    log.info("[HC] MANUAL RESET: Set home state to Night mode")

    # Set night-appropriate lighting
    _set_sensor("sensor.sleep_in_ramp_brightness", 10)
    _set_ramp_temperature(2000)
    log.info("[HC] MANUAL RESET: Set lighting to night levels (10%, 2000K)")

    # Reset input helpers
    _set_input_text("input_text.em_route_key", "")
    _set_input_text("input_text.em_until", "")
    _set_input_datetime("input_datetime.em_start_ts", None)

    # Clear first motion datetime
    try:
        service.call("input_datetime", "set_datetime",
                     entity_id="input_datetime.first_kitchen_motion_today",
                     datetime=_now().replace(hour=0, minute=0, second=0, microsecond=0).strftime("%Y-%m-%d %H:%M:%S"))
    except Exception:
        pass

    log.info("[HC] MANUAL RESET: Complete - system fully reset to Night mode, ready for morning test")

    # Publish contract to update diagnostics
    _publish_em_contract()

# Midnight reset for evening flags
@time_trigger("cron(5 0 * * *)")
@catch_hc_trigger_error("midnight_reset")
def _midnight_reset():
    _set_boolean_state("evening_ramp_started_today", "off")
    _set_boolean_state("evening_done_today", "off")
    _set_boolean_state("evening_mode_active", "off")
    _clear_waiting_for_bedroom_tv("midnight_reset")
    _set_last_action("midnight_reset_evening_flags")

# Presence changes
@state_trigger(PHONE_1, PHONE_2)
@catch_hc_trigger_error("handle_presence_change")
def _handle_presence_change(value=None, old_value=None, **kwargs):
    entity_name = kwargs.get("var_name", "unknown_tracker")

    log.info(f"[HC][PRESENCE][CRASH_DEBUG] ========== PRESENCE CHANGE TRIGGERED ==========")
    log.info(f"[HC][PRESENCE][CRASH_DEBUG] Triggered by {entity_name} change: {old_value} -> {value}")
    log.info(f"[HC][PRESENCE][CRASH_DEBUG] Current Home State: {_get_home_state()}")
    log.info(f"[HC][PRESENCE][CRASH_DEBUG] Both Phones Home: {_are_both_phones_home()}")
    log.info(f"[HC][PRESENCE][CRASH_DEBUG] Any Phone Away: {_is_any_phone_away()}")
    log.info(f"[HC][PRESENCE][CRASH_DEBUG] Current time: {_now().strftime('%H:%M:%S.%f')}")
    log.info(f"[HC][PRESENCE][CRASH_DEBUG] Phone1 state: {_get(PHONE_1)}, Phone2 state: {_get(PHONE_2)}")

    if _are_both_phones_home():
        log.info("[HC][PRESENCE][CRASH_DEBUG] All tracked phones are now home.")
        if _get_home_state() == "Away":
            log.info("[HC][PRESENCE][CRASH_DEBUG] System is currently in Away mode. Evaluating return conditions.")
            now = _now()
            cutoff = _get_evening_cutoff_time()

            log.info(f"[HC][PRESENCE][CRASH_DEBUG] Current time: {now.time().strftime('%H:%M')}, Cutoff: {cutoff.strftime('%H:%M')}")
            log.info(f"[HC][PRESENCE][CRASH_DEBUG] In Evening Window: {_get('binary_sensor.in_evening_window')}")
            log.info(f"[HC][PRESENCE][CRASH_DEBUG] Night Started Today: {_night_started_on() == _today_str()}")
            log.info(f"[HC][PRESENCE][CRASH_DEBUG] Evening Done Today: {_get_boolean_state('evening_done_today')}")

            if now.time() >= cutoff or now.time() < dt_time(4,45):
                log.info("[HC][PRESENCE] Branch: Returning during Night hours.")
                lr_state = str(_get(LIVINGROOM_TV) or "").lower()
                lr_on = not _offish(lr_state)
                _enter_night(run_cutover=not lr_on, reason="presence_return_after_away")
            elif _get("binary_sensor.in_evening_window") == "on" and now.time() < cutoff:
                night_started = _night_started_on()
                if night_started == _today_str():
                    log.info("[HC][PRESENCE] Evening return detected before cutoff with stale night flag. Clearing night_started_on to allow re-entry.")
                    _set_sensor("sensor.night_started_on", "", {
                        "friendly_name": "Night Started On",
                        "cleared_due_to": "evening_return_before_cutoff"
                    })
                log.info("[HC][PRESENCE] Branch: Returning during Evening window.")
                force_evening = (_get_home_state() == "Away")
                if _get_boolean_state("evening_done_today") != "on":
                    if _enter_evening("presence_return_after_away", force=force_evening):
                        log.info("[HC][PRESENCE] Successfully entered Evening mode.")
                        _start_evening_ramp_if_needed()
                    else:
                        log.warning("[HC][PRESENCE] Failed to enter Evening mode (return from Away).")
                else:
                    log.info("[HC][PRESENCE] Evening already done today, forcing entry due to return from Away.")
                    if _enter_evening("presence_return_after_away", force=True):
                        log.info("[HC][PRESENCE] Successfully entered Evening mode (forced).")
                        _start_evening_ramp_if_needed()
                    else:
                        log.warning("[HC][PRESENCE] Failed to enter Evening mode (forced return from Away).")
            else:
                log.info("[HC][PRESENCE] Branch: Defaulting to Day mode.")
                if _get_home_state() != "Day":
                    _set_home_state("Day")
                    _set_last_action(f"returned_home:{entity_name}→Day")
                else:
                    log.info("[HC][PRESENCE] Already in Day mode, no change needed.")
        else:
            log.info("[HC][PRESENCE] System not in Away mode, no return action needed.")
    else:
        log.info(f"[HC][PRESENCE][CRASH_DEBUG] At least one phone has left. Evaluating Away transition.")
        log.info(f"[HC][PRESENCE][CRASH_DEBUG] Current state: {_get_home_state()}")
        log.info(f"[HC][PRESENCE][CRASH_DEBUG] Entity that triggered: {entity_name}")
        log.info(f"[HC][PRESENCE][CRASH_DEBUG] Phone states - Phone1: {_get(PHONE_1)}, Phone2: {_get(PHONE_2)}")

        if _get_home_state() != "Away":
            log.info(f"[HC][PRESENCE][CRASH_DEBUG] System not in Away mode. Evaluating transition to Away.")
            current_state = _get_home_state()
            log.info(f"[HC][PRESENCE][CRASH_DEBUG] Current state before transition: {current_state}")

            # SET IN STONE: On workday after 05:40, presence→Away ends Early Morning
            if (_get_home_state() == "Early Morning" and
                str(_get("pyscript.motion_work_day_detected") or "off").lower() == "on" and
                _now().time() >= WORK_RAMP_END_TIME):
                log.info("[HC][PRESENCE][CRASH_DEBUG] Ending Early Morning due to Away transition.")
                _mark_em_end("workday_presence_away")
                _set_boolean_state("sleep_in_ramp_active", "off")

            if _get_home_state() == "Evening" or _get_boolean_state("evening_mode_active") == "on":
                log.info("[HC][PRESENCE][CRASH_DEBUG] Ending Evening mode due to Away transition.")
                _end_evening("presence_away", mark_done=False)

            log.info(f"[HC][PRESENCE][CRASH_DEBUG] About to call _set_home_state('Away')")
            _set_home_state("Away")
            log.info(f"[HC][PRESENCE][CRASH_DEBUG] Successfully set state to Away")

            if _get("binary_sensor.pys_night_cutover_pending") == "on":
                log.info(f"[HC][PRESENCE][CRASH_DEBUG] Clearing night cutover pending")
                _clear_cutover_pending()
            if _is_waiting_for_bedroom_tv():
                log.info(f"[HC][PRESENCE][CRASH_DEBUG] Clearing bedroom TV waiting state")
                _clear_waiting_for_bedroom_tv("presence_away")

            try:
                log.info(f"[HC][PRESENCE][CRASH_DEBUG] Getting all light entities")
                lights = state.names(domain="light")
                log.info(f"[HC][PRESENCE][CRASH_DEBUG] Found {len(lights)} light entities")
                on_lights = [
                    entity
                    for entity in lights
                    if str(_get(entity)).lower() == "on"
                ]
                log.info(f"[HC][PRESENCE][CRASH_DEBUG] Found {len(on_lights)} lights that are on")
                if on_lights:
                    log.info(f"[HC][PRESENCE][CRASH_DEBUG] Turning off lights for Away: {on_lights}")
                    for entity in on_lights:
                        log.info(f"[HC][PRESENCE][CRASH_DEBUG] Turning off light: {entity}")
                        service.call("light", "turn_off", entity_id=entity)
                else:
                    log.info(f"[HC][PRESENCE][CRASH_DEBUG] No lights to turn off")
            except Exception as exc:
                log.warning(f"[HC][PRESENCE][CRASH_DEBUG] Error turning off lights during Away: {exc}")
                log.warning(f"[HC][PRESENCE][CRASH_DEBUG] Exception type: {type(exc)}")

            log.info(f"[HC][PRESENCE][CRASH_DEBUG] About to set last action")
            _set_last_action(f"went_away:{entity_name}")
            log.info(f"[HC][PRESENCE][CRASH_DEBUG] Successfully completed Away transition")
        else:
            log.info("[HC][PRESENCE][CRASH_DEBUG] Already in Away mode, no change needed.")

@state_trigger("input_select.home_state")
@catch_hc_trigger_error("handle_manual_home_state")
def _handle_manual_home_state(value=None, old_value=None, **kwargs):
    if _suppress_home_state_trigger:
        return
    if value is None or value == old_value:
        return
    if value == "Night":
        _enter_night(run_cutover=True, reason="manual_input_select")
    elif value == "Evening":
        _enter_evening("manual_input_select", force=True)
    elif value == "Away":
        if _get_home_state() != "Away":
            if _get_home_state() == "Evening" or _get_boolean_state("evening_mode_active") == "on":
                _end_evening("manual_away", mark_done=False)
            _set_home_state("Away")
    elif value == "Day":
        if _get_home_state() != "Day":
            if _get_home_state() == "Evening" or _get_boolean_state("evening_mode_active") == "on":
                _end_evening("manual_day", mark_done=False)
            _set_home_state("Day")
    elif value == "Early Morning":
        if _get_home_state() != "Early Morning":
            _set_home_state("Early Morning")

# Startup initialization
@time_trigger("startup")
@catch_hc_trigger_error("startup_initialization")
def _startup_initialization():
    log.info("[HC] ========== HOME CONTROLLER STARTING (REWORK COMPLIANT) ==========")
    _ensure_entities()
    _init_brightness_system()
    _init_day_start_sensors()
    _refresh_daily_constants()
    _evaluate_startup_state()

    # Consolidated startup functions from other modules
    _consolidated_startup_tasks()

    _set_last_action("startup_complete")
    log.info("[HC] ========== HOME CONTROLLER READY ==========")

@catch_hc_error("_consolidated_startup_tasks")
def _consolidated_startup_tasks():
    """Consolidated startup tasks from other modules to reduce startup trigger duplication"""

    # Load memory stats for web interface (from web_interface_services.py) - OPTIONAL
    try:
        # Try to import and call the function - this is completely optional
        import web_interface_services
        if hasattr(web_interface_services, 'get_all_memory_stats'):
            web_interface_services.get_all_memory_stats()
            log.info("[HC] Memory stats loaded for web interface")
        else:
            log.info("[HC] web_interface_services module available but missing get_all_memory_stats function")
    except ImportError:
        log.info("[HC] web_interface_services module not available - memory stats loading skipped (optional feature)")
    except Exception as e:
        log.info(f"[HC] Memory stats loading failed: {e} (optional feature)")

    # System diagnostic startup message (from system_diagnostic.py)
    try:
        log.info("🔧 System diagnostic loaded successfully")
    except Exception as e:
        log.warning(f"[HC] Error logging diagnostic startup: {e}")

# Daily constants refresh at 00:02
@time_trigger("cron(2 0 * * *)")
@catch_hc_trigger_error("refresh_constants_midnight")
def _refresh_constants_midnight():
    _refresh_daily_constants()


# Cache today's sunset at noon when it's most accurate
@time_trigger("cron(0 12 * * *)")
@catch_hc_trigger_error("cache_todays_sunset")
def _cache_todays_sunset():
    """Cache today's sunset time at noon when we know it's accurate"""
    sunset_raw = _get("sun.sun", attr="next_setting")
    if sunset_raw:
        try:
            sunset_str = str(sunset_raw)
            if "T" in sunset_str:
                sunset_dt = datetime.fromisoformat(sunset_str)
                if sunset_dt.tzinfo is not None:
                    sunset_dt = sunset_dt.astimezone()
                    sunset_dt = sunset_dt.replace(tzinfo=None)

            # Store in both MQTT and a sensor for easy access
            if sunset_dt.date() == _now().date():
                # MQTT for persistence
                payload = {
                    "sunset_time": sunset_dt.isoformat(),
                    "evening_start": (sunset_dt - timedelta(minutes=EVENING_START_OFFSET_MINUTES)).isoformat(),
                    "date": _now().date().isoformat()
                }
                _mqtt_publish("daily/sunset", payload)

                # Also store in a sensor for easy access
                _set_sensor("sensor.cached_sunset_today", sunset_dt.time().strftime("%H:%M:%S"), {
                    "friendly_name": "Cached Sunset Time",
                    "date": _now().date().isoformat(),
                    "full_datetime": sunset_dt.isoformat()
                })

                log.info(f"[HC] Cached today's sunset: {sunset_dt.strftime('%H:%M')}")
            else:
                log.warning(f"[HC] Cached sunset is for wrong date: {sunset_dt.date()} vs {_now().date()}")
        except Exception as e:
            log.warning(f"[HC] Failed to cache sunset: {e}")

# Refresh when inputs change
@state_trigger("sun.sun")
@state_trigger("input_datetime.evening_time_cutoff")
@state_trigger("input_datetime.day_earliest_time")
@state_trigger("pyscript.current_day_threshold")
@catch_hc_trigger_error("refresh_constants_inputs_changed")
def _refresh_constants_inputs_changed(value=None, old_value=None, **kwargs):
    _refresh_daily_constants()

# Evening ramp trigger at 20:00
@time_trigger("cron(0 20 * * *)")
@catch_hc_trigger_error("evening_ramp_20_trigger")
def _evening_ramp_20_trigger():
    _start_evening_ramp_if_needed()

# Evening mode entry check for ramp
@state_trigger("pyscript.home_state == 'Evening'")
@catch_hc_trigger_error("on_home_state_evening")
def _on_home_state_evening(value=None, old_value=None):
    if value == "Evening":
        _start_evening_ramp_if_needed()

# Update day commit/target when inputs change
@state_trigger("sensor.day_min_start")
@state_trigger("input_datetime.day_earliest_time")
@state_trigger("sensor.learned_day_start")
@state_trigger("sensor.day_learned_start")
@state_trigger("sensor.day_target_brightness_teaching")
@state_trigger("sensor.day_target_brightness_adaptive")
@state_trigger("sensor.day_target_brightness_intelligent")
@state_trigger("input_number.day_target_brightness_fallback")
@state_trigger("pyscript.day_target_brightness_fallback")
@catch_hc_trigger_error("publish_day_updates_on_change")
def _publish_day_updates_on_change(value=None, old_value=None):
    global _suppress_brightness_trigger
    if _suppress_brightness_trigger:
        return
    _publish_day_commit_and_target()

# ============================================================================
# SERVICES
# ============================================================================
@service("pyscript.home_controller_status")
@catch_hc_error("get_home_controller_status")
def get_home_controller_status():
    """Get comprehensive status of home controller"""
    now = _now()
    ramp_active = _get_boolean_state("sleep_in_ramp_active")
    ramp_brightness = _get("sensor.sleep_in_ramp_brightness")
    
    status = {
        "timestamp": now.isoformat(),
        "current_time": now.strftime("%H:%M:%S"),
        "controller_enabled": _is_controller_enabled(),
        "current_state": _get_home_state(),
        "presence": {
            "phone1": _get(PHONE_1),
            "phone2": _get(PHONE_2),
            "both_home": _are_both_phones_home(),
        },
        "early_morning": {
            "motion_classified_today": _morning_motion_classified_date == now.date(),
            "profile": _get("sensor.pys_morning_ramp_profile"),
            "workday_detected": _get("pyscript.motion_work_day_detected"),
            "reason": _get("sensor.pys_morning_ramp_reason"),
            "end_reason": _get("sensor.pys_em_end_reason"),
            "end_time": _get("sensor.pys_em_end_time"),
            "workday_window": f"{WORKDAY_MOTION_START.strftime('%H:%M')}-{WORKDAY_MOTION_END.strftime('%H:%M')}",
            "current_in_workday_window": WORKDAY_MOTION_START <= now.time() < WORKDAY_MOTION_END,
        },
        "morning_ramp": {
            "active": ramp_active,
            "current_brightness": ramp_brightness,
            "work_targets": f"{WORK_RAMP_START_BRIGHTNESS}% → {WORK_RAMP_END_BRIGHTNESS}%",
            "work_end_time": WORK_RAMP_END_TIME.strftime("%H:%M"),
        },
        "evening": {
            "start": _get("sensor.evening_start_local"),
            "cutoff": _get_evening_cutoff_time().strftime("%H:%M:%S"),
            "in_window": _get("binary_sensor.in_evening_window"),
            "mode_active": _get_boolean_state("evening_mode_active"),
            "done_today": _get_boolean_state("evening_done_today"),
            "ramp_started": _get_boolean_state("evening_ramp_started_today"),
            "ramp_window": f"{EV_RAMP_START_TIME.strftime('%H:%M')}-{EV_RAMP_END_TIME.strftime('%H:%M')}",
            "ramp_targets": f"{EV_RAMP_BRI}% / {EV_RAMP_START_K}K → {EV_RAMP_END_K}K",
            "last_reason": _get("sensor.evening_last_reason"),
        },
        "day": {
            "min_start": _get("sensor.day_min_start"),
            "earliest": _get_day_earliest_time_floor().strftime("%H:%M:%S"),
            "elev_target": _get("sensor.day_elev_target"),
            "elev_current": _get("sun.sun", attr="elevation"),
            "ready_now": _get("binary_sensor.day_ready_now"),
            "reason": _get("sensor.day_ready_reason"),
            "commit_time": _get("sensor.day_commit_time"),
            "target_brightness": _get("sensor.day_target_brightness"),
        },
        "night": {
            "started_on": _get("sensor.night_started_on"),
            "cutover_pending": _get("binary_sensor.pys_night_cutover_pending"),
            "failsafe_time": "23:00",
            "last_reason": _get("sensor.night_last_reason"),
            "waiting_for_bedroom_tv": _is_waiting_for_bedroom_tv(),
            "waiting_reason": _get("sensor.night_waiting_reason"),
            "waiting_timeout_active": bool(_waiting_timeout_task and not getattr(_waiting_timeout_task, "done", lambda: True)()),
        },
        "last_action": _get("sensor.pys_last_action"),
    }
    
    log.info(f"[HC] ===== STATUS REPORT =====")
    log.info(f"[HC] Mode: {status['current_state']} at {status['current_time']}")
    log.info(f"[HC] Ramp: {status['morning_ramp']}")
    log.info(f"[HC] =======================")
    return status

@service("pyscript.morning_ramp_first_motion")
async def morning_ramp_first_motion(entity: str = "automation.morning_ramp_trigger", sensor: str = None, **kwargs):
    """Direct motion classification trigger for testing"""
    src = sensor or entity or "automation.morning_ramp_trigger"
    try:
        await _coordinated_kitchen_motion_classification(src)
        log.info(f"[HC] Triggered classification for {src}")
    except Exception as e:
        log.error(f"[HC] Classification failed: {e}")
        # Fallback: simulate motion
        eid = "binary_sensor.kitchen_test_simulated_motion"
        state.set(eid, "on", {"friendly_name": "Kitchen Test Motion"})
        state.set(eid, "off")
@catch_hc_error("force_early_morning")
def force_early_morning_classification(profile: str = "work"):
    """Force Early Morning classification for testing"""
    global _morning_motion_classified_date, _morning_motion_profile
    
    if profile not in ("work", "day_off"):
        log.error(f"[HC] Invalid profile: {profile}")
        return
    
    _morning_motion_classified_date = None
    _morning_motion_profile = None
    
    log.info(f"[HC] FORCING Early Morning classification: {profile}")
    
    _morning_motion_classified_date = _now().date()
    _morning_motion_profile = profile
    
    _set_sensor("sensor.pys_morning_ramp_profile", profile, {
        "source": "forced", 
        "reason": f"forced_{profile}"
    })
    _set_sensor("pyscript.motion_work_day_detected", "on" if profile == "work" else "off")
    now = _now()
    _set_sensor("sensor.pys_em_classification_time", now.isoformat(), {
        "friendly_name": "Early Morning Classification Time",
        "source": "forced"
    })

    _set_input_text("input_text.em_route_key", profile)
    _set_input_datetime("input_datetime.em_start_ts", now)
    _set_input_text("input_text.em_until", "")
    _set_boolean_state("em_active", "on")

    try:
        service.call("input_datetime", "set_datetime",
                     entity_id="input_datetime.first_kitchen_motion_today",
                     datetime=now.strftime("%Y-%m-%d %H:%M:%S"))
    except Exception:
        pass

    _set_boolean_state("daily_motion_lock", "on")

    _set_home_state("Early Morning")
    _set_last_action(f"forced_early_morning:{profile}")
    
    # Start the appropriate ramp
    global _work_ramp_task, _nonwork_ramp_task
    if profile == "work":
        _cancel_task_if_running(_work_ramp_task, "work_ramp")
        _cancel_task_if_running(_nonwork_ramp_task, "nonwork_ramp")
        _work_ramp_task = task.create(_start_work_ramp(restore_from_time=now))
    else:
        _cancel_task_if_running(_nonwork_ramp_task, "nonwork_ramp")
        _cancel_task_if_running(_work_ramp_task, "work_ramp")
        _nonwork_ramp_task = task.create(_start_nonwork_ramp(start_time_override=now))
    
    log.info(f"[HC] Early Morning mode set with {profile} profile and ramp started")
    _publish_em_contract()


@service("pyscript.morning_ramp_force_end")
@catch_hc_error("morning_ramp_force_end")
def _service_morning_ramp_force_end(reason: str = "manual_force_end"):
    """Manual escape hatch to end the current ramp"""
    if _get_boolean_state("sleep_in_ramp_active") == "on":
        _set_boolean_state("sleep_in_ramp_active", "off")
        _mark_em_end(reason)
        _set_last_action(f"morning_ramp_force_end:{reason}")
    _set_boolean_state("daily_motion_lock", "off")
    _set_em_status("force_end", {"reason": reason})
    _publish_em_contract()


@service("pyscript.morning_ramp_reset_today")
@catch_hc_error("morning_ramp_reset_today")
def _service_morning_ramp_reset_today():
    """Reset daily ramp guards so testing can retrigger"""
    _morning_reset()
    _set_boolean_state("daily_motion_lock", "off")
    log.info("[HC] Morning ramp guards reset via service call")
    _set_em_status("reset_today", {})
    _publish_em_contract()


@service("pyscript.morning_ramp_test_trigger")
@catch_hc_error("morning_ramp_test_trigger")
def _service_morning_ramp_test_trigger(profile: str = "work", hour: int = None, minute: int = None, prework: bool = False):
    """Testing helper mirroring the legacy morning ramp trigger"""
    profile = profile if profile in ("work", "day_off") else "work"
    force_early_morning_classification(profile)

    override_time = None
    if hour is not None and minute is not None:
        try:
            override_time = _now().replace(hour=int(hour), minute=int(minute), second=0, microsecond=0)
        except Exception:
            override_time = None

    if profile == "work":
        if prework:
            override_time = (_now().replace(hour=WORKDAY_MOTION_START.hour,
                                            minute=WORKDAY_MOTION_START.minute,
                                            second=0,
                                            microsecond=0))
        if override_time:
            global _work_ramp_task
            _cancel_task_if_running(_work_ramp_task, "work_ramp_test")
            _work_ramp_task = task.create(_start_work_ramp(restore_from_time=override_time))
    else:
        if override_time:
            global _nonwork_ramp_task
            _cancel_task_if_running(_nonwork_ramp_task, "nonwork_ramp_test")
            _nonwork_ramp_task = task.create(_start_nonwork_ramp(start_time_override=override_time))

    _set_last_action(f"morning_ramp_test_trigger:{profile}")

@service("pyscript.set_day_brightness_teaching")
@catch_hc_error("set_day_brightness_teaching")
def set_day_brightness_teaching(brightness: int):
    """Set teaching brightness override"""
    brightness = max(0, min(100, int(brightness)))
    _set_sensor("sensor.day_target_brightness_teaching", brightness, {
        "friendly_name": "Day Target Brightness (Teaching)",
        "unit_of_measurement": "%",
        "set_at": _now().isoformat(),
        "priority": 1
    })
    log.info(f"[HC] Teaching brightness set to {brightness}%")

@service("pyscript.set_learned_day_start")
@catch_hc_error("set_learned_day_start")
def set_learned_day_start(time_str: str):
    """Set learned day start time"""
    try:
        # Validate time format
        if ":" in time_str:
            parts = time_str.split(":")
            hour, minute = int(parts[0]), int(parts[1])
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                now = _now()
                learned_dt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
                _set_sensor("sensor.learned_day_start", learned_dt.isoformat(), {
                    "friendly_name": "Learned Day Start Time",
                    "learned_at": now.isoformat()
                })
                log.info(f"[HC] Learned day start set to {time_str}")
            else:
                log.error(f"[HC] Invalid time values: {time_str}")
        else:
            log.error(f"[HC] Invalid time format: {time_str}")
    except Exception as e:
        log.error(f"[HC] Error setting learned day start: {e}")

@service("pyscript.force_refresh_constants")
@catch_hc_error("force_refresh_constants")
def force_refresh_constants():
    """Force refresh daily constants (sunset, sunrise, etc.)"""
    log.info("[HC] ========== FORCE REFRESHING DAILY CONSTANTS ==========")
    log.info("[HC] FORCE REFRESH SERVICE CALLED - TESTING IF SERVICES WORK")
    _refresh_daily_constants()
    log.info("[HC] ========== DAILY CONSTANTS REFRESHED ==========")

@service("pyscript.test_service")
@catch_hc_error("test_service")
def test_service():
    """Simple test service to verify service system is working"""
    log.info("[HC] ========== TEST SERVICE CALLED ==========")
    log.info("[HC] If you can see this, the service system is working!")
    log.info(f"[HC] Current time: {_now().strftime('%H:%M:%S')}")
    log.info(f"[HC] Current home state: {_get_home_state()}")

    # Test MQTT connectivity
    log.info("[HC] Testing MQTT connectivity...")
    try:
        mqtt_available = _get("mqtt")
        log.info(f"[HC] MQTT integration available: {mqtt_available}")

        if mqtt_available:
            # Try to publish a test message
            test_payload = {
                "test": "mqtt_connectivity_test",
                "timestamp": _now().isoformat(),
                "home_state": _get_home_state()
            }
            _mqtt_publish("test/connectivity", test_payload)
            log.info("[HC] MQTT test message sent successfully")
        else:
            log.warning("[HC] MQTT integration not available - check Home Assistant MQTT configuration")
    except Exception as e:
        log.error(f"[HC] MQTT test failed: {e}")

    log.info("[HC] ========== TEST SERVICE COMPLETE ==========")

@service("pyscript.force_evening_mode")
@catch_hc_error("force_evening_mode")
def force_evening_mode():
    """Force enter evening mode for testing"""
    log.info("[HC] ========== FORCE EVENING MODE CALLED ==========")
    log.info(f"[HC] Current time: {_now().strftime('%H:%M:%S')}")
    log.info(f"[HC] Current home state: {_get_home_state()}")

    if _enter_evening("force_service_test", force=True):
        log.info("[HC] Successfully forced evening mode")
        _start_evening_ramp_if_needed()
        log.info("[HC] Started evening ramp if needed")
    else:
        log.warning("[HC] Failed to force evening mode")

    log.info("[HC] ========== FORCE EVENING MODE COMPLETE ==========")

@service("pyscript.force_evening_window")
@catch_hc_error("force_evening_window")
def force_evening_window():
    """Force the evening window to be active for testing"""
    log.info("[HC] ========== FORCE EVENING WINDOW CALLED ==========")
    log.info(f"[HC] Current time: {_now().strftime('%H:%M:%S')}")

    # Force set evening window to on
    _set_sensor("binary_sensor.in_evening_window", "on", {
        "friendly_name": "In Evening Window",
        "reason": "forced_for_testing",
        "start": _now().isoformat(),
        "cutoff": "23:00:00"
    })

    log.info("[HC] Evening window forced to ON")
    log.info("[HC] ========== FORCE EVENING WINDOW COMPLETE ==========")

@service("pyscript.force_day_mode")
@catch_hc_error("force_day_mode")
def force_day_mode():
    """Force enter Day mode for testing"""
    log.info("[HC] ========== FORCE DAY MODE CALLED ==========")
    log.info(f"[HC] Current time: {_now().strftime('%H:%M:%S')}")
    log.info(f"[HC] Current home state: {_get_home_state()}")

    if _set_home_state("Day"):
        log.info("[HC] Successfully forced Day mode")
        # Clear evening flags
        _set_boolean_state("evening_mode_active", "off")
        _set_boolean_state("evening_done_today", "off")
        log.info("[HC] Cleared evening flags")
    else:
        log.warning("[HC] Failed to force Day mode")

    log.info("[HC] ========== FORCE DAY MODE COMPLETE ==========")

@service("pyscript.check_mqtt_status")
@catch_hc_error("check_mqtt_status")
def check_mqtt_status():
    """Check MQTT integration status and provide detailed diagnostics"""
    log.info("[HC] ========== MQTT STATUS CHECK ==========")

    # Check multiple ways MQTT might be available
    checks = {}

    # Check 1: Basic MQTT entity
    checks["mqtt_entity"] = _get("mqtt")
    log.info(f"[HC] MQTT entity check: {checks['mqtt_entity']}")

    # Check 2: MQTT broker status
    checks["broker_status"] = _get("binary_sensor.mqtt_broker_status") or _get("sensor.mqtt_broker_status")
    log.info(f"[HC] MQTT broker status: {checks['broker_status']}")

    # Check 3: Try MQTT service call
    try:
        service.call("mqtt", "publish", topic="home/test", payload="test")
        checks["service_test"] = "success"
        log.info("[HC] MQTT service test: success")
    except Exception as e:
        checks["service_test"] = f"failed: {e}"
        log.info(f"[HC] MQTT service test: failed - {e}")

    # Check 4: Look for MQTT integration in integrations
    try:
        # This is a best-effort check - may not work in all PyScript environments
        integrations = state.names(domain="integration")
        mqtt_integrations = [i for i in integrations if "mqtt" in i.lower()]
        checks["integrations_found"] = mqtt_integrations
        log.info(f"[HC] MQTT integrations found: {mqtt_integrations}")
    except Exception as e:
        checks["integrations_found"] = f"check_failed: {e}"
        log.info(f"[HC] Integration check failed: {e}")

    # Determine overall status
    mqtt_available = (
        checks["mqtt_entity"] is not None or
        (checks["broker_status"] and str(checks["broker_status"]).lower() not in ("off", "unavailable", "unknown")) or
        checks["service_test"] == "success"
    )

    log.info(f"[HC] Overall MQTT available: {mqtt_available}")
    log.info("[HC] ========== MQTT STATUS CHECK COMPLETE ==========")

    return {
        "mqtt_available": mqtt_available,
        "checks": checks,
        "recommendations": [
            "If mqtt_available is False, configure MQTT integration in Home Assistant",
            "Go to Settings > Devices & Services > Add Integration > MQTT",
            "Configure broker settings and restart Home Assistant",
            "Check Home Assistant logs for MQTT connection errors"
        ] if not mqtt_available else ["MQTT integration is working correctly"]
    }

@service("pyscript.test_mqtt")
@catch_hc_error("test_mqtt")
def test_mqtt():
    """Test MQTT connectivity and publish test messages"""
    log.info("[HC] ========== MQTT TEST SERVICE CALLED ==========")

    # Check MQTT integration using multiple methods
    mqtt_available = False
    detection_method = "none"

    # Method 1: Check for MQTT integration entity
    if _get("mqtt") is not None:
        mqtt_available = True
        detection_method = "mqtt_entity"
    else:
        # Method 2: Check for MQTT broker entity
        mqtt_broker = _get("binary_sensor.mqtt_broker_status") or _get("sensor.mqtt_broker_status")
        if mqtt_broker and str(mqtt_broker).lower() not in ("off", "unavailable", "unknown"):
            mqtt_available = True
            detection_method = "broker_status"
        else:
            # Method 3: Try to call MQTT service directly and catch errors
            try:
                service.call("mqtt", "publish", topic="home/test", payload="test")
                mqtt_available = True
                detection_method = "service_test"
                log.info("[HC] MQTT integration confirmed available via test publish")
            except Exception:
                mqtt_available = False
                detection_method = "service_test_failed"

    log.info(f"[HC] MQTT integration available: {mqtt_available} (detected via: {detection_method})")

    if not mqtt_available:
        log.error("[HC] MQTT integration not available!")
        log.error("[HC] Please check:")
        log.error("[HC] 1. Home Assistant Settings > Devices & Services")
        log.error("[HC] 2. Look for MQTT integration")
        log.error("[HC] 3. If not found, add 'MQTT' integration")
        log.error("[HC] 4. Configure broker settings (host, port, credentials)")
        log.error("[HC] 5. Restart Home Assistant after configuration")
        log.error("[HC] 6. Check logs for MQTT connection errors")
        return {
            "mqtt_available": False,
            "detection_method": detection_method,
            "error": "MQTT integration not configured",
            "instructions": "Enable MQTT integration in Home Assistant",
            "troubleshooting": [
                "Check Settings > Devices & Services for MQTT integration",
                "Add MQTT integration if missing",
                "Configure broker connection settings",
                "Restart Home Assistant",
                "Check Home Assistant logs for MQTT errors"
            ]
        }

    # Test publishing to different topics
    test_topics = [
        "home/rework/controller/test/connectivity",
        "home/rework/controller/daily/sunset",
        "home/rework/controller/daily_constants/evening_window"
    ]

    results = {}
    for topic in test_topics:
        try:
            payload = {
                "test": "mqtt_test",
                "topic": topic,
                "timestamp": _now().isoformat(),
                "home_state": _get_home_state()
            }
            # Extract path from full topic for _mqtt_publish function
            path = topic.replace(f"{_MQTT_PREFIX}/", "")
            _mqtt_publish(path, payload)
            results[topic] = "success"
            log.info(f"[HC] Successfully published to: {topic}")
        except Exception as e:
            results[topic] = f"failed: {e}"
            log.error(f"[HC] Failed to publish to {topic}: {e}")

    log.info("[HC] ========== MQTT TEST COMPLETE ==========")
    return {
        "mqtt_available": True,
        "detection_method": detection_method,
        "test_results": results,
        "expected_topics": test_topics,
        "note": "If messages don't appear in your MQTT broker, check broker configuration and topic subscriptions"
    }

@service("pyscript.debug_evening_window")
@catch_hc_error("debug_evening_window")
def debug_evening_window():
    """Debug evening window activation - call this to see why evening mode isn't activating"""
    now = _now()
    current_time = now.strftime("%H:%M:%S")
    current_state = _get_home_state()

    log.info(f"[HC][DEBUG_EVENING] ========== EVENING WINDOW DEBUG at {current_time} ==========")
    log.info(f"[HC][DEBUG_EVENING] Current home state: {current_state}")

    # Check evening window sensor
    evening_window = _get("binary_sensor.in_evening_window")
    evening_window_attrs = state.getattr("binary_sensor.in_evening_window") or {}
    log.info(f"[HC][DEBUG_EVENING] Evening window sensor: {evening_window}")
    log.info(f"[HC][DEBUG_EVENING] Evening window attributes: {evening_window_attrs}")

    # Check sunset data
    sunset_raw = _get("sun.sun", attr="next_setting")
    sunset_elev = _get("sun.sun", attr="elevation")
    log.info(f"[HC][DEBUG_EVENING] Sunset raw: {sunset_raw}")
    log.info(f"[HC][DEBUG_EVENING] Sunset elevation: {sunset_elev}")

    # Check cached values
    log.info(f"[HC][DEBUG_EVENING] Cached evening start: {_cached_evening_start}")
    log.info(f"[HC][DEBUG_EVENING] Cached cutoff: {_cached_cutoff_hm}")

    # Check evening completion status
    evening_done = _get_boolean_state("evening_done_today")
    evening_active = _get_boolean_state("evening_mode_active")
    log.info(f"[HC][DEBUG_EVENING] Evening done today: {evening_done}")
    log.info(f"[HC][DEBUG_EVENING] Evening mode active: {evening_active}")

    # Check night status
    night_started = _night_started_on()
    log.info(f"[HC][DEBUG_EVENING] Night started today: {night_started}")
    log.info(f"[HC][DEBUG_EVENING] Today: {_today_str()}")

    # Check evening start sensor
    evening_start_local = _get("sensor.evening_start_local")
    log.info(f"[HC][DEBUG_EVENING] Evening start local: {evening_start_local}")

    # Check evening cutoff time
    cutoff_time = _get_evening_cutoff_time()
    log.info(f"[HC][DEBUG_EVENING] Evening cutoff time: {cutoff_time}")

    # Check if conditions would allow evening entry
    conditions_met = (
        current_state == "Day" and
        evening_window == "on" and
        night_started != _today_str() and
        evening_done != "on"
    )
    log.info(f"[HC][DEBUG_EVENING] Conditions for evening entry: {conditions_met}")
    log.info(f"[HC][DEBUG_EVENING] - Home state is Day: {current_state == 'Day'}")
    log.info(f"[HC][DEBUG_EVENING] - Evening window is on: {evening_window == 'on'}")
    log.info(f"[HC][DEBUG_EVENING] - Night not started today: {night_started != _today_str()}")
    log.info(f"[HC][DEBUG_EVENING] - Evening not done today: {evening_done != 'on'}")

    # Manual trigger attempt
    if conditions_met:
        log.info(f"[HC][DEBUG_EVENING] All conditions met - attempting manual evening entry")
        if _enter_evening("debug_manual_trigger"):
            log.info(f"[HC][DEBUG_EVENING] Manual evening entry successful")
        else:
            log.info(f"[HC][DEBUG_EVENING] Manual evening entry failed")
    else:
        log.info(f"[HC][DEBUG_EVENING] Conditions not met - cannot enter evening mode")

    log.info(f"[HC][DEBUG_EVENING] ========== END EVENING WINDOW DEBUG ==========")

    # Return debug info
    return {
        "current_time": current_time,
        "current_state": current_state,
        "evening_window": evening_window,
        "evening_window_attrs": evening_window_attrs,
        "sunset_raw": sunset_raw,
        "sunset_elevation": sunset_elev,
        "cached_evening_start": str(_cached_evening_start),
        "cached_cutoff": _cached_cutoff_hm,
        "evening_done": evening_done,
        "evening_active": evening_active,
        "night_started": night_started,
        "today": _today_str(),
        "evening_start_local": evening_start_local,
        "cutoff_time": cutoff_time.strftime("%H:%M:%S"),
        "conditions_met": conditions_met
    }

# Log startup
log.info("[HC] ========== HOME CONTROLLER STARTING (REWORK COMPLIANT) ==========")
log.info("[HC] Home Controller REWORK COMPLIANT - Every SET IN STONE requirement implemented")
log.info("[HC] Available services: test_service, check_mqtt_status, test_mqtt, force_refresh_constants, debug_evening_window, force_evening_mode, force_evening_window, force_day_mode")
log.info("[HC] MQTT Topics: home/rework/controller/daily/sunset, home/rework/controller/daily_constants/evening_window")
log.info("[HC] ========== HOME CONTROLLER READY ==========")

# Force a log entry every minute to verify script is running
@time_trigger("cron(* * * * *)")
@catch_hc_trigger_error("heartbeat")
def _heartbeat():
    """Heartbeat to verify script is running"""
    log.info("[HC] HEARTBEAT - Script is running and active")
    # Update a sensor to show script is active
    _set_sensor("sensor.pyscript_hc_active", "on", {
        "friendly_name": "Home Controller Active",
        "last_heartbeat": _now().isoformat()
    })


def _hc_now():
    """Return simulated time if freeze is active, else real time."""
    try:
        if str(state.get("input_boolean.time_freeze_active")).lower() == "on":
            raw = state.get("input_datetime.time_freeze_clock")
            if raw:
                from datetime import datetime as _dt
                return _dt.fromisoformat(str(raw).replace("T", " "))
    except Exception:
        pass
    from datetime import datetime as _dt
    return _dt.now()


def _hc_parse_dt(val):
    """Parse a datetime string robustly:
       - Supports ISO with/without 'T'
       - Handles microseconds and optional timezone
       - Falls back to common strptime formats
    """
    from datetime import datetime as _dt
    if val is None:
        raise ValueError("None datetime")
    text = str(val).strip()
    if not text:
        raise ValueError("empty datetime")
    # Normalize ISO quirks
    txt = text.replace("T", " ").replace("Z", "+00:00")
    # Try Python's tolerant ISO parser first
    try:
        return _dt.fromisoformat(txt)
    except Exception:
        pass
    # Fallback formats (tz + micros / micros / no micros)
    for fmt in ("%Y-%m-%d %H:%M:%S.%f%z",
                "%Y-%m-%d %H:%M:%S.%f",
                "%Y-%m-%d %H:%M:%S%z",
                "%Y-%m-%d %H:%M:%S"):
        try:
            return _dt.strptime(txt, fmt)
        except Exception:
            continue
    raise ValueError(f"Unparseable datetime: {text}")
