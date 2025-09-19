# /config/pyscript/hallway_motion.py (Created 2025-09-14)
# COMPLETE PyScript hallway controller - SINGLE FILE ONLY
# Handles motion detection, brightness calculations, mode transitions
# INCLUDES: All input helper definitions - no separate YAML needed

from datetime import datetime, time as dt_time
import time
import asyncio

# ===== Entities =====
HALLWAY_LIGHT    = "light.hallway"
HALLWAY_MOTION   = "binary_sensor.hallway_iris_occupancy"
HOME_STATE       = "input_select.home_state"
ALLOWED_MODES    = {"Day", "Evening", "Night", "Early Morning"}  # All modes except Away

# ===== Hardcoded Configuration Values =====
# Since we want one file only, these values are hardcoded instead of input entities
MOTION_TIMEOUT_SECONDS = 30
FALLBACK_DAY_BRIGHTNESS = 20      # 20% for daytime
FALLBACK_EVENING_BRIGHTNESS = 15 # 15% for evening
FALLBACK_NIGHT_BRIGHTNESS = 1    # 1% for night
OVERRIDE_BRIGHTNESS = 100        # 100% for manual override

# System entities for brightness calculations
RAMP_ACTIVE              = "input_boolean.sleep_in_ramp_active"
ADAPTIVE_LEARNING_ENABLED = "input_boolean.adaptive_learning_enabled"
INTELLIGENT_LIGHTING_ENABLED = "input_boolean.intelligent_lighting_enable"
ALL_ROOMS_USE_PYSCRIPT   = "input_boolean.all_rooms_use_pyscript"

# Brightness sources
RAMP_BRIGHTNESS          = "sensor.sleep_in_ramp_brightness"
LEARNED_BRIGHTNESS_HALLWAY = "sensor.learned_brightness_hallway"
INTELLIGENT_BRIGHTNESS_HALLWAY = "sensor.intelligent_brightness_hallway"
PYSCRIPT_HALLWAY_BRIGHTNESS = "pyscript.test_hallway_brightness"

# ===== Configuration =====
CLEAR_DEBOUNCE_SEC = 5
TEST_BYPASS_MODE   = False

# Override state (replaces input_boolean)
ADAPTIVE_OVERRIDE = False

# Brightness caching to prevent changes during same motion event
cached_brightness = None
motion_start_time = None

# ===========================

# --- Brightness Calculation (replaces complex YAML template) ---
def calculate_hallway_brightness():
    """Calculate hallway target brightness with proper priority order"""

    # Morning Ramp has highest priority
    if _state(RAMP_ACTIVE) == "on":
        ramp_bri = _state(RAMP_BRIGHTNESS)
        if ramp_bri not in ["unavailable", "unknown", None]:
            _info(f"Brightness source: Morning Ramp ({ramp_bri}%)")
            return max(1, min(100, int(float(ramp_bri))))

    # Manual Override
    if ADAPTIVE_OVERRIDE:
        _info(f"Brightness source: Manual Override ({OVERRIDE_BRIGHTNESS}%)")
        return OVERRIDE_BRIGHTNESS

    # Night Mode Lock
    if _state(HOME_STATE) == "Night":
        _info(f"Brightness source: Night Mode Lock ({FALLBACK_NIGHT_BRIGHTNESS}%)")
        return FALLBACK_NIGHT_BRIGHTNESS

    # Adaptive Learning
    if _state(ADAPTIVE_LEARNING_ENABLED) == "on":
        learned = _state(LEARNED_BRIGHTNESS_HALLWAY)
        try:
            learned_attrs = state.getattr(LEARNED_BRIGHTNESS_HALLWAY)
            using_learned = learned_attrs.get("using_learned", False) if learned_attrs else False
        except Exception:
            using_learned = False
        if learned not in ["unavailable", "unknown", None] and using_learned:
            _info(f"Brightness source: Adaptive Learning ({learned}%)")
            return max(1, min(100, int(float(learned))))

    # PyScript Engine
    if _state(ALL_ROOMS_USE_PYSCRIPT) == "on":
        pyscript_bri = _state(PYSCRIPT_HALLWAY_BRIGHTNESS)
        if pyscript_bri not in ["unavailable", "unknown", None]:
            _info(f"Brightness source: PyScript Engine ({pyscript_bri}%)")
            return max(1, min(100, int(float(pyscript_bri))))

    # Intelligent System
    if _state(INTELLIGENT_LIGHTING_ENABLED) == "on":
        intelligent_bri = _state(INTELLIGENT_BRIGHTNESS_HALLWAY)
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
        _info(f"Brightness source: Default Fallback (15%)")
        return 15

# --- helpers ---
def _state(eid, d=None):
    try:
        v = state.get(eid)
        return v if v not in (None, "unknown", "unavailable") else d
    except Exception:
        return d

def _info(msg):  log.info(f"[HallwayALS] {msg}")
def _warn(msg):  log.error(f"[HallwayALS] {msg}")  # Changed to error so it definitely shows
def _error(msg): log.error(f"[HallwayALS] {msg}")

# --- Sensor Publishers ---
def publish_hallway_sensors():
    """Publish hallway sensors (replaces YAML template sensors)"""
    try:
        # Target Brightness Sensor - use cached brightness during motion to prevent changes
        if cached_brightness is not None:
            brightness = cached_brightness
            source = "CACHED"
        else:
            brightness = calculate_hallway_brightness()
            source = get_calculation_source()

        state.set("sensor.hallway_target_brightness", brightness, {
            "friendly_name": "Hallway Target Brightness",
            "unit_of_measurement": "%",
            "calculation_source": source,
            "confirmations": 0  # Disabled due to state.getattr issues
        })

        # Status Sensor
        enabled = True  # Always enabled in PyScript version
        motion = _state(HALLWAY_MOTION) == "on"
        home_mode = _state(HOME_STATE, "unknown")
        error = _state("input_text.als_error_hallway")

        if error not in ["", "unknown", "unavailable", None]:
            status = "🚫 Error Present"
        elif not enabled:
            status = "⏸️ System Disabled"
        elif home_mode == "Away":
            status = "🚪 Away Mode"
        elif motion:
            status = f"💡 Motion Active ({brightness}%)"
        else:
            status = f"🚪 Ready ({get_calculation_source()})"

        # Set icon based on status
        icon = "mdi:door"
        if "🚫" in status:
            icon = "mdi:alert-circle"
        elif "⏸️" in status:
            icon = "mdi:pause-circle"
        elif "🚪" in status:
            icon = "mdi:home-export-outline"
        elif "💡" in status:
            icon = "mdi:lightbulb-on"

        state.set("sensor.hallway_als_status", status, {
            "friendly_name": "Hallway ALS Status",
            "icon": icon
        })

    except Exception as e:
        _error(f"Failed to publish sensors: {e}")

def get_calculation_source():
    """Get current calculation source for attributes"""
    if _state(RAMP_ACTIVE) == "on":
        return "Morning Ramp"
    elif ADAPTIVE_OVERRIDE:
        return "Manual Override"
    elif _state(HOME_STATE) == "Night":
        return "Night Mode Lock"
    elif _state(ADAPTIVE_LEARNING_ENABLED) == "on":
        try:
            learned_attrs = state.getattr(LEARNED_BRIGHTNESS_HALLWAY)
            learned = learned_attrs.get("using_learned", False) if learned_attrs else False
        except Exception:
            learned = False
        if learned:
            return "Adaptive Learning"
    elif _state(ALL_ROOMS_USE_PYSCRIPT) == "on":
        return "PyScript Engine"
    elif _state(INTELLIGENT_LIGHTING_ENABLED) == "on":
        return "Intelligent System"
    else:
        return "Fallback Values"

def _trigger_morning_ramp(sensor_name: str):
    """Trigger morning ramp service when motion detected in Night mode during morning hours only"""
    try:
        hs = _state(HOME_STATE)
        ramp_enabled = _state("input_boolean.sleep_in_ramp_system_enable", "on") in ["on", "unknown", "unavailable", ""]

        # TIME CHECK: Only trigger morning ramp during appropriate morning hours
        now_time = datetime.now().time()
        morning_start = dt_time(4, 0, 0)   # 4:00 AM - earliest morning ramp
        morning_end = dt_time(10, 0, 0)    # 10:00 AM - latest morning ramp

        is_morning_hours = morning_start <= now_time <= morning_end

        if hs == "Night" and ramp_enabled and is_morning_hours:
            _warn(f"🔥 MORNING RAMP: Calling pyscript.morning_ramp_first_motion from {sensor_name} at {now_time.strftime('%H:%M')}")
            try:
                service.call("pyscript", "morning_ramp_first_motion", sensor=sensor_name)
                _info(f"✅ Morning ramp service call successful")
            except Exception as service_error:
                _error(f"❌ Service call failed: {service_error}")
                # Try alternative service name
                try:
                    service.call("pyscript", "morning_ramp_first_motion", sensor=sensor_name)
                    _info(f"✅ Alternative service call successful")
                except:
                    _error(f"❌ All service attempts failed")
        else:
            reasons = []
            if hs != "Night":
                reasons.append(f"mode={hs}")
            if not ramp_enabled:
                reasons.append("ramp_disabled")
            if not is_morning_hours:
                reasons.append(f"time={now_time.strftime('%H:%M')} (not morning hours)")
            _info(f"Morning ramp not triggered: {', '.join(reasons)}")
    except Exception as e:
        _error(f"Failed to trigger morning ramp: {e}")

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

# --- core behavior ---
def _apply_for_motion(active: bool, reason: str):
    global cached_brightness

    hs = _state(HOME_STATE, "unknown")

    # Simple: Don't turn on lights in Away mode
    if hs == "Away":
        return

    if active:
        # Use cached brightness if available, otherwise calculate fresh
        if cached_brightness is not None:
            br = cached_brightness
            _info(f"Using cached brightness: {br}%")
        else:
            br = calculate_hallway_brightness()
            _info(f"Using fresh brightness: {br}%")

        # CHECK IF ALREADY ON AT CORRECT BRIGHTNESS
        current_state = _state(HALLWAY_LIGHT)
        if current_state == "on":
            # Get current brightness (0-255 scale)
            try:
                current_br_raw = state.getattr(HALLWAY_LIGHT).get("brightness", 0)
                current_br_pct = int((current_br_raw / 255) * 100) if current_br_raw else 0

                if abs(current_br_pct - br) < 3:  # Within 3%, don't send command
                    _info(f"Light already at {current_br_pct}%, target {br}% - skipping command")
                    return
            except:
                pass  # If we can't check, just send the command

        _light_on(HALLWAY_LIGHT, brightness_pct=br)
        _info(f"Hallway light ON at {br}%")
    else:
        # Turn OFF hallway light
        _light_off(HALLWAY_LIGHT)
        _info(f"Hallway light OFF (motion clear)")

# --- listeners (no YAML automation needed) ---
@state_trigger(HALLWAY_MOTION)
async def hallway_motion_listener(**kwargs):
    global cached_brightness, motion_start_time

    eid = kwargs.get("var_name")
    new = _state(eid)
    current_time = datetime.now()

    _info(f"Listener: {eid} -> {new} @ {current_time.strftime('%H:%M:%S')}")

    if new == "on":
        # NEW MOTION: Calculate and cache brightness
        cached_brightness = calculate_hallway_brightness()
        motion_start_time = current_time
        _info(f"Cached brightness: {cached_brightness}% for new motion event")

        # Trigger morning ramp system when motion detected
        _trigger_morning_ramp(eid)
        _apply_for_motion(True, reason=f"{eid} active")
        publish_hallway_sensors()  # Only update when motion detected
    else:
        # Motion cleared - start debounce but DON'T reset cache yet
        original_cache = cached_brightness
        original_start_time = motion_start_time
        await asyncio.sleep(MOTION_TIMEOUT_SECONDS)

        # Check if motion is still clear after debounce
        if _state(HALLWAY_MOTION) == "off":
            # Only clear cache after successful debounce
            cached_brightness = None
            motion_start_time = None
            _apply_for_motion(False, reason="debounced clear")
            publish_hallway_sensors()  # Update when motion actually clears
        else:
            # Motion returned during debounce - restore original cache
            cached_brightness = original_cache
            motion_start_time = original_start_time
            _info("Clear aborted (motion returned during debounce) - brightness cache restored")
            # No sensor update needed - motion is still active

# --- mode-based hallway control ---
@state_trigger("input_select.home_state == 'Away'")
def hallway_mode_turn_off():
    """Turn off hallway lights when entering Away mode"""
    hs = _state(HOME_STATE, "unknown")
    _info(f"HALLWAY CONTROL: Turning off hallway lights for {hs} mode")
    _light_off(HALLWAY_LIGHT)
    publish_hallway_sensors()


# --- Manual Services ---
@service("pyscript.hallway_smoke_test")
def hallway_smoke_test():
    """Test hallway light control"""
    _info("SMOKE: Hallway light ON at 50%, then OFF")
    _light_on(HALLWAY_LIGHT, brightness_pct=50)
    time.sleep(2)
    _light_off(HALLWAY_LIGHT)
    publish_hallway_sensors()

@service("pyscript.hallway_force")
def hallway_force(mode: str = "on"):
    """Force hallway light on/off"""
    if mode == "on":
        br = calculate_hallway_brightness()
        _light_on(HALLWAY_LIGHT, brightness_pct=br)
    else:
        _light_off(HALLWAY_LIGHT)
    publish_hallway_sensors()

@service("pyscript.hallway_override_on")
def hallway_override_on():
    """Enable manual override"""
    global ADAPTIVE_OVERRIDE
    ADAPTIVE_OVERRIDE = True
    _info("Hallway override ENABLED")
    publish_hallway_sensors()

@service("pyscript.hallway_override_off")
def hallway_override_off():
    """Disable manual override"""
    global ADAPTIVE_OVERRIDE
    ADAPTIVE_OVERRIDE = False
    _info("Hallway override DISABLED")
    publish_hallway_sensors()

# --- Startup and Regular Updates ---
@time_trigger("startup")
def hallway_startup():
    """Initialize hallway system on startup"""
    _info("Hallway system starting up")
    publish_hallway_sensors()

@time_trigger("cron(* * * * *)")
def hallway_minute_update():
    """Update sensors every minute"""
    publish_hallway_sensors()