# /config/pyscript/parallel_test_engine.py
# VERSION 2.0 - CONSOLIDATED LOGIC ENGINE
# Core "brain" for ALS. Learns brightness & temperature, writes per-room targets.

import sqlite3
import statistics
import datetime
# NOTE: do NOT import task_unique from pyscript; the decorator is available globally.

# --- Database Connection (SQLITE VERSION) ---
def _get_db_connection():
    """Connect to Home Assistant's SQLite database."""
    try:
        return sqlite3.connect("/config/home-assistant_v2.db", timeout=10.0)
    except Exception as e:
        log.error(f"Failed to connect to SQLite database: {e}")
        return None

# ---------- System & Room Configuration ----------
CFG = {
    "hallway": {
        "final_entity": "sensor.hallway_target_brightness",
        "override_toggle": "input_boolean.hallway_adaptive_override",
        "override_bri": "input_number.hallway_override_brightness",
        "fb_night": "input_number.hallway_fallback_night_brightness",
        "fb_evening": "input_number.hallway_fallback_evening_brightness",
        "fb_day": "input_number.hallway_fallback_day_brightness",
        "use_avg_toggle": "input_boolean.use_average_hallway",
        "defaults": {"override_bri": 100, "fb_night": 1, "fb_evening": 15, "fb_day": 20},
    },
    "laundry": {
        "final_entity": "sensor.laundry_room_target_brightness",
        "override_toggle": "input_boolean.laundry_adaptive_override",
        "override_bri": "input_number.laundry_override_brightness",
        "fb_night": "input_number.laundry_fallback_night_brightness",
        "fb_evening": "input_number.laundry_fallback_evening_brightness",
        "fb_day": "input_number.laundry_fallback_day_brightness",
        "use_avg_toggle": "input_boolean.use_average_laundry",
        "defaults": {"override_bri": 80, "fb_night": 1, "fb_evening": 60, "fb_day": 80},
    },
    "kitchen": {
        "final_entity": "sensor.kitchen_target_brightness",
        "override_toggle": "input_boolean.kitchen_adaptive_override",
        "override_bri": "input_number.kitchen_override_brightness",
        "fb_night": "input_number.kitchen_fallback_night_brightness",
        "fb_evening": "input_number.kitchen_fallback_evening_brightness",
        "fb_day": "input_number.kitchen_fallback_day_brightness",
        "use_avg_toggle": "input_boolean.use_average_kitchen",
        "defaults": {"override_bri": 80, "fb_night": 1, "fb_evening": 30, "fb_day": 30},
    },
    "living_room": {
        "final_entity": "sensor.living_room_target_brightness",
        "override_toggle": "input_boolean.living_room_adaptive_override",
        "override_bri": "input_number.living_room_override_brightness",
        "fb_night": "input_number.livingroom_fallback_night_brightness",
        "fb_evening": "input_number.livingroom_fallback_evening_brightness",
        "fb_day": "input_number.livingroom_fallback_day_brightness",
        "use_avg_toggle": "input_boolean.use_average_living_room",
        "defaults": {"override_bri": 50, "fb_night": 1, "fb_evening": 40, "fb_day": 0},
    },
    "bathroom": {
        "final_entity": "sensor.bathroom_target_brightness",
        "override_toggle": "input_boolean.bathroom_adaptive_override",
        "override_bri": "input_number.bathroom_override_brightness",
        "fb_night": "input_number.bathroom_fallback_night_brightness",
        "fb_evening": "input_number.bathroom_fallback_evening_brightness",
        "fb_day": "input_number.bathroom_fallback_day_brightness",
        "use_avg_toggle": "input_boolean.use_average_bathroom",
        "defaults": {"override_bri": 70, "fb_night": 1, "fb_evening": 50, "fb_day": 70},
    },
    "bedroom": {
        "final_entity": "sensor.bedroom_target_brightness",
        "override_toggle": "input_boolean.bedroom_adaptive_override",
        "override_bri": "input_number.bedroom_override_brightness",
        "fb_night": "input_number.bedroom_fallback_night_brightness",
        "fb_evening": "input_number.bedroom_fallback_evening_brightness",
        "fb_day": "input_number.bedroom_fallback_day_brightness",
        "use_avg_toggle": "input_boolean.use_average_bedroom",
        "defaults": {"override_bri": 30, "fb_night": 1, "fb_evening": 20, "fb_day": 30},
    },
}

# ---------- Utils ----------
def _norm(v, d=None): return d if v in (None, "", "unknown", "unavailable") else v
def _to_int(v, d=0):
    try: return int(float(v))
    except Exception: return d
def _state(eid, d=None):
    try: return _norm(state.get(str(eid)), d)
    except Exception: return d
def _attr(eid, attr, d=None):
    try: return _norm((state.getattr(str(eid)) or {}).get(attr), d)
    except Exception: return d
def _num(room, key):
    rcfg = CFG.get(room, {})
    eid = rcfg.get(key)
    default_val = rcfg.get("defaults", {}).get(key, 0)
    return _to_int(_state(eid, default_val), default_val)

# ---------- Consolidated Logic Functions ----------
def _calculate_intelligent_brightness():
    """Calculates the master intelligent brightness."""
    if _state("input_boolean.sleep_in_ramp_active") == 'on':
        return _to_int(_state('sensor.sleep_in_ramp_brightness'), 50)

    home_mode = _state("input_select.home_state", "Day")

    if home_mode == 'Night':
        return _to_int(_state('input_number.night_max_brightness'), 1)

    if home_mode == 'Day':
        cloud_coverage = _attr('weather.pirateweather', 'cloud_coverage', 0)
        base = _to_int(_state('input_number.als_day_base_brightness'), 30)
        max_bright = _to_int(_state('input_number.als_day_max_brightness'), 80)
        cloud_boost_pct = _to_int(_state('input_number.als_cloudy_boost'), 15)
        winter_boost = _to_int(_state('input_number.als_winter_boost'), 10)
        fall_boost = _to_int(_state('input_number.als_fall_boost'), 5)

        cloud_boost = (cloud_coverage / 100) * cloud_boost_pct
        season = _state('sensor.current_season', 'Summer')
        season_adj = winter_boost if season == 'Winter' else (fall_boost if season == 'Fall' else 0)

        final = base + cloud_boost + season_adj
        return round(min(final, max_bright))

    # Evening / Early Morning or unknown: sensible default
    return 50

def _calculate_intelligent_temperature():
    """Calculates the master intelligent temperature."""
    if _state("input_boolean.sleep_in_ramp_active") == 'on':
        return _to_int(_state('sensor.sleep_in_ramp_temperature'), 3000)

    home_mode = _state("input_select.home_state", "Day")

    if home_mode == 'Night':
        return _to_int(_state('input_number.night_temp'), 1800)

    if home_mode == 'Day':
        season = _state('sensor.current_season', 'Summer')
        if season == 'Winter': return 3800
        if season == 'Summer': return 4200
        return 4000

    if home_mode == 'Evening':
        return 2700

    return 3500  # default fallback

# ---------- Learned Brightness & Temperature (from DB) ----------
def _get_learned_settings(room, fallback_bri, fallback_temp):
    """Gets learned brightness AND temperature from the database."""
    home = _state("input_select.home_state", "Day")
    sun_el = _attr("sun.sun", "elevation", 0.0)
    clouds = _attr("weather.pirateweather", "cloud_coverage", 0)
    season = _state("sensor.current_season", "Summer")

    sun_bucket = "High_Sun"
    try:
        se = float(sun_el or 0)
        if se < 0: sun_bucket = "Below_Horizon"
        elif se < 15: sun_bucket = "Low_Sun"
        elif se < 40: sun_bucket = "Mid_Sun"
    except Exception:
        pass

    try:
        cloud_bucket = int(_to_int(clouds, 0) // 20 * 20)
    except Exception:
        cloud_bucket = 0

    key = f"{home}_{sun_bucket}_{cloud_bucket}_{season}"
    threshold = _to_int(_state("input_number.confirmation_threshold", 4), 4)

    confirmations = 0  # always defined

    db_conn = _get_db_connection()
    if not db_conn:
        return {
            "brightness": fallback_bri,
            "temperature": fallback_temp,
            "using_learned": False,
            "confirmations": confirmations,
        }

    try:
        cursor = db_conn.cursor()
        sql = "SELECT brightness_percent, temperature_kelvin FROM adaptive_learning WHERE room = ? AND condition_key = ?"
        cursor.execute(sql, (room, key))
        results = cursor.fetchall()
        confirmations = len(results)

        if confirmations >= threshold:
            bri_vals = [row[0] for row in results]
            temp_vals = [row[1] for row in results if row[1] is not None]

            use_avg = _state(CFG[room]["use_avg_toggle"], "off") == "on"
            final_bri = statistics.mean(bri_vals) if use_avg else statistics.median(bri_vals)

            final_temp = fallback_temp
            if len(temp_vals) >= threshold:
                final_temp = statistics.median(temp_vals)

            return {
                "brightness": _to_int(final_bri),
                "temperature": _to_int(final_temp),
                "using_learned": True,
                "confirmations": confirmations,
            }

    except Exception as e:
        log.error(f"_get_learned_settings_db: Database error: {e}")
    finally:
        try: db_conn.close()
        except Exception: pass

    return {
        "brightness": fallback_bri,
        "temperature": fallback_temp,
        "using_learned": False,
        "confirmations": confirmations,
    }

# ---------- Core Decision Logic ----------
def _calculate_final_settings(room):
    """Calculates the final brightness AND temperature based on the priority hierarchy."""
    home = _state("input_select.home_state", "Day")

    # Manual override wins
    if _state(CFG[room]["override_toggle"], "off") == "on":
        return {"brightness": _num(room, "override_bri"), "temperature": 3500, "reason": "override"}

    # Morning ramp in progress
    if _state("input_boolean.sleep_in_ramp_active", "off") == "on":
        ramp_bri = _to_int(_state("sensor.sleep_in_ramp_brightness"), 50)
        ramp_temp = _to_int(_state("sensor.sleep_in_ramp_temperature"), 3000)
        return {"brightness": ramp_bri, "temperature": ramp_temp, "reason": "ramp_progression"}

    # Night fallback
    if home == "Night":
        return {"brightness": _num(room, "fb_night"), "temperature": 1800, "reason": "night"}

    # Intelligent baseline
    master_bri = _calculate_intelligent_brightness()
    master_temp = _calculate_intelligent_temperature()

    # Room-specific intelligent fallbacks (brightness only)
    intel_bri = _to_int(_state(f"sensor.intelligent_brightness_{room}"), master_bri)
    intel_temp = master_temp

    # Learned (DB) override if enabled & sufficient samples
    learned = _get_learned_settings(room, intel_bri, intel_temp)

    if _state("input_boolean.adaptive_learning_enabled", "off") == "on" and learned["using_learned"]:
        return {"brightness": learned["brightness"], "temperature": learned["temperature"], "reason": "adaptive_learned"}

    if _state("input_boolean.intelligent_lighting_enable", "off") == "on":
        return {"brightness": intel_bri, "temperature": intel_temp, "reason": "intelligent_pyscript"}

    # Fallbacks by mode
    if home in ("Evening", "Early Morning"):
        return {"brightness": _num(room, "fb_evening"), "temperature": 2700, "reason": "fallback_evening"}
    if home == "Day":
        return {"brightness": _num(room, "fb_day"), "temperature": 4000, "reason": "fallback_day"}

    return {"brightness": _num(room, "fb_evening"), "temperature": 2700, "reason": "fallback_default"}

# ---------- State Writer ----------
@time_trigger("startup")
@state_trigger(
    "input_select.home_state", "weather.pirateweather", "input_boolean.sleep_in_ramp_active",
    # room-specific intelligent fallbacks (keep as-is)
    "sensor.intelligent_brightness_hallway",
    "input_boolean.hallway_adaptive_override", "input_boolean.laundry_adaptive_override",
    "input_boolean.kitchen_adaptive_override", "input_boolean.living_room_adaptive_override",
    "input_boolean.bathroom_adaptive_override", "input_boolean.bedroom_adaptive_override",
)
def _write(**kwargs):
    """Calculates settings for all rooms and writes them to the appropriate sensors."""
    rooms = ["hallway", "laundry", "kitchen", "living_room", "bathroom", "bedroom"]
    for room in rooms:
        calculation = _calculate_final_settings(room)
        brightness = calculation["brightness"]
        temperature = calculation["temperature"]
        reason = calculation["reason"]

        intel_bri = _to_int(_state(f"sensor.intelligent_brightness_{room}"), 50)
        learned = _get_learned_settings(room, intel_bri, 3500)

        # Common attributes for both entity types
        attrs = {
            "unit_of_measurement": "%",
            "reason": reason,
            "temperature": temperature,
            "learned_temperature": learned["temperature"],
            "home": _state("input_select.home_state", "Day"),
            "adaptive_on": _state("input_boolean.adaptive_learning_enabled", "off") == "on",
            "intelligent_on": _state("input_boolean.intelligent_lighting_enable", "off") == "on",
            "intel_bri": intel_bri,
            "learned_bri": learned["brightness"],
            "using_learned": learned["using_learned"],
            "confirmations": learned["confirmations"],
        }

        # ALWAYS create test entities for comparison (this fixes the backwards logic)
        test_eid = f"pyscript.test_{room}_brightness"
        test_attrs = attrs.copy()
        test_attrs["friendly_name"] = f"TEST {room.title()} Brightness"
        state.set(test_eid, brightness, test_attrs)

        # ALSO create control entities when PyScript mode is active
        USE_PYSCRIPT_MODE = _state("input_boolean.all_rooms_use_pyscript", "off") == "on"
        if USE_PYSCRIPT_MODE:
            control_eid = CFG[room]["final_entity"]
            control_attrs = attrs.copy()
            control_attrs["friendly_name"] = f"{room.title().replace('_', ' ')} Target Brightness"
            state.set(control_eid, brightness, control_attrs)

@task_unique("parallel_test_engine_minutely")
@time_trigger("cron(* * * * *)")
def _loop():
    _write()

# Services — use bare @service so names become:
#   pyscript.parallel_test_run_now
#   pyscript.parallel_kitchen_motion_detected
@service("pyscript.parallel_test_run_now")
def parallel_test_run_now():
    _write()

@service("pyscript.parallel_kitchen_motion_detected")
def parallel_kitchen_motion_detected(sensor=None, timestamp=None):
    # test-only hook; logs without touching real kitchen service name
    now = datetime.datetime.now().strftime("%H:%M:%S")
    log.info(f"[ParallelTest] parallel_kitchen_motion_detected called by {sensor} at {now}")