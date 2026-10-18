"""Direct ``states[...]`` indexing must not crash the setup.

Some structure-file states are optional (available since a certain
Miniserver version, or absent for control variants). Every access via
``states["key"]`` during setup raises ``KeyError`` and takes the whole
platform's entity list down. These tests guard the known spots; each
harness constructs the entity exactly like the platform setup does.
"""

from __future__ import annotations

from types import SimpleNamespace

from custom_components.loxone.binary_sensor import LoxoneDigitalSensor
from collections import OrderedDict
from custom_components.loxone.button import LoxoneButton
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

    switch.event_handler(SimpleNamespace(data={"uuid-other": 1.0}))
    attrs = switch.extra_state_attributes

    assert attrs["state_uuid"] is None


def test_select_event_without_states():
    select = LoxoneSelect(
        uuidAction="uuid-action", name="Radio", type="Switch",
        room="", cat="", states={}, details={},
    )
    select.async_schedule_update_ha_state = lambda: None

    select.event_handler(SimpleNamespace(data={"uuid-other": 1}))

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
