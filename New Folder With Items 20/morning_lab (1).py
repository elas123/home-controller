from datetime import datetime, timedelta

# Core functions
def _state(entity_id):
    v = state.get(entity_id)
    return str(v) if v else ""

def _is_freeze_active():
    return _state("input_boolean.time_freeze_active").lower() == "on"

def _now():
    if _is_freeze_active():
        iso = _state("input_datetime.time_freeze_clock")
        if iso and iso != "unknown":
            try:
                return datetime.fromisoformat(iso.replace("T", " "))
            except:
                pass
    return datetime.now()

def _set_effective_now(dt):
    state.set("sensor.effective_now", 
              dt.strftime("%B %d, %Y %H:%M:%S"),
              {"iso": dt.isoformat(), "simulation": "on" if _is_freeze_active() else "off"})

def _apply_freeze_datetime(dt):
    service.call("input_boolean", "turn_on", entity_id="input_boolean.time_freeze_active")
    service.call("input_datetime", "set_datetime", 
                 entity_id="input_datetime.time_freeze_clock",
                 datetime=dt.strftime("%Y-%m-%d %H:%M:%S"))
    _set_effective_now(dt)

# Services
@service
def hc_apply_picker_time():
    raw = _state("input_datetime.time_freeze_clock")
    if raw and raw != "unknown":
        dt = datetime.fromisoformat(raw.replace("T", " "))
        _apply_freeze_datetime(dt)
        log.info("[ML] Applied time")

@service
def hc_run_full_test_once():
    raw = _state("input_datetime.time_freeze_clock")
    if raw and raw != "unknown":
        dt = datetime.fromisoformat(raw.replace("T", " "))
        _apply_freeze_datetime(dt)
        service.call("input_select", "select_option", 
                     entity_id="input_select.home_state", option="Night")
        service.call("pyscript", "morning_ramp_first_motion",
                    sensor="binary_sensor.kitchen_test_simulated_motion")

@service
def manual_morning_reset():
    service.call("input_select", "select_option",
                 entity_id="input_select.home_state", option="Night")

@service
def disable_test_time():
    service.call("input_boolean", "turn_off", entity_id="input_boolean.time_freeze_active")
    _set_effective_now(datetime.now())

@service
def advance_sim_time(minutes=1):
    if _is_freeze_active():
        current = _now()
        new_time = current + timedelta(minutes=minutes)
        _apply_freeze_datetime(new_time)

@service
def test_time(hour, minute=0):
    dt = datetime.now().replace(hour=hour, minute=minute, second=0)
    _apply_freeze_datetime(dt)

@service
def hc_back_to_normal():
    service.call("input_boolean", "turn_off", entity_id="input_boolean.time_freeze_active")
    _set_effective_now(datetime.now())

# Update sensor periodically
@time_trigger("cron(* * * * *)")
def update_effective_now():
    _set_effective_now(_now())

@time_trigger("startup")
def on_start():
    _set_effective_now(_now())
    log.info("[ML] Morning lab loaded")
