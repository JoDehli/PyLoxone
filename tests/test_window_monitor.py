"""WindowMonitor ("Fenster- und Türüberwachung", #524).

Shape per the Loxone structure file v16 (p. 157-158) and the reporter's
excerpt in #524: ``details.windows[]`` lists the contacts, the text state
``windowStates`` carries one comma-separated bitmask per contact in that
order (0 offline, 1 closed, 2 tilted, 4 open, 8 locked, 16 unlocked; a
lockable door reports 8 / 16 / 4 as single values).

The fixture has two monitors: "Bathroom Windows" (room monitor, one contact)
and "Window and Door Monitoring" (central monitor in the Hall):

    index 0  Fenster Bad      (also in the room monitor -> fed from there)
    index 1  Office Window    room Office
    index 2  Kitchen Window   uuid of the motorised Window cover -> skipped
    index 3  Main Door        uuid of the InfoOnlyDigital "Main Door"
    index 4  Garden Door      room Garden

Expected values are literals read from the fixture and the issue.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from custom_components.loxone.window_monitor import (
    LoxoneWindowContactSensor,
    LoxoneWindowPositionSensor,
    parse_window_states,
    window_contacts,
    window_position,
    window_state,
)

FIXTURE = Path(__file__).parent / "fixtures" / "LoxAPP3.json"

ROOM_STATES = "1efaa7ad-0217-ede4-ffff5b41adbf0217"
CENTRAL_STATES = "1efaa7ad-0227-ede4-ffff5b41adbf0227"
CENTRAL_NUM_OPEN = "1efaa7ad-0221-edee-08ff5b41adbf0221"
CENTRAL_NUM_CLOSED = "1efaa7ad-0222-edf0-0aff5b41adbf0222"

FENSTER_BAD = "1efaa31b-0013-66fe-ffffed57184a0001"
OFFICE_WINDOW = "1efaa623-0370-7089-ffffed57184a0002"
KITCHEN_WINDOW = "63746c3a-017b-9746-ffff-8656e2057696000123"
MAIN_DOOR = "63746c3a-0301-96d7-ffff-572617475726000098"
GARDEN_DOOR = "1f263a35-017e-1ac2-ffff8a31785a0003"


async def _setup(hass, mock_entry) -> None:
    mock_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(mock_entry.entry_id)
    await hass.async_block_till_done()


async def _unload(hass, mock_entry) -> None:
    await hass.config_entries.async_unload(mock_entry.entry_id)
    await hass.async_block_till_done()


def _entity(hass, domain: str, unique_id: str) -> str | None:
    return er.async_get(hass).async_get_entity_id(domain, "loxone", unique_id)


async def test_setup_creates_one_entity_set_per_contact(
    hass, mock_connection, mock_entry, enable_custom_integrations, caplog
):
    await _setup(hass, mock_entry)
    registry = er.async_get(hass)
    # Deduplicated before HA sees them: no rejected duplicate unique id.
    assert "does not generate unique IDs" not in caplog.text

    assert _entity(hass, "binary_sensor", f"{FENSTER_BAD}-window") == "binary_sensor.bathroom_fenster_bad"
    assert _entity(hass, "sensor", f"{FENSTER_BAD}-state") == "sensor.bathroom_fenster_bad_state"
    assert _entity(hass, "binary_sensor", f"{OFFICE_WINDOW}-window") == "binary_sensor.office_office_window"
    assert _entity(hass, "binary_sensor", f"{GARDEN_DOOR}-window") == "binary_sensor.garden_garden_door"

    # Fenster Bad is in both monitors but exists once.
    fenster = [e for e in registry.entities.values() if e.unique_id.startswith(FENSTER_BAD)]
    assert sorted(e.unique_id for e in fenster) == [f"{FENSTER_BAD}-state", f"{FENSTER_BAD}-window"]

    # The motorised Kitchen Window stays a cover only.
    assert [e.entity_id for e in registry.entities.values() if e.unique_id.startswith(KITCHEN_WINDOW)] == [
        "cover.kitchen_kitchen_window"
    ]

    # Main Door is a real InfoOnlyDigital: suffixed ids, its device is
    # shared and keeps its name/model.
    assert _entity(hass, "binary_sensor", MAIN_DOOR) == "binary_sensor.hall_main_door"
    assert _entity(hass, "binary_sensor", f"{MAIN_DOOR}-window") == "binary_sensor.hall_main_door_contact"
    devices = dr.async_get(hass)
    main_device = devices.async_get(registry.async_get("binary_sensor.hall_main_door_contact").device_id)
    assert main_device.id == registry.async_get("binary_sensor.hall_main_door").device_id
    assert main_device.name == "Main Door"
    assert main_device.model == "digital"

    # Each contact's device sits in the contact's own room, not the
    # central monitor's (Hall).
    office_device = devices.async_get(registry.async_get("binary_sensor.office_office_window").device_id)
    assert office_device.name == "Office Window"
    assert office_device.model == "Window contact"
    assert ar.async_get(hass).async_get_area(office_device.area_id).name == "Office"

    state = hass.states.get("binary_sensor.office_office_window")
    assert state.attributes["device_class"] == "window"
    assert state.attributes["install_place"] == "North wall"
    assert state.attributes["monitor"] == "Window and Door Monitoring"
    assert hass.states.get("sensor.office_office_window_state").attributes["options"] == [
        "closed",
        "tilted",
        "open",
        "locked",
        "unlocked",
    ]

    # The lock state lives in the enum sensor: no separate lock entity.
    assert not [e for e in registry.entities.values() if e.unique_id.endswith("-lock")]

    await _unload(hass, mock_entry)


async def test_window_states_decode_in_list_order(hass, mock_connection, mock_entry, enable_custom_integrations):
    await _setup(hass, mock_entry)

    # Fenster Bad (index 0) is fed by the room monitor; Kitchen (index 2)
    # is skipped; Main Door unlocked, Garden Door locked.
    mock_connection.feed(CENTRAL_STATES, "4,2,1,16,8")
    await hass.async_block_till_done()

    office = hass.states.get("binary_sensor.office_office_window")
    assert office.state == STATE_ON  # tilted counts as open
    assert office.attributes["position"] == "tilted"
    assert office.attributes["icon"] == "mdi:window-open-variant"
    assert hass.states.get("sensor.office_office_window_state").state == "tilted"
    assert hass.states.get("binary_sensor.hall_main_door_contact").state == STATE_OFF  # 16 = closed
    assert hass.states.get("sensor.hall_main_door_state").state == "unlocked"
    garden = hass.states.get("binary_sensor.garden_garden_door")
    assert garden.state == STATE_OFF  # 8 = closed
    assert garden.attributes["position"] == "locked"
    assert garden.attributes["icon"] == "mdi:window-closed-variant"
    assert hass.states.get("sensor.garden_garden_door_state").state == "locked"
    assert hass.states.get("binary_sensor.bathroom_fenster_bad").state == STATE_UNKNOWN

    mock_connection.feed(ROOM_STATES, "4")
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.bathroom_fenster_bad").state == STATE_ON
    assert hass.states.get("sensor.bathroom_fenster_bad_state").state == "open"
    assert hass.states.get("binary_sensor.bathroom_fenster_bad").attributes["raw_state"] == 4

    await _unload(hass, mock_entry)


async def test_lockable_door_reports_locked_and_unlocked(hass, mock_connection, mock_entry, enable_custom_integrations):
    await _setup(hass, mock_entry)

    # The reporter's garden-door sequence 8 -> 16 -> 4 -> 16 -> 8
    # (lock, unlock, open, close, lock).
    for raw, contact, state, icon in (
        ("8", STATE_OFF, "locked", "mdi:window-closed-variant"),
        ("16", STATE_OFF, "unlocked", None),
        ("4", STATE_ON, "open", None),
        ("16", STATE_OFF, "unlocked", None),
        ("8", STATE_OFF, "locked", "mdi:window-closed-variant"),
    ):
        mock_connection.feed(CENTRAL_STATES, f"1,1,1,16,{raw}")
        await hass.async_block_till_done()
        door = hass.states.get("binary_sensor.garden_garden_door")
        assert door.state == contact, raw
        assert door.attributes["position"] == state, raw
        assert door.attributes.get("icon") == icon, raw
        assert hass.states.get("sensor.garden_garden_door_state").state == state, raw

    await _unload(hass, mock_entry)


async def test_offline_and_missing_values_are_unavailable(
    hass, mock_connection, mock_entry, enable_custom_integrations, caplog
):
    await _setup(hass, mock_entry)

    mock_connection.feed(CENTRAL_STATES, "1,0,1,1,1")
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.office_office_window").state == STATE_UNAVAILABLE
    assert hass.states.get("sensor.office_office_window_state").state == STATE_UNAVAILABLE
    assert hass.states.get("binary_sensor.garden_garden_door").state == STATE_OFF

    # Fewer values than windows: the contacts without one are unavailable,
    # and the mismatch is logged once.
    caplog.set_level(logging.DEBUG, logger="custom_components.loxone.window_monitor")
    mock_connection.feed(CENTRAL_STATES, "1,1")
    await hass.async_block_till_done()
    mock_connection.feed(CENTRAL_STATES, "1,4")
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.office_office_window").state == STATE_ON
    assert hass.states.get("binary_sensor.hall_main_door_contact").state == STATE_UNAVAILABLE
    assert hass.states.get("binary_sensor.garden_garden_door").state == STATE_UNAVAILABLE
    mismatch = [r for r in caplog.records if "values in windowStates" in r.getMessage()]
    assert len(mismatch) <= 2  # once per platform (binary_sensor, sensor)
    assert {r.levelno for r in mismatch} == {logging.DEBUG}

    # Back to a full list: available again.
    mock_connection.feed(CENTRAL_STATES, "1,1,1,1,4")
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.garden_garden_door").state == STATE_ON

    await _unload(hass, mock_entry)


async def test_monitor_count_sensors(hass, mock_connection, mock_entry, enable_custom_integrations):
    await _setup(hass, mock_entry)
    registry = er.async_get(hass)

    open_id = _entity(hass, "sensor", CENTRAL_NUM_OPEN)
    assert open_id == "sensor.hall_window_and_door_monitoring_open"
    assert hass.states.get(open_id).attributes["state_class"] == "measurement"
    closed_entry = registry.async_get(_entity(hass, "sensor", CENTRAL_NUM_CLOSED))
    assert closed_entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION

    device = dr.async_get(hass).async_get(registry.async_get(open_id).device_id)
    assert device.name == "Window and Door Monitoring"
    assert device.model == "WindowMonitor"

    mock_connection.feed(CENTRAL_NUM_OPEN, 3.0)
    await hass.async_block_till_done()
    assert hass.states.get(open_id).state == "3"

    await _unload(hass, mock_entry)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1,2,4,8,16", [1, 2, 4, 8, 16]),
        (" 1 , 0 ,", [1, 0, 0]),
        ("1,x,4", [1, None, 4]),
        ("", []),
        (4.0, [4]),
        (None, None),
        (True, None),
        ([1, 2], None),
    ],
)
def test_parse_window_states(raw, expected):
    assert parse_window_states(raw) == expected


@pytest.mark.parametrize(
    ("value", "position", "state"),
    [
        (0, None, None),
        (None, None, None),
        (1, "closed", "closed"),
        (2, "tilted", "tilted"),
        (4, "open", "open"),
        (8, "closed", "locked"),
        (16, "closed", "unlocked"),
        (9, "closed", "locked"),
        (17, "closed", "unlocked"),
        (12, "open", "open"),  # an open door cannot be locked
        (32, None, None),
    ],
)
def test_window_value_decoding(value, position, state):
    assert window_position(value) == position
    assert window_state(value) == state


def test_contact_entities_have_a_name():
    """
    Every contact entity must answer ``name`` without raising.

    ``LoxoneEntity.name`` returns ``_attr_name``; a contact that is not a
    control of its own used to leave it unset, which raised AttributeError
    and dropped the whole binary_sensor platform setup for that contact.
    """
    contacts = window_contacts(json.loads(FIXTURE.read_text(encoding="utf-8")))
    names = {}
    for contact in contacts:
        window = LoxoneWindowContactSensor(contact)
        state = LoxoneWindowPositionSensor(contact)
        assert window.has_entity_name
        assert state.has_entity_name
        names[contact.uuid] = (window.name, state.name)
    assert names == {
        FENSTER_BAD: (None, "State"),
        OFFICE_WINDOW: (None, "State"),
        MAIN_DOOR: ("Contact", "State"),
        GARDEN_DOOR: (None, "State"),
    }
