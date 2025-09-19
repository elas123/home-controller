# /config/pyscript/als_memory_manager.py
# Uses PyMySQL for storage management - HARDCODED TEST VERSION
# !!! PYSCRIPT FUNCTIONS (motion detection, overrides) !!!
import sqlite3

# --- Database Connection (SQLITE VERSION) ---
def _get_db_connection():
    """Connect to Home Assistant's SQLite database."""
    try:
        conn = sqlite3.connect("/config/home-assistant_v2.db", timeout=10.0)
        conn.row_factory = sqlite3.Row  # Makes results easier to work with
        
        # Ensure table exists
        cursor = conn.cursor()
        # Ensure table exists with temperature support
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
        conn.commit()
        # Migrate if legacy table missing temperature column
        try:
            cursor.execute("PRAGMA table_info(adaptive_learning)")
            cols = [row[1] for row in cursor.fetchall()]
            if "temperature_kelvin" not in cols:
                cursor.execute("ALTER TABLE adaptive_learning ADD COLUMN temperature_kelvin INTEGER NULL")
                conn.commit()
        except Exception as _:
            # Non-fatal; reading code tolerates NULLs
            pass
        
        return conn
        
    except Exception as e:
        log.error(f"Failed to connect to SQLite database from memory manager: {e}")
        return None

# --- Helper Functions ---
def _norm_room(room_str):
    """Normalizes room name from Lovelace."""
    r = str(room_str).lower().replace(" ", "_")
    return "living_room" if r == "livingroom" else r

# --- Services to Power the Form ---

@state_trigger("input_select.als_teaching_room")
def populate_condition_keys(value=None):
    """When a room is selected, this populates the second dropdown with its condition keys from the database."""
    room_key = _norm_room(value)
    options = ["No learned data for this room"]

    db_conn = _get_db_connection()
    if db_conn:
        try:
            cursor = db_conn.cursor()
            sql = "SELECT DISTINCT condition_key FROM adaptive_learning WHERE room = ? ORDER BY condition_key"
            cursor.execute(sql, (room_key,))
            results = cursor.fetchall()
            if results:
                options = [row['condition_key'] for row in results]
        except Exception as e:
            log.error(f"Error fetching condition keys: {e}")
        finally:
            if db_conn:
                db_conn.close()

    service.call("input_select", "set_options", entity_id="input_select.als_memory_condition_key", options=options)
    service.call("input_select", "select_option", entity_id="input_select.als_memory_condition_key", option=options[0])
    service.call("input_select", "set_options", entity_id="input_select.als_memory_sample", options=["Select a condition first"])


@state_trigger("input_select.als_memory_condition_key")
def populate_samples(value=None):
    """When a condition key is selected, this populates the third dropdown with its individual samples from the database."""
    condition_key = value
    room_key = _norm_room(state.get("input_select.als_teaching_room"))
    options = ["No samples for this condition"]

    db_conn = _get_db_connection()
    if db_conn:
        try:
            cursor = db_conn.cursor()
            sql = "SELECT id, brightness_percent FROM adaptive_learning WHERE room = ? AND condition_key = ? ORDER BY timestamp"
            cursor.execute(sql, (room_key, condition_key))
            results = cursor.fetchall()
            if results:
                options = [f"ID {row['id']}: {row['brightness_percent']}%" for row in results]
        except Exception as e:
            log.error(f"Error fetching samples: {e}")
        finally:
            if db_conn:
                db_conn.close()

    service.call("input_select", "set_options", entity_id="input_select.als_memory_sample", options=options)
    service.call("input_select", "select_option", entity_id="input_select.als_memory_sample", option=options[0])

@service("pyscript.als_delete_selected_sample")
def als_delete_selected_sample():
    """Deletes the single sample currently selected in the dropdowns from the database."""
    selected_sample_str = state.get("input_select.als_memory_sample")

    try:
        sample_id = int(selected_sample_str.split(":")[0].replace("ID ", ""))
    except (ValueError, AttributeError):
        log.error("Could not determine which sample ID to delete.")
        return

    db_conn = _get_db_connection()
    if db_conn:
        try:
            cursor = db_conn.cursor()
            sql = "DELETE FROM adaptive_learning WHERE id = ?"
            cursor.execute(sql, (sample_id,))
            db_conn.commit()
            log.info(f"Deleted sample with ID {sample_id} from the database.")

            populate_condition_keys(value=state.get("input_select.als_teaching_room"))
        except Exception as e:
            log.error(f"Error deleting sample: {e}")
        finally:
            if db_conn:
                db_conn.close()

@service("pyscript.als_delete_condition_key")
def als_delete_condition_key(room=None, condition_key=None):
    """Deletes all samples for a given condition key in a room's memory from the database."""
    room_key = _norm_room(room)

    db_conn = _get_db_connection()
    if db_conn:
        try:
            cursor = db_conn.cursor()
            sql = "DELETE FROM adaptive_learning WHERE room = ? AND condition_key = ?"
            cursor.execute(sql, (room_key, condition_key))
            db_conn.commit()
            log.info(f"Deleted all samples for condition key '{condition_key}' from {room_key}")
        except Exception as e:
            log.error(f"Error deleting condition key: {e}")
        finally:
            if db_conn:
                db_conn.close()
