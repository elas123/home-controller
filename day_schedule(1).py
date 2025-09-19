
"""
day_schedule.py — publishes today's sunrise/sunset as local ISO strings
Used by home_controller.py for Evening window & Day gates.
"""

from datetime import datetime, timedelta

def _now_local():
    return datetime.now().astimezone()

def _parse_aware(s):
    try:
        return datetime.fromisoformat(str(s))
    except Exception:
        return None

def _to_local_iso(dt):
    if dt is None:
        return ""
    try:
        return dt.astimezone(_now_local().tzinfo).replace(microsecond=0).isoformat()
    except Exception:
        return ""

def _compute_today_events():
    """Derive sunrise_today & sunset_today from sun.sun's next events.
       If we're past an event, subtract 1 day from the next event to approximate today's timestamp.
       (Accuracy is within ~1–2 minutes, which is fine for a 15-minute window.)
    """
    now = _now_local()
    next_rising  = _parse_aware(state.getattr("sun.sun").get("next_rising"))
    next_setting = _parse_aware(state.getattr("sun.sun").get("next_setting"))

    sunrise_today = None
    sunset_today  = None

    if next_rising:
        if next_rising.astimezone(now.tzinfo).date() == now.date():
            sunrise_today = next_rising
        else:
            # Past today's sunrise → approximate by subtracting 1 day
            sunrise_today = next_rising - timedelta(days=1)

    if next_setting:
        if next_setting.astimezone(now.tzinfo).date() == now.date():
            sunset_today = next_setting
        else:
            # Past today's sunset → approximate by subtracting 1 day
            sunset_today = next_setting - timedelta(days=1)

    return _to_local_iso(sunrise_today), _to_local_iso(sunset_today)

def _publish():
    sunrise_iso, sunset_iso = _compute_today_events()
    state.set("pyscript.sunrise_today", sunrise_iso, {
        "friendly_name": "Sunrise (today, local ISO)",
        "icon": "mdi:weather-sunset-up"
    })
    state.set("pyscript.sunset_today", sunset_iso, {
        "friendly_name": "Sunset (today, local ISO)",
        "icon": "mdi:weather-sunset-down"
    })
    state.set("sensor.day_schedule_last_update", _now_local().replace(microsecond=0).isoformat(), {
        "friendly_name": "Day Schedule Last Update",
        "icon": "mdi:clock-check"
    })

@time_trigger("startup")
def _on_startup():
    _publish()

# Update shortly after midnight so values point to the new day
@time_trigger("cron(0 1 0 * * *)")  # 00:01 local
def _after_midnight():
    _publish()

# Also refresh when the sun entity changes significantly (rare, but safe)
@state_trigger("sun.sun")
def _on_sun_change(value=None):
    _publish()
