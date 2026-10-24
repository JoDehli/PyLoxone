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

import logging

import pytest
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from custom_components.loxone.window_monitor import (
    parse_window_states,
    window_position,
    window_unlocked,
)

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
    assert hass.states.get("sensor.office_office_window_state").attributes["options"] == ["closed", "tilted", "open"]

    # No lock entity before any contact has reported a lock bit.
    assert not [e for e in registry.entities.values() if e.unique_id.endswith("-lock")]

    await _unload(hass, mock_entry)


async def test_window_states_decode_in_list_order(hass, mock_connection, mock_entry, enable_custom_integrations):
    await _setup(hass, mock_entry)

    # Fenster Bad (index 0) is fed by the room monitor; Kitchen (index 2)
    # is skipped; Main Door unlocked, Garden Door locked.
    mock_connection.feed(CENTRAL_STATES, "4,2,1,16,8")
    await hass.async_block_till_done()

    assert hass.states.get("binary_sensor.office_office_window").state == STATE_ON  # tilted counts as open
    assert hass.states.get("sensor.office_office_window_state").state == "tilted"
    assert hass.states.get("binary_sensor.hall_main_door_contact").state == STATE_OFF  # 16 = closed
    assert hass.states.get("sensor.hall_main_door_state").state == "closed"
    assert hass.states.get("binary_sensor.garden_garden_door").state == STATE_OFF  # 8 = closed
    assert hass.states.get("sensor.garden_garden_door_state").state == "closed"
    assert hass.states.get("binary_sensor.bathroom_fenster_bad").state == STATE_UNKNOWN

    mock_connection.feed(ROOM_STATES, "4")
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.bathroom_fenster_bad").state == STATE_ON
    assert hass.states.get("sensor.bathroom_fenster_bad_state").state == "open"
    assert hass.states.get("binary_sensor.bathroom_fenster_bad").attributes["raw_state"] == 4

    await _unload(hass, mock_entry)


async def test_lock_entities_appear_for_contacts_with_lock_bits(
    hass, mock_connection, mock_entry, enable_custom_integrations
):
    await _setup(hass, mock_entry)

    mock_connection.feed(CENTRAL_STATES, "1,1,1,16,8")
    await hass.async_block_till_done()

    main_lock = _entity(hass, "binary_sensor", f"{MAIN_DOOR}-lock")
    garden_lock = _entity(hass, "binary_sensor", f"{GARDEN_DOOR}-lock")
    assert main_lock == "binary_sensor.hall_main_door_lock"
    assert garden_lock == "binary_sensor.garden_garden_door_lock"
    assert _entity(hass, "binary_sensor", f"{OFFICE_WINDOW}-lock") is None
    assert hass.states.get(main_lock).attributes["device_class"] == "lock"
    assert hass.states.get(main_lock).state == STATE_ON  # 16 = unlocked
    assert hass.states.get(garden_lock).state == STATE_OFF  # 8 = locked

    # The reporter's garden-door sequence 8 -> 16 -> 4 -> 16 -> 8.
    for raw, contact, lock in (
        ("16", STATE_OFF, STATE_ON),
        ("4", STATE_ON, STATE_ON),
        ("16", STATE_OFF, STATE_ON),
        ("8", STATE_OFF, STATE_OFF),
    ):
        mock_connection.feed(CENTRAL_STATES, f"1,1,1,16,{raw}")
        await hass.async_block_till_done()
        assert hass.states.get("binary_sensor.garden_garden_door").state == contact, raw
        assert hass.states.get(garden_lock).state == lock, raw

    await _unload(hass, mock_entry)


async def test_known_lock_entity_is_created_at_setup(hass, mock_connection, mock_entry, enable_custom_integrations):
    """A lock seen in an earlier run comes back with the platform, not later."""
    mock_entry.add_to_hass(hass)
    er.async_get(hass).async_get_or_create(
        "binary_sensor",
        "loxone",
        f"{GARDEN_DOOR}-lock",
        config_entry=mock_entry,
        suggested_object_id="garden_door_lock",
    )
    assert await hass.config_entries.async_setup(mock_entry.entry_id)
    await hass.async_block_till_done()

    entity_id = _entity(hass, "binary_sensor", f"{GARDEN_DOOR}-lock")
    assert hass.states.get(entity_id).state == STATE_UNKNOWN  # provided, no value yet

    mock_connection.feed(CENTRAL_STATES, "1,1,1,1,8")
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == STATE_OFF

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
    ("value", "position", "unlocked"),
    [
        (0, None, None),
        (None, None, None),
        (1, "closed", None),
        (2, "tilted", True),
        (4, "open", True),
        (8, "closed", False),
        (16, "closed", True),
        (9, "closed", False),
        (17, "closed", True),
        (32, None, None),
    ],
)
def test_window_value_decoding(value, position, unlocked):
    assert window_position(value) == position
    assert window_unlocked(value) == unlocked
