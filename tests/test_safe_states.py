"""Direct ``states[...]`` indexing must not crash the setup.

Some structure-file states are optional (available since a certain
Miniserver version, or absent for control variants). Every access via
``states["key"]`` during setup raises ``KeyError`` and takes the whole
platform's entity list down. These tests guard the known spots; each
harness constructs the entity exactly like the platform setup does.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from custom_components.loxone.binary_sensor import LoxoneDigitalSensor
from homeassistant.const import STATE_OFF, STATE_ON
from collections import OrderedDict
from custom_components.loxone.button import LoxoneButton
from custom_components.loxone.cover import LoxoneGate, LoxoneJalousie, LoxoneWindow
from custom_components.loxone.select import LoxoneSelect
from custom_components.loxone.sensor import LoxoneTextSensor
from custom_components.loxone.switch import LoxoneSwitch
from custom_components.loxone.lights.lightcontroller import LoxoneLightControllerV2


class _Event(SimpleNamespace):
    """Event stand-in for ``event_handler`` calls."""


def _digital_sensor(**kwargs) -> LoxoneDigitalSensor:
    kwargs.setdefault("uuidAction", "uuid-action")
    kwargs.setdefault("name", "Test")
    kwargs.setdefault("type", "digital")
    kwargs.setdefault("room", "Raum")
    kwargs.setdefault("cat", "Kat")
    kwargs.setdefault("states", {})
    kwargs.setdefault("details", {})
    return LoxoneDigitalSensor(**kwargs)


# --- SmokeAlarm: read the smoke level, not the muted-signal flag ------------


def test_smoke_sensor_without_level_uses_uuid_action():
    """PS-04: smoke reads the alarm level. Without it (optional in the
    structure file) the echoed uuidAction keeps the entity inert."""
    sensor = _digital_sensor(type="smoke")

    assert sensor._state_uuid == "uuid-action"


def test_smoke_sensor_uses_level_not_are_alarm_signals_off():
    """areAlarmSignalsOff tells whether the beeper is muted - a different
    signal than the alarm level."""
    sensor = _digital_sensor(
        type="smoke",
        states={"level": "uuid-level", "areAlarmSignalsOff": "uuid-signals-off"},
    )

    assert sensor._state_uuid == "uuid-level"


def test_smoke_alarm_on_any_level_above_zero():
    """A level of 0.5 or 2 is a smoke event too; only 0 means off."""
    sensor = _digital_sensor(
        type="smoke", states={"level": "uuid-level", "areAlarmSignalsOff": "uuid-signals-off"}
    )
    sensor.async_schedule_update_ha_state = lambda: None

    asyncio.run(sensor.event_handler(SimpleNamespace(data={"uuid-level": 0.5})))
    assert sensor.is_on is True

    asyncio.run(sensor.event_handler(SimpleNamespace(data={"uuid-level": 2.0})))
    assert sensor.is_on is True

    asyncio.run(sensor.event_handler(SimpleNamespace(data={"uuid-level": 0.0})))
    assert sensor.is_on is False


def test_smoke_alarm_ignores_are_alarm_signals_off_state():
    sensor = _digital_sensor(
        type="smoke", states={"level": "uuid-level", "areAlarmSignalsOff": "uuid-signals-off"}
    )
    sensor.async_schedule_update_ha_state = lambda: None

    asyncio.run(
        sensor.event_handler(
            SimpleNamespace(data={"uuid-level": 0.0, "uuid-signals-off": 1.0})
        )
    )

    assert sensor.is_on is False


def test_smoke_sensor_without_state_ignores_events():
    """A smoke sensor without the optional state must be inert, not crash
    on events either."""
    sensor = _digital_sensor(type="smoke")

    sensor.event_handler(SimpleNamespace(data={"uuid-something": 1}))


def test_presence_sensor_without_active_state():
    sensor = _digital_sensor(type="presence")

    assert sensor._state_uuid is None


# --- initial state: unknown until the first event ---------------------------


def test_digital_sensor_is_on_is_none_before_first_event():
    """The sensor must report 'unknown' until an event arrives, not 'off'."""
    sensor = _digital_sensor(states={"active": "uuid-active"})

    assert sensor.is_on is None
    assert sensor.state is None


def test_digital_sensor_is_on_after_events():
    sensor = _digital_sensor(states={"active": "uuid-active"})
    sensor.async_schedule_update_ha_state = lambda: None

    asyncio.run(sensor.event_handler(SimpleNamespace(data={"uuid-action": 1.0})))
    assert sensor.is_on is True
    assert sensor.state == STATE_ON

    asyncio.run(sensor.event_handler(SimpleNamespace(data={"uuid-action": 0.0})))
    assert sensor.is_on is False
    assert sensor.state == STATE_OFF


# --- button / select / switch / text sensor / light controller ---------------


def test_button_attributes_without_active_state():
    """``states['active']`` is only guaranteed for some button types - the
    attributes must not crash when the structure omits it."""
    button = LoxoneButton(
        uuidAction="uuid-action", name="Taster", type="Switch",
        room="", cat="", states={}, details={},
    )

    attrs = button.extra_state_attributes

    assert attrs["state_uuid"] is None


def test_switch_event_without_active_state():
    switch = LoxoneSwitch(
        uuidAction="uuid-action", name="Switch", type="Switch",
        room="", cat="", states={}, details={},
    )
    switch.schedule_update_ha_state = lambda: None
    switch.async_schedule_update_ha_state = lambda: None

    asyncio.run(switch.event_handler(SimpleNamespace(data={"uuid-other": 1.0})))
    attrs = switch.extra_state_attributes

    assert attrs["state_uuid"] is None


def test_select_event_without_states():
    select = LoxoneSelect(
        uuidAction="uuid-action", name="Radio", type="Switch",
        room="", cat="", states={}, details={},
    )
    select.async_schedule_update_ha_state = lambda: None

    asyncio.run(select.event_handler(SimpleNamespace(data={"uuid-other": 1})))

    attrs = select.extra_state_attributes
    assert attrs["state_uuid"] is None


def test_text_sensor_event_without_text_state():
    sensor = LoxoneTextSensor(
        uuidAction="uuid-action", name="Text", type="Switch",
        room="", cat="", states={}, details={},
    )
    sensor.async_schedule_update_ha_state = lambda: None

    # the event must be ignored, and the (base-class) attributes built
    # lazily must not crash either:
    sensor.event_handler(SimpleNamespace(data={"uuid-other": "hello"}))

    assert sensor.extra_state_attributes is not None


def test_light_controller_event_without_mood_states():
    controller = LoxoneLightControllerV2.__new__(LoxoneLightControllerV2)
    controller._attr_extra_state_attributes = {}
    controller.states = {}
    controller._active_moods = []
    controller._moodlist = []
    controller._additional_moodlist = []
    controller._attr_available = False
    controller._attr_is_on = None
    controller._attr_brightness = None
    controller._master_value = None
    controller._master_value_uuid = None
    controller._master_position_uuid = None
    controller._master_min_uuid = None
    controller._master_max_uuid = None
    controller._master_min = None
    controller._master_max = None
    controller._circuit_state_uuids = {}
    controller._circuit_states = {}
    controller.subcontrols = {}
    controller._sub_controls = OrderedDict({})
    controller.type = "LightControllerV2"
    controller.async_schedule_update_ha_state = lambda: None

    # moodList property like in the "moods" service path:
    assert controller.mood_list_uuid is None

    controller.event_handler(SimpleNamespace(data={"uuid-other": 1.0}))
    attrs = controller.extra_state_attributes

    assert controller._active_moods == []


# --- cover: optional states (targetPosition only since MS 11.3; simple
# --- Jalousie variants ship without any automatic-related states) -----------

def _window():
    window = LoxoneWindow.__new__(LoxoneWindow)
    window._attr_extra_state_attributes = {}
    window.states = {"position": "uuid-position"}
    window.uuidAction = "uuid-action"
    window._position = None
    window._closed = True
    window._direction = 0
    window._target_position = None
    window._is_automatic = False
    window._auto_text_uuid = None
    window._auto_state_uuid = None
    window.schedule_update_ha_state = lambda: None
    return window


def _jalousie():
    jalousie = LoxoneJalousie.__new__(LoxoneJalousie)
    jalousie._attr_extra_state_attributes = {}
    jalousie.states = {
        "position": "uuid-position",
        "shadePosition": "uuid-shade",
        "up": "uuid-up",
        "down": "uuid-down",
    }
    jalousie.uuidAction = "uuid-action"
    jalousie._position_loxone = None
    jalousie._position = None
    jalousie._closed = True
    jalousie._tilt_position_loxone = None
    jalousie._tilt_position = None
    jalousie._target_position = None
    jalousie._target_position_tilt = None
    jalousie._is_automatic = False
    jalousie._auto_text_uuid = None
    jalousie._auto_state_uuid = None
    jalousie.schedule_update_ha_state = lambda: None
    return jalousie


def test_window_event_without_direction_and_target_position_states():
    """Pre-11.3 structures carry no targetPosition state (spec: interface
    optional); the event handler must then only process what exists."""
    window = _window()

    asyncio.run(window.event_handler(SimpleNamespace(data={"uuid-position": 0.5})))

    assert window._position == 50.0
    assert window._target_position is None


def test_jalousie_event_without_target_position_and_automatic():
    jalousie = _jalousie()

    asyncio.run(jalousie.event_handler(SimpleNamespace(data={"uuid-position": 0.3})))

    assert jalousie._position_loxone == 30.0
    assert jalousie._target_position is None


def test_jalousie_event_without_shade_position_state():
    """Simple Jalousie variants may lack shadePosition entirely."""
    jalousie = _jalousie()
    jalousie.states = {"position": "uuid-position"}

    asyncio.run(jalousie.event_handler(SimpleNamespace(data={"uuid-position": 0.3})))

    assert jalousie._position_loxone == 30.0
