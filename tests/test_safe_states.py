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


# --- SmokeAlarm: areAlarmSignalsOff is optional (spec, since 10.3) ----------


def test_smoke_sensor_without_are_alarm_signals_off_state():
    """Bug: ``states['areAlarmSignalsOff']`` crashed the setup whenever the
    structure file omitted the optional state (0 occurrences in this
    installation's real structure)."""
    sensor = _digital_sensor(type="smoke")

    assert sensor._state_uuid is None


def test_smoke_sensor_with_are_alarm_signals_off_state():
    sensor = _digital_sensor(
        type="smoke", states={"areAlarmSignalsOff": "uuid-signals-off"}
    )

    assert sensor._state_uuid == "uuid-signals-off"


def test_smoke_sensor_without_state_ignores_events():
    """A smoke sensor without the optional state must be inert, not crash
    on events either."""
    sensor = _digital_sensor(type="smoke")

    sensor.event_handler(SimpleNamespace(data={"uuid-something": 1}))


def test_presence_sensor_without_active_state():
    sensor = _digital_sensor(type="presence")

    assert sensor._state_uuid is None


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
