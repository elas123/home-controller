import asyncio
from datetime import datetime, time as dt_time
import importlib.util
from pathlib import Path
import sys
from typing import Any

import pytest


class DummyState:
    def __init__(self):
        self.states: dict[str, Any] = {}
        self.attrs: dict[str, dict[str, Any]] = {}

    def set(self, entity_id: str, value: Any, attrs: dict | None = None):
        self.states[entity_id] = value
        self.attrs[entity_id] = dict(attrs or {})

    def get(self, entity_id: str, default: Any = None):
        return self.states.get(entity_id, default)

    def getattr(self, entity_id: str):
        return self.attrs.get(entity_id, {})

    def names(self, domain: str | None = None):
        if domain is None:
            return list(self.states.keys())
        prefix = f"{domain}."
        return [entity for entity in self.states if entity.startswith(prefix)]


class DummyService:
    def __init__(self, state: DummyState):
        self.state = state
        self.calls = []

    def __call__(self, *_args, **_kwargs):
        def decorator(fn):
            return fn
        return decorator

    def call(self, domain: str, service_name: str, **data):
        self.calls.append((domain, service_name, data))

        if domain == "input_boolean":
            entity = data.get("entity_id")
            if entity:
                value = "on" if service_name == "turn_on" else "off"
                self.state.set(entity, value)
        elif domain == "input_text" and service_name == "set_value":
            entity = data.get("entity_id")
            if entity:
                self.state.set(entity, data.get("value", ""))
        elif domain == "input_datetime" and service_name == "set_datetime":
            entity = data.get("entity_id")
            if entity:
                dt_value = data.get("datetime")
                attrs: dict[str, Any] = {}
                if isinstance(dt_value, str):
                    parsed = None
                    try:
                        parsed = datetime.fromisoformat(dt_value)
                    except ValueError:
                        try:
                            parsed = datetime.strptime(dt_value, "%Y-%m-%d %H:%M:%S")
                        except ValueError:
                            parsed = None
                    if parsed:
                        attrs["timestamp"] = parsed.timestamp()
                self.state.set(entity, dt_value, attrs)
        elif domain == "input_number" and service_name == "set_value":
            entity = data.get("entity_id")
            if entity:
                self.state.set(entity, data.get("value"))
        elif domain == "input_select" and service_name == "select_option":
            entity = data.get("entity_id")
            if entity:
                self.state.set(entity, data.get("option"))
        elif domain == "light" and service_name == "turn_on":
            entity = data.get("entity_id")
            if entity:
                if isinstance(entity, (list, tuple)):
                    for item in entity:
                        self.state.set(item, "on")
                else:
                    self.state.set(entity, "on")
        # mqtt/persistent_notification/etc. are ignored for tests


class DummyTaskHandle:
    def __init__(self):
        self.cancelled = False

    def cancel(self):
        self.cancelled = True

    def done(self):
        return True


class DummyTaskModule:
    def __init__(self):
        self.created = []

    def create(self, coro):
        self.created.append(coro)
        try:
            asyncio.run(coro)
        except RuntimeError:
            loop = asyncio.new_event_loop()
            loop.run_until_complete(coro)
            loop.close()
        return DummyTaskHandle()


class DummyLog:
    def __init__(self):
        self.messages = []

    def _record(self, level: str, message: str, *args):
        if args:
            try:
                message = message % args
            except Exception:
                message = " ".join([message, *map(str, args)])
        self.messages.append((level, message))

    def info(self, message, *args):
        self._record("info", message, *args)

    def warning(self, message, *args):
        self._record("warning", message, *args)

    def error(self, message, *args):
        self._record("error", message, *args)

    def debug(self, message, *args):
        self._record("debug", message, *args)


@pytest.fixture()
def hc_env():
    sys.modules.pop("home_controller", None)
    spec = importlib.util.spec_from_file_location(
        "home_controller", Path(__file__).resolve().parents[1] / "home_controller.py"
    )
    module = importlib.util.module_from_spec(spec)

    dummy_state = DummyState()
    dummy_service = DummyService(dummy_state)
    dummy_task = DummyTaskModule()
    dummy_log = DummyLog()

    decorator = lambda *args, **kwargs: (lambda fn: fn)

    module.state = dummy_state
    module.service = dummy_service
    module.task = dummy_task
    module.log = dummy_log
    module.time_trigger = decorator
    module.state_trigger = decorator
    module.event_trigger = decorator
    module.service_trigger = decorator

    spec.loader.exec_module(module)

    return module, dummy_state


def prime_defaults(state: DummyState):
    state.set("input_boolean.em_active", "off")
    state.set("input_boolean.sleep_in_ramp_active", "off")
    state.set("input_boolean.sleep_in_ramp_system_enable", "on")
    state.set("input_boolean.daily_motion_lock", "off")
    state.set("input_boolean.time_freeze_active", "off")
    state.set("input_text.em_route_key", "")
    state.set("input_text.em_until", "")
    state.set("input_datetime.em_start_ts", "")
    state.set("input_datetime.ramp_start_time", "")
    state.set("input_datetime.ramp_calculated_end_time", "")
    state.set("input_number.calculated_ramp_duration", 0)
    state.set("input_select.home_state", "Day")
    state.set("pyscript.home_state", "Day")


def test_day_off_classification_at_603(hc_env):
    module, state = hc_env
    prime_defaults(state)

    state.set("pyscript.sunrise_today", "2024-01-05T07:10:00")
    state.set("pyscript.sunset_today", "2024-01-05T17:05:00")
    state.set("input_datetime.day_earliest_time", "07:30:00")
    state.set("input_number.day_target_brightness_fallback", 75)

    now = datetime(2024, 1, 5, 6, 3)
    module._now = lambda: now

    module._refresh_daily_constants()

    captured = {}

    async def fake_nonwork(start_time_override=None):
        captured["start_time"] = start_time_override
        module._set_ramp_temperature(module.NONWORK_RAMP_START_TEMP)
        state.set("input_boolean.sleep_in_ramp_active", "on")

    module._start_nonwork_ramp = fake_nonwork
    module._work_ramp_task = None
    module._nonwork_ramp_task = None

    module._classify_kitchen_motion("binary_sensor.aqara_motion_sensor_p1_occupancy")

    assert module._morning_motion_profile == "day_off"
    assert state.get("pyscript.home_state") == "Early Morning"
    assert state.get("sensor.pys_morning_ramp_profile") == "day_off"
    assert state.get("input_text.em_route_key") == "day_off"
    assert captured["start_time"].time() == dt_time(6, 3)
    assert state.get("sensor.sleep_in_ramp_temperature") == module.NONWORK_RAMP_START_TEMP


def test_work_prework_motion_holds_until_450(hc_env):
    module, state = hc_env
    prime_defaults(state)

    now = datetime(2024, 1, 5, 4, 47)
    module._now = lambda: now

    captured = {}

    async def fake_work(restore_from_time=None):
        captured["start_time"] = restore_from_time
        module._set_ramp_temperature(module.WORK_RAMP_START_TEMP)

    module._start_work_ramp = fake_work
    module._work_ramp_task = None
    module._nonwork_ramp_task = None

    module._classify_kitchen_motion("binary_sensor.kitchen_iris_frig_occupancy")

    assert module._morning_motion_profile == "work"
    assert state.get("sensor.pys_morning_ramp_profile") == "work"
    assert captured["start_time"].time() == dt_time(4, 50)
    assert state.get("sensor.sleep_in_ramp_temperature") == module.WORK_RAMP_START_TEMP


def test_ramps_publish_temperature_sensor(hc_env):
    module, state = hc_env
    prime_defaults(state)

    start_time = datetime(2024, 1, 5, 6, 3)
    module._compute_day_commit_time = lambda: start_time
    module._resolve_day_target_brightness = lambda: (60, "test")
    module._now = lambda: start_time

    asyncio.run(module._start_nonwork_ramp(start_time_override=start_time))
    assert state.get("sensor.sleep_in_ramp_temperature") == module.NONWORK_RAMP_END_TEMP
    assert state.get("sensor.sleep_in_ramp_kelvin") == module.NONWORK_RAMP_END_TEMP

    module._now = lambda: datetime(2024, 1, 5, 5, 40)
    asyncio.run(module._start_work_ramp(restore_from_time=datetime(2024, 1, 5, 4, 50)))
    assert state.get("sensor.sleep_in_ramp_temperature") == module.WORK_RAMP_END_TEMP
    assert state.get("sensor.sleep_in_ramp_kelvin") == module.WORK_RAMP_END_TEMP
