# /config/pyscript/laundry_motion.py (Created 2025-09-14)
# COMPLETE PyScript laundry controller - SINGLE FILE ONLY
# Handles motion detection, brightness calculations, mode transitions
# Simple and reliable - follows hallway/kitchen patterns

from datetime import datetime, time as dt_time
import asyncio

# ===== Entities =====
LAUNDRY_LIGHT = "light.laundry_room"
LAUNDRY_MOTION = "binary_sensor.laundry_iris_occupancy"
HOME_STATE = "input_select.home_state"
ALLOWED_MODES = {"Day", "Evening", "Night", "Early Morning"}  # All modes except Away

# ===== Configuration =====
MOTION_TIMEOUT_SECONDS = 30  # Default timeout

# Fallback brightness values
FALLBACK_DAY_BRIGHTNESS = 80      # 80% for daytime
FALLBACK_EVENING_BRIGHTNESS = 60  # 60% for evening
FALLBACK_NIGHT_BRIGHTNESS = 1     # 1% for night

# System entities for brightness calculations
RAMP_ACTIVE = "input_boolean.sleep_in_ramp_active"
RAMP_BRIGHTNESS = "sensor.sleep_in_ramp_brightness"
ADAPTIVE_LEARNING_ENABLED = "input_boolean.adaptive_learning_enabled"
INTELLIGENT_LIGHTING_ENABLED = "input_boolean.intelligent_lighting_enable"
ALL_ROOMS_USE_PYSCRIPT = "input_boolean.all_rooms_use_pyscript"
LEARNED_BRIGHTNESS = "sensor.learned_brightness_laundry"
INTELLIGENT_BRIGHTNESS = "sensor.intelligent_brightness_laundry"
PYSCRIPT_BRIGHTNESS = "pyscript.test_laundry_brightness"

# Brightness caching to prevent changes during same motion event
cached_brightness = None
motion_start_time = None

# ===========================

# --- Helpers ---
def _state(eid, d=None):
    try:
        v = state.get(eid)
        return v if v not in (None, "unknown", "unavailable") else d
    except Exception:
        return d

def _info(msg): log.info(f"[LaundryALS] {msg}")
def _warn(msg): log.warning(f"[LaundryALS] {msg}")
def _error(msg): log.error(f"[LaundryALS] {msg}")

# --- Brightness Calculation ---
def calculate_laundry_brightness():
    """Calculate laundry target brightness with proper priority order"""
    
    # Morning Ramp has highest priority
    if _state(RAMP_ACTIVE) == "on":
        ramp_bri = _state(RAMP_BRIGHTNESS)
        if ramp_bri not in ["unavailable", "unknown", None]:
            _info(f"Brightness source: Morning Ramp ({ramp_bri}%)")
            return max(1, min(100, int(float(ramp_bri))))
    
    # Night Mode Lock
    if _state(HOME_STATE) == "Night":
        _info(f"Brightness source: Night Mode Lock ({FALLBACK_NIGHT_BRIGHTNESS}%)")
        return FALLBACK_NIGHT_BRIGHTNESS
    
    # Adaptive Learning
    if _state(ADAPTIVE_LEARNING_ENABLED) == "on":
        learned = _state(LEARNED_BRIGHTNESS)
        try:
            learned_attrs = state.getattr(LEARNED_BRIGHTNESS)
            using_learned = learned_attrs.get("using_learned", False) if learned_attrs else False
        except Exception:
            using_learned = False
        if learned not in ["unavailable", "unknown", None] and using_learned:
            _info(f"Brightness source: Adaptive Learning ({learned}%)")
            return max(1, min(100, int(float(learned))))
    
    # PyScript Engine
    if _state(ALL_ROOMS_USE_PYSCRIPT) == "on":
        pyscript_bri = _state(PYSCRIPT_BRIGHTNESS)
        if pyscript_bri not in ["unavailable", "unknown", None]:
            _info(f"Brightness source: PyScript Engine ({pyscript_bri}%)")
            return max(1, min(100, int(float(pyscript_bri))))
    
    # Intelligent System
    if _state(INTELLIGENT_LIGHTING_ENABLED) == "on":
        intelligent_bri = _state(INTELLIGENT_BRIGHTNESS)
        if intelligent_bri not in ["unavailable", "unknown", None]:
            _info(f"Brightness source: Intelligent System ({intelligent_bri}%)")
            return max(1, min(100, int(float(intelligent_bri))))
    
    # Fallback Values by Mode
    home_mode = _state(HOME_STATE, "unknown")
    if home_mode in ["Evening", "Early Morning"]:
        _info(f"Brightness source: Fallback Evening ({FALLBACK_EVENING_BRIGHTNESS}%)")
        return FALLBACK_EVENING_BRIGHTNESS
    elif home_mode == "Day":
        _info(f"Brightness source: Fallback Day ({FALLBACK_DAY_BRIGHTNESS}%)")
        return FALLBACK_DAY_BRIGHTNESS
    else:
        _info(f"Brightness source: Default Fallback (60%)")
        return 60

def _trigger_morning_ramp(sensor_name: str):
    """Trigger morning ramp service when motion detected in Night mode during morning hours"""
    try:
        hs = _state(HOME_STATE)
        ramp_enabled = _state("input_boolean.sleep_in_ramp_system_enable", "on") in ["on", "unknown", "unavailable", ""]
        
        # TIME CHECK: Only trigger morning ramp during appropriate morning hours
        now_time = datetime.now().time()
        morning_start = dt_time(4, 0, 0)   # 4:00 AM
        morning_end = dt_time(10, 0, 0)    # 10:00 AM
        is_morning_hours = morning_start <= now_time <= morning_end
        
        if hs == "Night" and ramp_enabled and is_morning_hours:
            _warn(f"🔥 MORNING RAMP: Calling from {sensor_name} at {now_time.strftime('%H:%M')}")
            service.call("pyscript", "morning_ramp_first_motion", sensor=sensor_name)
        else:
            reasons = []
            if hs != "Night":
                reasons.append(f"mode={hs}")
            if not ramp_enabled:
                reasons.append("ramp_disabled")
            if not is_morning_hours:
                reasons.append(f"time={now_time.strftime('%H:%M')}")
            _info(f"Morning ramp not triggered: {', '.join(reasons)}")
    except Exception as e:
        _error(f"Failed to trigger morning ramp: {e}")

def _light_on(entity_id: str, **kwargs):
    try:
        service.call("light", "turn_on", entity_id=entity_id, **kwargs)
        _info(f"Light ON -> {entity_id} {kwargs if kwargs else ''}")
    except Exception as e:
        _error(f"Light on error on {entity_id}: {e}")

def _light_off(entity_id: str):
    try:
        service.call("light", "turn_off", entity_id=entity_id)
        _info(f"Light OFF -> {entity_id}")
    except Exception as e:
        _error(f"Light off error on {entity_id}: {e}")

# --- Core Behavior ---
def _apply_for_motion(active: bool, reason: str):
    global cached_brightness
    
    hs = _state(HOME_STATE, "unknown")
    
    # CRITICAL: Don't turn on lights in Away mode
    if hs == "Away":
        _warn(f"🚫 SKIP - Away mode protection active")
        return
    
    if hs not in ALLOWED_MODES:
        _warn(f"🚫 SKIP - Invalid mode: {hs}")
        return
    
    _info(f"APPLY motion_active={active} mode={hs} reason={reason}")
    
    if active:
        # Use cached brightness if available, otherwise calculate fresh
        if cached_brightness is not None:
            br = cached_brightness
            _info(f"Using cached brightness: {br}%")
        else:
            br = calculate_laundry_brightness()
            _info(f"Using fresh brightness: {br}%")
        
        # Check if light is already on at correct brightness
        current_state = _state(LAUNDRY_LIGHT)
        if current_state == "on":
            try:
                current_br_raw = state.getattr(LAUNDRY_LIGHT).get("brightness", 0)
                current_br_pct = int((current_br_raw / 255) * 100) if current_br_raw else 0
                
                if abs(current_br_pct - br) < 3:  # Within 3%, don't send command
                    _info(f"Light already at {current_br_pct}%, target {br}% - skipping")
                    return
            except:
                pass  # If we can't check, just send the command
        
        _light_on(LAUNDRY_LIGHT, brightness_pct=br)
        _info(f"Laundry light ON at {br}%")
    else:
        # Turn OFF laundry light
        _light_off(LAUNDRY_LIGHT)
        _info(f"Laundry light OFF (motion clear)")

# --- Motion Listener ---
@state_trigger(LAUNDRY_MOTION)
async def laundry_motion_listener(**kwargs):
    global cached_brightness, motion_start_time
    
    eid = kwargs.get("var_name")
    new = _state(eid)
    current_time = datetime.now()
    
    _info(f"Listener: {eid} -> {new} @ {current_time.strftime('%H:%M:%S')}")
    
    if new == "on":
        # NEW MOTION: Calculate and cache brightness
        cached_brightness = calculate_laundry_brightness()
        motion_start_time = current_time
        _info(f"Cached brightness: {cached_brightness}% for new motion event")
        
        # Trigger morning ramp if appropriate
        _trigger_morning_ramp(eid)
        _apply_for_motion(True, reason=f"{eid} active")
    else:
        # Motion cleared - start debounce but DON'T reset cache yet
        original_cache = cached_brightness
        original_start_time = motion_start_time
        await asyncio.sleep(MOTION_TIMEOUT_SECONDS)
        
        # Check if motion is still clear after debounce
        if _state(LAUNDRY_MOTION) == "off":
            # Only clear cache after successful debounce
            cached_brightness = None
            motion_start_time = None
            _apply_for_motion(False, reason="debounced clear")
        else:
            # Motion returned during debounce - restore original cache
            cached_brightness = original_cache
            motion_start_time = original_start_time
            _info("Clear aborted (motion returned during debounce) - brightness cache restored")

# --- Mode-based Control ---
@state_trigger("input_select.home_state == 'Away'")
def laundry_away_mode():
    """Turn off laundry lights when entering Away mode"""
    _info("LAUNDRY CONTROL: Turning off lights for Away mode")
    _light_off(LAUNDRY_LIGHT)

@state_trigger("input_select.home_state == 'Day'")
@state_trigger("input_select.home_state == 'Evening'")
@state_trigger("input_select.home_state == 'Night'")
@state_trigger("input_select.home_state == 'Early Morning'")
def laundry_mode_reset():
    """Reset laundry when entering allowed modes"""
    hs = _state(HOME_STATE, "unknown")
    _info(f"LAUNDRY CONTROL: Resetting for {hs} mode (will respond to motion)")
    # Could turn off light here if desired, or leave as is

# --- Sensor Publishers ---
def publish_laundry_sensors():
    """Publish laundry sensors (replaces YAML template sensors)"""
    try:
        # Target Brightness Sensor
        if cached_brightness is not None:
            brightness = cached_brightness
            source = "CACHED"
        else:
            brightness = calculate_laundry_brightness()
            source = get_calculation_source()
        
        state.set("sensor.laundry_room_target_brightness", brightness, {
            "friendly_name": "Laundry Room Target Brightness",
            "unit_of_measurement": "%",
            "calculation_source": source
        })
        
        # Status Sensor
        motion = _state(LAUNDRY_MOTION) == "on"
        home_mode = _state(HOME_STATE, "unknown")
        
        if home_mode == "Away":
            status = "🚪 Away Mode"
        elif motion:
            status = f"💡 Motion Active ({brightness}%)"
        else:
            status = f"🧺 Ready ({source})"
        
        # Set icon based on status
        if "🚪" in status:
            icon = "mdi:home-export-outline"
        elif "💡" in status:
            icon = "mdi:lightbulb-on"
        else:
            icon = "mdi:washing-machine"
        
        state.set("sensor.laundry_room_als_status", status, {
            "friendly_name": "Laundry Room ALS Status",
            "icon": icon
        })
    
    except Exception as e:
        _error(f"Failed to publish sensors: {e}")

def get_calculation_source():
    """Get current calculation source for attributes"""
    if _state(RAMP_ACTIVE) == "on":
        return "Morning Ramp"
    elif _state(HOME_STATE) == "Night":
        return "Night Mode Lock"
    elif _state(ADAPTIVE_LEARNING_ENABLED) == "on":
        try:
            learned_attrs = state.getattr(LEARNED_BRIGHTNESS)
            learned = learned_attrs.get("using_learned", False) if learned_attrs else False
        except:
            learned = False
        if learned:
            return "Adaptive Learning"
    elif _state(ALL_ROOMS_USE_PYSCRIPT) == "on":
        return "PyScript Engine"
    elif _state(INTELLIGENT_LIGHTING_ENABLED) == "on":
        return "Intelligent System"
    else:
        return "Fallback Values"

# --- Manual Services ---
@service("pyscript.laundry_smoke_test")
def laundry_smoke_test():
    """Test laundry light control"""
    _info("SMOKE TEST: Laundry light ON at 60%, then OFF")
    _light_on(LAUNDRY_LIGHT, brightness_pct=60)
    import time
    time.sleep(2)
    _light_off(LAUNDRY_LIGHT)
    publish_laundry_sensors()

@service("pyscript.laundry_force")
def laundry_force(mode: str = "on"):
    """Force laundry light on/off"""
    if mode == "on":
        br = calculate_laundry_brightness()
        _light_on(LAUNDRY_LIGHT, brightness_pct=br)
    else:
        _light_off(LAUNDRY_LIGHT)
    publish_laundry_sensors()

@service("pyscript.laundry_debug_status")
def laundry_debug_status():
    """Debug current state of laundry components"""
    _info("=== LAUNDRY DEBUG STATUS ===")
    _info(f"Home State: {_state(HOME_STATE)}")
    _info(f"Motion: {_state(LAUNDRY_MOTION)}")
    _info(f"Light: {_state(LAUNDRY_LIGHT)}")
    _info(f"Cached Brightness: {cached_brightness}")
    _info("=== END DEBUG ===")

# --- Startup and Regular Updates ---
@time_trigger("startup")
def laundry_startup():
    """Initialize laundry system on startup"""
    _info("Laundry system starting up")
    publish_laundry_sensors()

@time_trigger("cron(* * * * *)")
def laundry_minute_update():
    """Update sensors every minute"""
    publish_laundry_sensors()