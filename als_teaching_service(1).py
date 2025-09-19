# /config/pyscript/als_teaching_service.py
# Uses PyMySQL for MariaDB storage - UPDATED WITH BETTER ERROR HANDLING

import datetime
import sqlite3

# --- Database Connection (SQLITE VERSION) ---
def _get_db_connection():
    """Connect to Home Assistant's SQLite database."""
    try:
        return sqlite3.connect("/config/home-assistant_v2.db", timeout=10.0)
    except Exception as e:
        log.error(f"Failed to connect to SQLite database: {e}")
        return None

# ===== Utils =====
def _norm(v, d=None): return d if v in (None, "", "unknown", "unavailable") else v
def _to_int(v, d=0):
    try: return int(float(v))
    except: return d
def _state(eid, d=None):
    try: return _norm(state.get(str(eid)), d)
    except: return d
def _attr(eid, attr, d=None):
    try: return _norm((state.getattr(str(eid)) or {}).get(attr), d)
    except: return d

def _condition_key():
    home_mode = _state("input_select.home_state", "Day")
    sun_el = _attr("sun.sun", "elevation", 0.0)
    clouds = _attr("weather.pirateweather", "cloud_coverage", 0)
    season = _state("sensor.current_season", "Summer")
    sun_bucket = "High_Sun"
    try:
        se = float(sun_el or 0)
        if se < 0: sun_bucket = "Below_Horizon"
        elif se < 15: sun_bucket = "Low_Sun"
        elif se < 40: sun_bucket = "Mid_Sun"
    except: pass
    try: cloud_bucket = int(_to_int(clouds, 0) // 20 * 20)
    except: cloud_bucket = 0
    return f"{home_mode}_{sun_bucket}_{cloud_bucket}_{season}"

def _clamp(v):
    v = _to_int(v, 0)
    return 0 if v < 0 else 100 if v > 100 else v

# ===== Services =====
@service("pyscript.als_teach_room")
def als_teach_room(room=None, brightness=None, temperature=None):
    """
    Teach brightness and temperature sample for the current condition key to SQLite.
    """
    ts_now = datetime.datetime.now()
    ts_iso = ts_now.isoformat(timespec="seconds")

    if room is None or brightness is None:
        log.error("als_teach_room: 'room' and 'brightness' are required.")
        return

    b = _clamp(brightness)
    temp = None
    if temperature is not None:
        temp = max(2200, min(6500, int(temperature)))  # Clamp temp to valid range
    key = _condition_key()

    db_conn = _get_db_connection()
    if not db_conn:
        return

    try:
        cursor = db_conn.cursor()
        
        # Create table if needed (SQLite syntax with temperature support)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS adaptive_learning (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                room TEXT NOT NULL,
                condition_key TEXT NOT NULL,
                brightness_percent INTEGER NOT NULL,
                temperature_kelvin INTEGER NULL,
                timestamp TEXT NOT NULL
            )
        """)
        
        # Insert the teaching sample (SQLite syntax)
        cursor.execute("""
            INSERT INTO adaptive_learning (room, condition_key, brightness_percent, temperature_kelvin, timestamp)
            VALUES (?, ?, ?, ?, ?)
        """, (room, key, b, temp, ts_iso))
        
        db_conn.commit()
        
        # Get sample count for this condition (SQLite syntax)
        cursor.execute("SELECT COUNT(*) FROM adaptive_learning WHERE room = ? AND condition_key = ?", (room, key))
        sample_count = cursor.fetchone()[0]
        
        info = {"room": room, "brightness": b, "key": key, "samples": sample_count, "ts": ts_iso}
        log.info(f"[ALS TEACH DB SUCCESS] {info}")
        state.set("pyscript.last_teach", "ok_db", info)
        
        # Update database status sensor
        state.set("sensor.als_last_teach_status", "success", {
            "friendly_name": "ALS Last Teach Status",
            "room": room,
            "brightness": b,
            "condition_key": key,
            "sample_count": sample_count,
            "last_teach": ts_iso
        })
        
    except sqlite3.Error as e:
        msg = f"als_teach_room_db: SQLite error: {e}"
        log.error(msg)
        state.set("pyscript.last_teach", "sqlite_error", {"message": msg, "ts": ts_iso})
        state.set("sensor.als_last_teach_status", "sqlite_error", {
            "friendly_name": "ALS Last Teach Status",
            "error": str(e),
            "last_attempt": ts_iso
        })
    except Exception as e:
        msg = f"als_teach_room_db: unexpected error: {e}"
        log.error(msg)
        state.set("pyscript.last_teach", "error", {"message": msg, "ts": ts_iso})
        state.set("sensor.als_last_teach_status", "error", {
            "friendly_name": "ALS Last Teach Status",
            "error": str(e),
            "last_attempt": ts_iso
        })
    finally:
        if db_conn:
            db_conn.close()

@service("pyscript.als_get_learned_data")
def als_get_learned_data(room=None):
    """
    Get learned data for a specific room from the database.
    Returns the most recent 20 learned settings for the room.
    """
    if room is None:
        log.error("als_get_learned_data: 'room' parameter is required.")
        return []

    db_conn = _get_db_connection()
    if not db_conn:
        return []

    try:
        cursor = db_conn.cursor()
        
        # Get recent learned data for the room (SQLite syntax)
        cursor.execute("""
            SELECT condition_key, brightness_percent, temperature_kelvin, timestamp, COUNT(*) as sample_count
            FROM adaptive_learning 
            WHERE room = ?
            GROUP BY condition_key
            ORDER BY timestamp DESC
            LIMIT 20
        """, (room,))
        
        results = cursor.fetchall()
        learned_data = []
        
        for row in results:
            condition_key, brightness, temperature, timestamp, count = row
            
            # Parse condition key for display
            parts = condition_key.split('_')
            display_condition = f"{parts[0]} mode"
            if len(parts) > 1:
                if parts[1] != "High_Sun":
                    display_condition += f", {parts[1].replace('_', ' ')}"
            if len(parts) > 2 and int(parts[2]) > 0:
                display_condition += f", {parts[2]}% clouds"
            if len(parts) > 3:
                display_condition += f", {parts[3]}"
            
            learned_entry = {
                "condition": display_condition,
                "brightness": brightness,
                "temperature": temperature,
                "timestamp": timestamp,
                "sample_count": count
            }
            learned_data.append(learned_entry)
        
        log.info(f"Retrieved {len(learned_data)} learned entries for room {room}")
        return learned_data
        
    except sqlite3.Error as e:
        log.error(f"als_get_learned_data: SQLite error: {e}")
        return []
    except Exception as e:
        log.error(f"als_get_learned_data: unexpected error: {e}")
        return []
    finally:
        if db_conn:
            db_conn.close()

@service("pyscript.als_get_automation_predictions")  
def als_get_automation_predictions(room=None):
    """
    Generate automation predictions based on learned data patterns.
    Analyzes time-based patterns to predict what the room will do at different times.
    """
    if room is None:
        log.error("als_get_automation_predictions: 'room' parameter is required.")
        return []

    db_conn = _get_db_connection()
    if not db_conn:
        return []

    try:
        cursor = db_conn.cursor()
        
        # Get all learned data for the room to analyze patterns
        cursor.execute("""
            SELECT condition_key, brightness_percent, temperature_kelvin, timestamp
            FROM adaptive_learning 
            WHERE room = ?
            ORDER BY timestamp DESC
            LIMIT 100
        """, (room,))
        
        results = cursor.fetchall()
        
        if len(results) < 3:
            return [{
                "time": "Need More Data",
                "action": "Teach more settings to see predictions",
                "confidence": 0
            }]
        
        predictions = []
        
        # Analyze patterns by home mode
        mode_patterns = {}
        for row in results:
            condition_key, brightness, temperature, timestamp = row
            parts = condition_key.split('_')
            mode = parts[0] if parts else "Unknown"
            
            if mode not in mode_patterns:
                mode_patterns[mode] = []
            mode_patterns[mode].append({
                "brightness": brightness,
                "temperature": temperature,
                "timestamp": timestamp
            })
        
        # Generate predictions for each mode with sufficient data
        mode_times = {
            "Night": "11:00 PM - 6:00 AM",
            "Early Morning": "6:00 AM - 8:00 AM", 
            "Day": "8:00 AM - 6:00 PM",
            "Evening": "6:00 PM - 11:00 PM"
        }
        
        for mode, data_points in mode_patterns.items():
            if len(data_points) >= 2:  # Need at least 2 samples for confidence
                # Calculate average settings for this mode
                avg_brightness = sum(d["brightness"] for d in data_points) / len(data_points)
                avg_temp = None
                temp_values = [d["temperature"] for d in data_points if d["temperature"]]
                if temp_values:
                    avg_temp = sum(temp_values) / len(temp_values)
                
                # Calculate confidence based on consistency
                brightness_variance = sum((d["brightness"] - avg_brightness) ** 2 for d in data_points) / len(data_points)
                confidence = max(20, min(95, 95 - brightness_variance))
                
                # Generate prediction text
                action = f"Set to {int(avg_brightness)}% brightness"
                if avg_temp:
                    action += f" and {int(avg_temp)}K temperature"
                
                predictions.append({
                    "time": mode_times.get(mode, mode),
                    "action": action,
                    "confidence": int(confidence)
                })
        
        # Sort by confidence
        predictions.sort(key=lambda x: x["confidence"], reverse=True)
        
        # Limit to top 5 predictions
        return predictions[:5]
        
    except sqlite3.Error as e:
        log.error(f"als_get_automation_predictions: SQLite error: {e}")
        return []
    except Exception as e:
        log.error(f"als_get_automation_predictions: unexpected error: {e}")
        return []
    finally:
        if db_conn:
            db_conn.close()