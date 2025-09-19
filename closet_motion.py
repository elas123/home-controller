# /config/pyscript/closet_motion.py (Created 2025-09-14)
# COMPLETE PyScript closet/bedroom controller - SINGLE FILE ONLY
# Handles motion detection, brightness + color temperature
# Integrates with morning ramp and evening mode

from datetime import datetime, time as dt_time
import asyncio

# ===== Entities =====
CLOSET_LIGHT = "light.closet"
BEDROOM_MOTION = "binary_sensor.bedroom_x_occupancy"
HOME_STATE = "input_select.home_state"
ALLOWED_MODES = {"Day", "Evening", "Night", "Early Morning"}  # All modes except Away

# ===== Configuration =====
MOTION_TIMEOUT_SECONDS = 30  # Default timeout

# Fallback brightness values
FALLBACK_DAY_BRIGHTNESS = 60
FALLBACK_EVENING_BRIGHTNESS = 40
FALLBACK_NIGHT_BRIGHTNESS = 1

# System entities for brightness calculations
RAMP_ACTIVE = "input_boolean.sleep_in_ramp_active"
RAMP_BRIGHTNESS = "sensor.sleep_in_ramp_brightness"
ADAPTIVE_LEARNING_ENABLED = "input_boolean.adaptive_learning_enabled"
INTELLIGENT_LIGHTING_ENABLED = "input_boolean.intelligent_lighting_enable"
ALL_ROOMS_USE_PYSCRIPT = "input_boolean.all_rooms_use_pyscript"
LEARNED_BRIGHTNESS = "sensor.learned_brightness_bedroom"
INTELLIGENT_BRIGHTNESS = "sensor.intelligent_brightness_bedroom"
PYSCRIPT_BRIGHTNESS = "pyscript.test_bedroom_brightness"
ADAPTIVE_OVERRIDE = "input_boolean.bedroom_adaptive_override"
OVERRIDE_BRIGHTNESS = "input_number.bedroom_override_brightness"

# Evening mode entities
EVENING_MODE_ACTIVE = "input_boolean.evening_mode_active"

# Brightness caching to prevent changes during same motion event
cached_brightness = None
cached_temperature = None
motion_start_time = None

# ===========================

# --- Helpers ---
def _state(eid, d=None):
    try:
        v = state.get(eid)
        return v if v not in (None, "unknown", "unavailable") else d
    except Exception:
        return d

def _attr(eid, attr, d=None):
    try:
        attrs = state.getattr(eid)
        return attrs.get(attr, d) if attrs else d
    except Exception:
        return d

def _to_int(v, d=0):
    try:
        return int(float(v))
    except:
        return d

def _info(msg): log.info(f"[ClosetALS] {msg}")
def _warn(msg): log.warning(f"[ClosetALS] {msg}")
def _error(msg): log.error(f"[ClosetALS] {msg}")

# --- Brightness Calculation ---
def calculate_closet_brightness():
    """Calculate closet target brightness with proper priority order"""
    
    home_mode = _state(HOME_STATE, "unknown")
    
    # Morning Ramp has highest priority
    if _state(RAMP_ACTIVE) == "on":
        ramp_bri = _state(RAMP_BRIGHTNESS)
        if ramp_bri not in ["unavailable", "unknown", None]:
            _info(f"Brightness source: Morning Ramp ({ramp_bri}%)")
            return max(1, min(100, _to_int(ramp_bri)))
    
    # Manual Override
    if _state(ADAPTIVE_OVERRIDE) == "on":
        override_bri = _state(OVERRIDE_BRIGHTNESS)
        if override_bri not in ["unavailable", "unknown", None]:
            _info(f"Brightness source: Manual Override ({override_bri}%)")
            return max(1, min(100, _to_int(override_bri, 100)))
    
    # Night Mode Lock
    if home_mode == "Night":
        _info(f"Brightness source: Night Mode Lock ({FALLBACK_NIGHT_BRIGHTNESS}%)")
        return FALLBACK_NIGHT_BRIGHTNESS
    
    # PyScript Engine (includes temperature)
    if _state(ALL_ROOMS_USE_PYSCRIPT) == "on":
        pyscript_bri = _state(PYSCRIPT_BRIGHTNESS)
        if pyscript_bri not in ["unavailable", "unknown", None]:
            _info(f"Brightness source: PyScript Engine ({pyscript_bri}%)")
            return max(1, min(100, _to_int(pyscript_bri)))
    
    # Adaptive Learning
    if _state(ADAPTIVE_LEARNING_ENABLED) == "on":
        learned = _state(LEARNED_BRIGHTNESS)
        using_learned = _attr(LEARNED_BRIGHTNESS, "using_learned", False)
        if learned not in ["unavailable", "unknown", None] and using_learned:
            _info(f"Brightness source: Adaptive Learning ({learned}%)")
            return max(1, min(100, _to_int(learned)))
    
    # Intelligent System
    if _state(INTELLIGENT_LIGHTING_ENABLED) == "on":
        intelligent_bri = _state(INTELLIGENT_BRIGHTNESS)
        if intelligent_bri not in ["unavailable", "unknown", None]:
            _info(f"Brightness source: Intelligent System ({intelligent_bri}%)")
            return max(1, min(100, _to_int(intelligent_bri)))
    
    # Fallback Values by Mode
    if home_mode in ["Evening", "Early Morning"]:
        _info(f"Brightness source: Fallback Evening ({FALLBACK_EVENING_BRIGHTNESS}%)")
        return FALLBACK_EVENING_BRIGHTNESS
    elif home_mode == "Day":
        _info(f"Brightness source: Fallback Day ({FALLBACK_DAY_BRIGHTNESS}%)")
        return FALLBACK_DAY_BRIGHTNESS
    else:
        _info(f"Brightness source: Default Fallback (40%)")
        return 40

def calculate_color_temperature():
    """Calculate color temperature based on mode and context"""
    
    home_mode = _state(HOME_STATE, "unknown")
    
    # Morning Ramp - warm to neutral transition
    if _state(RAMP_ACTIVE) == "on":
        # Start at 2000K, gradually increase to 4000K (like your work ramp spec)
        ramp_progress = _attr("sensor.sleep_in_ramp_progress", "state", 0)
        progress_pct = _to_int(ramp_progress, 0) / 100.0
        # Linear interpolation from 2000K to 4000K
        temp = int(2000 + (2000 * progress_pct))
        _info(f"Temperature source: Morning Ramp ({temp}K at {int(progress_pct*100)}%)")
        return temp
    
    # Evening Mode - always 2000K (warm) for closet during evening
    if _state(EVENING_MODE_ACTIVE) == "on" or home_mode == "Evening":
        _info(f"Temperature source: Evening Mode (2000K)")
        return 2000
    
    # PyScript Engine temperature
    if _state(ALL_ROOMS_USE_PYSCRIPT) == "on":
        pyscript_temp = _attr(PYSCRIPT_BRIGHTNESS, "temperature")
        if pyscript_temp:
            _info(f"Temperature source: PyScript Engine ({pyscript_temp}K)")
            return _to_int(pyscript_temp, 3000)
    
    # Mode-based defaults
    if home_mode == "Night":
        return 2000  # Very warm for night
    elif home_mode == "Early Morning":
        return 2500  # Warm for early morning
    elif home_mode == "Day":
        return 4000  # Neutral white for day
    else:
        return 3000  # Default warm-neutral

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

def _light_on(brightness_pct: int, temperature: int = None):
    try:
        data = {"brightness_pct": brightness_pct}
        if temperature:
            data["color_temp_kelvin"] = temperature
        
        service.call("light", "turn_on", entity_id=CLOSET_LIGHT, **data)
        _info(f"Light ON -> {CLOSET_LIGHT} at {brightness_pct}%" + (f" @ {temperature}K" if temperature else ""))
    except Exception as e:
        _error(f"Light on error: {e}")

def _light_off():
    try:
        service.call("light", "turn_off", entity_id=CLOSET_LIGHT, transition=2)
        _info(f"Light OFF -> {CLOSET_LIGHT}")
    except Exception as e:
        _error(f"Light off error: {e}")

# --- Core Behavior ---
def _apply_for_motion(active: bool, reason: str):
    global cached_brightness, cached_temperature
    
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
        # Use cached values if available, otherwise calculate fresh
        if cached_brightness is not None and cached_temperature is not None:
            br = cached_brightness
            temp = cached_temperature
            _info(f"Using cached: {br}% @ {temp}K")
        else:
            br = calculate_closet_brightness()
            temp = calculate_color_temperature()
            _info(f"Using fresh: {br}% @ {temp}K")
        
        # Check if light is already on at correct settings
        current_state = _state(CLOSET_LIGHT)
        if current_state == "on":
            try:
                attrs = state.getattr(CLOSET_LIGHT)
                current_br_raw = attrs.get("brightness", 0)
                current_br_pct = int((current_br_raw / 255) * 100) if current_br_raw else 0
                current_temp = attrs.get("color_temp_kelvin", 0)
                
                # Check both brightness and temperature
                if abs(current_br_pct - br) < 3 and abs(current_temp - temp) < 100:
                    _info(f"Light already at {current_br_pct}%/{current_temp}K, target {br}%/{temp}K - skipping")
                    return
            except:
                pass  # If we can't check, just send the command
        
        _light_on(br, temp)
    else:
        # Turn OFF closet light
        _light_off()

# --- Motion Listener ---
@state_trigger(BEDROOM_MOTION)
async def closet_motion_listener(**kwargs):
    global cached_brightness, cached_temperature, motion_start_time
    
    eid = kwargs.get("var_name")
    new = _state(eid)
    current_time = datetime.now()
    
    _info(f"Listener: {eid} -> {new} @ {current_time.strftime('%H:%M:%S')}")
    
    if new == "on":
        # NEW MOTION: Calculate and cache brightness/temperature
        cached_brightness = calculate_closet_brightness()
        cached_temperature = calculate_color_temperature()
        motion_start_time = current_time
        _info(f"Cached: {cached_brightness}% @ {cached_temperature}K for new motion event")
        
        # Trigger morning ramp if appropriate
        _trigger_morning_ramp(eid)
        _apply_for_motion(True, reason=f"{eid} active")
        publish_closet_sensors()
    else:
        # Motion cleared - start debounce but DON'T reset cache yet
        original_br = cached_brightness
        original_temp = cached_temperature
        original_time = motion_start_time
        await asyncio.sleep(MOTION_TIMEOUT_SECONDS)
        
        # Check if motion is still clear after debounce
        if _state(BEDROOM_MOTION) == "off":
            # Only clear cache after successful debounce
            cached_brightness = None
            cached_temperature = None
            motion_start_time = None
            _apply_for_motion(False, reason="debounced clear")
            publish_closet_sensors()
        else:
            # Motion returned during debounce - restore cache
            cached_brightness = original_br
            cached_temperature = original_temp
            motion_start_time = original_time
            _info("Clear aborted (motion returned) - cache restored")

# --- Mode Change Handlers ---
@state_trigger("input_select.home_state == 'Away'")
def closet_away_mode():
    """Turn off closet light when entering Away mode"""
    _info("CLOSET CONTROL: Turning off light for Away mode")
    _light_off()
    publish_closet_sensors()

@state_trigger("input_select.home_state == 'Night'")
def closet_night_mode():
    """Adjust closet light if it's on when entering Night mode"""
    if _state(CLOSET_LIGHT) == "on":
        # Adjust to night brightness/temperature
        br = calculate_closet_brightness()
        temp = calculate_color_temperature()
        _light_on(br, temp)
        _info(f"Night mode: adjusted to {br}% @ {temp}K")

# --- Sensor Publishers ---
def publish_closet_sensors():
    """Publish closet/bedroom sensors"""
    try:
        # Use cached values during motion, fresh otherwise
        if cached_brightness is not None and cached_temperature is not None:
            brightness = cached_brightness
            temperature = cached_temperature
            source = "CACHED"
        else:
            brightness = calculate_closet_brightness()
            temperature = calculate_color_temperature()
            source = get_calculation_source()
        
        # Target Brightness Sensor
        state.set("sensor.bedroom_target_brightness", brightness, {
            "friendly_name": "Bedroom Target Brightness",
            "unit_of_measurement": "%",
            "calculation_source": source,
            "temperature": temperature
        })
        
        # Status Sensor
        motion = _state(BEDROOM_MOTION) == "on"
        home_mode = _state(HOME_STATE, "unknown")
        error = _state("input_text.als_error_bedroom")
        
        if error not in ["", "unknown", "unavailable", None]:
            status = "🚫 Error Present"
            icon = "mdi:alert-circle"
        elif home_mode == "Away":
            status = "🚪 Away Mode"
            icon = "mdi:home-export-outline"
        elif motion:
            status = f"💡 Motion Active ({brightness}% @ {temperature}K)"
            icon = "mdi:lightbulb-on"
        else:
            status = f"🛏️ Ready ({source})"
            icon = "mdi:bed"
        
        state.set("sensor.bedroom_als_status", status, {
            "friendly_name": "Bedroom ALS Status",
            "icon": icon
        })
    
    except Exception as e:
        _error(f"Failed to publish sensors: {e}")

def get_calculation_source():
    """Get current calculation source"""
    if _state(RAMP_ACTIVE) == "on":
        return "Morning Ramp"
    elif _state(ADAPTIVE_OVERRIDE) == "on":
        return "Manual Override"
    elif _state(HOME_STATE) == "Night":
        return "Night Mode Lock"
    elif _state(ALL_ROOMS_USE_PYSCRIPT) == "on":
        return "PyScript Engine"
    elif (_state(ADAPTIVE_LEARNING_ENABLED) == "on" and 
          _attr(LEARNED_BRIGHTNESS, "using_learned", False)):
        return "Adaptive Learning"
    elif _state(INTELLIGENT_LIGHTING_ENABLED) == "on":
        return "Intelligent System"
    else:
        return "Fallback Values"

# --- Manual Services ---
@service("pyscript.closet_smoke_test")
def closet_smoke_test():
    """Test closet light control"""
    _info("SMOKE TEST: Closet light ON at 50% @ 3000K, then OFF")
    _light_on(50, 3000)
    import time
    time.sleep(2)
    _light_off()
    publish_closet_sensors()

@service("pyscript.closet_force")
def closet_force(mode: str = "on"):
    """Force closet light on/off"""
    if mode == "on":
        br = calculate_closet_brightness()
        temp = calculate_color_temperature()
        _light_on(br, temp)
    else:
        _light_off()
    publish_closet_sensors()

@service("pyscript.closet_debug_status")
def closet_debug_status():
    """Debug current state of closet/bedroom"""
    _info("=== CLOSET DEBUG STATUS ===")
    _info(f"Home State: {_state(HOME_STATE)}")
    _info(f"Motion: {_state(BEDROOM_MOTION)}")
    _info(f"Light: {_state(CLOSET_LIGHT)}")
    _info(f"Cached Brightness: {cached_brightness}")
    _info(f"Cached Temperature: {cached_temperature}")
    _info(f"Current Brightness: {calculate_closet_brightness()}%")
    _info(f"Current Temperature: {calculate_color_temperature()}K")
    _info(f"Source: {get_calculation_source()}")
    _info("=== END DEBUG ===")

# --- Startup and Regular Updates ---
@time_trigger("startup")
def closet_startup():
    """Initialize closet system on startup"""
    _info("Closet system starting up")
    publish_closet_sensors()

@time_trigger("cron(* * * * *)")
def closet_minute_update():
    """Update sensors every minute"""
    publish_closet_sensors()