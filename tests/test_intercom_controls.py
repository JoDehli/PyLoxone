"""Intercom Gen 2 (``IntercomV2``) sensors and controls (#466).

Runs the real platforms on a synthetic structure file; no hardware. The
states, commands and ``deviceState`` values follow the structure file
documentation (IntercomV2); ``version`` and ``jLocked`` are states seen
on a real device. Ported from PR #542 by jpulik.
"""

from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from unittest.mock import Mock

import pytest
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_send
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.loxone import connection_state_signal
from custom_components.loxone.const import DOMAIN
from custom_components.loxone.intercom import entities as controls

STATE_NAMES = ("bell", "muted", "deviceState", "version", "address", "answers", "jLocked")


def intercom_controls() -> dict:
    """One native Intercom plus the variants that must be left out."""
    device = {
        "name": "Front intercom",
        "type": "IntercomV2",
        "uuidAction": "front-control",
        "room": "hall",
        "cat": "entrance",
        "details": {"deviceType": 1, "deviceUuid": "front-hardware", "serialNo": "TEST-INTERCOM"},
        "states": {name: "front-" + name for name in STATE_NAMES},
        "subControls": {
            "release": {"type": "Pushbutton", "name": "Door release", "uuidAction": "release-control"},
            "duplicate": {"type": "IntercomSubControl", "name": "Duplicate", "uuidAction": "release-control"},
            "protected": {
                "type": "Pushbutton",
                "name": "Protected release",
                "uuidAction": "protected",
                "isSecured": True,
            },
            "other": {"type": "Switch", "name": "Unrelated switch", "uuidAction": "unrelated"},
        },
    }
    custom = deepcopy(device)
    custom["details"] = {"deviceType": 0, "deviceUuid": "custom"}
    trust = deepcopy(device)
    trust["details"] = {"deviceType": 1, "deviceUuid": "trust", "trustAddress": "remote.example"}
    return {"front": device, "duplicate": deepcopy(device), "custom": custom, "trust": trust}


@pytest.fixture
def loxapp3(request) -> dict:
    """The harness structure file with only the synthetic Intercom controls."""
    from tests.conftest import FIXTURES_DIR

    structure = json.loads((FIXTURES_DIR / "LoxAPP3_harness.json").read_text())
    structure.setdefault("msInfo", {})["serialNr"] = "MS-A"
    structure["controls"] = intercom_controls()
    structure["rooms"] = {"hall": {"name": "Hall"}}
    structure["cats"] = {"entrance": {"name": "Entrance"}}
    return structure


@pytest.fixture
async def intercom(hass, mock_connection, mock_entry, setup_loxone_entry):
    await setup_loxone_entry(mock_entry)
    return mock_entry, hass.data[DOMAIN][mock_entry.entry_id]


def entity_id(hass, entry, suffix):
    matches = [
        entity.entity_id
        for entity in er.async_get(hass).entities.values()
        if entity.config_entry_id == entry.entry_id and entity.unique_id.endswith("_" + suffix)
    ]
    assert len(matches) == 1, f"{suffix}: {matches}"
    return matches[0]


async def push(hass, coordinator, **states):
    """Deliver states through the integration's real message callback."""
    for key, value in states.items():
        await coordinator.api._fake_callback({"front-" + key: value})
    await hass.async_block_till_done()


async def initial_states(hass, coordinator):
    await push(
        hass,
        coordinator,
        bell=0.0,
        muted=0.0,
        deviceState=1.0,
        version="17.00.06.01",
        address="192.0.2.10",
        answers=json.dumps(["Please wait", "", "Leave the parcel"]),
        jLocked="",
    )


def sent(mock_connection):
    return [(command["uuid"], command["value"]) for command in mock_connection.sent]


async def test_discovery_groups_entities_on_one_device(hass, intercom):
    entry, coordinator = intercom
    await initial_states(hass, coordinator)
    suffixes = ["ringing", "online", "device_state", "mute", "dismiss", "release-control_output", "reply_0", "reply_2"]
    registry = er.async_get(hass)
    registered = [registry.async_get(entity_id(hass, entry, suffix)) for suffix in suffixes]
    assert len({e.device_id for e in registered}) == 1
    device = dr.async_get(hass).async_get(registered[0].device_id)
    assert device.model == "Intercom Gen 2"
    assert device.serial_number == "TEST-INTERCOM"
    assert device.sw_version == "17.00.06.01"
    # Grouped below the Miniserver device.
    assert dr.async_get(hass).async_get(device.via_device_id).identifiers == {(DOMAIN, "MS-A")}
    assert registry.async_get(entity_id(hass, entry, "firmware")).disabled_by == er.RegistryEntryDisabler.INTEGRATION
    # No button for the secured output, the empty reply slot, the custom
    # device or the trust member's device; no camera in this stage.
    unique_ids = [e.unique_id for e in registry.entities.values() if e.config_entry_id == entry.entry_id]
    assert not any(uid.endswith("protected_output") for uid in unique_ids)
    assert not any(uid.endswith("reply_1") for uid in unique_ids)
    assert not any("custom" in uid or "trust" in uid for uid in unique_ids)
    assert not any(e.domain == "camera" for e in registry.entities.values())
    # Discovery does not change the structure file.
    assert coordinator.miniserver.lox_config.json["controls"] == intercom_controls()


async def test_reconnect_follows_changed_state_uuids(hass, intercom):
    """A structure file re-read on reconnect brings its new state uuids along."""
    _, coordinator = intercom
    assert coordinator.update_intercom_states({"front-bell": 1.0}) == {"front-bell": 1.0}
    assert coordinator.update_intercom_states({"moved-bell": 1.0}) == {}

    structure = deepcopy(coordinator.api.structure_file)
    structure["controls"]["front"]["states"]["bell"] = "moved-bell"
    coordinator.api.structure_file = structure
    assert coordinator.refresh_miniserver()

    assert coordinator.update_intercom_states({"moved-bell": 1.0}) == {"moved-bell": 1.0}


async def test_bell_and_mute_use_independent_feedback(hass, intercom):
    entry, coordinator = intercom
    await initial_states(hass, coordinator)
    bell, mute = entity_id(hass, entry, "ringing"), entity_id(hass, entry, "mute")
    assert hass.states.get(bell).state == STATE_OFF
    await push(hass, coordinator, bell=1.0, muted=1.0)
    assert hass.states.get(bell).state == STATE_ON
    assert hass.states.get(mute).state == STATE_ON
    await push(hass, coordinator, bell=0.0)
    assert hass.states.get(bell).state == STATE_OFF
    assert hass.states.get(mute).state == STATE_ON


async def test_mute_waits_for_feedback(hass, intercom, mock_connection):
    """No optimistic state: the switch follows the ``muted`` state only."""
    entry, coordinator = intercom
    await initial_states(hass, coordinator)
    mute = entity_id(hass, entry, "mute")
    await hass.services.async_call("switch", "turn_on", {"entity_id": mute}, blocking=True)
    assert sent(mock_connection) == [("front-control", "mute/1")]
    assert hass.states.get(mute).state == STATE_OFF
    await push(hass, coordinator, muted=1)
    assert hass.states.get(mute).state == STATE_ON
    await hass.services.async_call("switch", "turn_off", {"entity_id": mute}, blocking=True)
    assert sent(mock_connection)[-1] == ("front-control", "mute/0")
    assert hass.states.get(mute).state == STATE_ON
    await push(hass, coordinator, muted=0)
    assert hass.states.get(mute).state == STATE_OFF


async def test_dismiss_and_outputs_send_their_commands(hass, intercom, mock_connection):
    entry, coordinator = intercom
    await initial_states(hass, coordinator)
    await hass.services.async_call("button", "press", {"entity_id": entity_id(hass, entry, "dismiss")}, blocking=True)
    await hass.services.async_call(
        "button", "press", {"entity_id": entity_id(hass, entry, "release-control_output")}, blocking=True
    )
    assert sent(mock_connection) == [("front-control", "answer"), ("release-control", "pulse")]
    # Plain commands only, never the secured path.
    assert all(command["code"] is None for command in mock_connection.sent)


async def test_voice_replies_keep_their_slot(hass, intercom, mock_connection):
    entry, coordinator = intercom
    await initial_states(hass, coordinator)
    first, third = entity_id(hass, entry, "reply_0"), entity_id(hass, entry, "reply_2")
    assert hass.states.get(third).attributes["message"] == "Leave the parcel"
    await hass.services.async_call("button", "press", {"entity_id": third}, blocking=True)
    assert sent(mock_connection) == [("front-control", "playTts/2")]

    await push(hass, coordinator, answers=json.dumps(["Updated reply", "New reply"]))
    second = entity_id(hass, entry, "reply_1")
    assert hass.states.get(first).attributes["message"] == "Updated reply"
    assert hass.states.get(second).attributes["message"] == "New reply"
    assert hass.states.get(third).state == STATE_UNAVAILABLE

    # The same payload again creates nothing new.
    count = len(er.async_get(hass).entities)
    await push(hass, coordinator, answers=json.dumps(["Updated reply", "New reply"]))
    assert len(er.async_get(hass).entities) == count

    await push(hass, coordinator, answers=json.dumps(["Updated reply", "New reply", "Restored"]))
    assert entity_id(hass, entry, "reply_2") == third
    assert hass.states.get(third).state != STATE_UNAVAILABLE


@pytest.mark.parametrize(("value", "expected"), [(0, "unknown"), (1, "online"), (2, "rebooting"), (3, "initializing")])
async def test_device_status_values(hass, intercom, value, expected):
    entry, coordinator = intercom
    await initial_states(hass, coordinator)
    await push(hass, coordinator, deviceState=value)
    assert hass.states.get(entity_id(hass, entry, "device_state")).state == expected
    assert hass.states.get(entity_id(hass, entry, "online")).state == (STATE_ON if value == 1 else STATE_OFF)


async def test_malformed_states_do_not_ring_or_enable_control(hass, intercom, mock_connection):
    entry, coordinator = intercom
    await initial_states(hass, coordinator)
    await push(hass, coordinator, bell=2, muted="invalid", deviceState=True, answers="not-json", jLocked="not-json")
    for key in ("ringing", "mute", "reply_0", "reply_2", "online"):
        assert hass.states.get(entity_id(hass, entry, key)).state == STATE_UNAVAILABLE
    assert hass.states.get(entity_id(hass, entry, "device_state")).state == "unknown"
    assert mock_connection.sent == []


async def test_locked_controls_cannot_send_commands(hass, intercom, mock_connection):
    entry, coordinator = intercom
    await initial_states(hass, coordinator)
    mute = hass.data["switch"].get_entity(entity_id(hass, entry, "mute"))
    await push(hass, coordinator, jLocked=json.dumps({"locked": 1, "reason": "Test lock"}))
    assert not mute.available
    with pytest.raises(HomeAssistantError, match="unavailable or locked"):
        await mute.async_turn_on()
    assert mock_connection.sent == []
    await push(hass, coordinator, jLocked="")
    assert mute.available


async def test_transport_error_is_reported_without_details(hass, intercom, caplog):
    entry, coordinator = intercom
    await initial_states(hass, coordinator)
    calls = []

    async def failing(*args, **kwargs):
        calls.append(args)
        raise ValueError("private-password-and-response")

    coordinator.api.send_websocket_command = failing
    mute = hass.data["switch"].get_entity(entity_id(hass, entry, "mute"))
    with pytest.raises(HomeAssistantError, match="Could not send the Intercom command") as error:
        await mute.async_turn_on()
    assert "private-password" not in str(error.value)
    assert "private-password" not in caplog.text
    assert len(calls) == 1  # not retried


async def test_stalled_command_has_a_deadline(hass, intercom, monkeypatch):
    entry, coordinator = intercom
    await initial_states(hass, coordinator)

    async def stalled(*args, **kwargs):
        await asyncio.Future()

    coordinator.api.send_websocket_command = stalled
    monkeypatch.setattr(controls, "COMMAND_TIMEOUT", 0.01)
    mute = hass.data["switch"].get_entity(entity_id(hass, entry, "mute"))
    with pytest.raises(HomeAssistantError, match="Could not send the Intercom command"):
        await asyncio.wait_for(mute.async_turn_on(), 1)


async def test_disconnect_clears_feedback_and_reload_keeps_identity(hass, intercom):
    entry, coordinator = intercom
    await initial_states(hass, coordinator)
    mute_id = entity_id(hass, entry, "mute")
    old = hass.data["switch"].get_entity(mute_id)
    original_device = er.async_get(hass).async_get(mute_id).device_id

    coordinator.connection_available = False
    coordinator.intercom_state_values.clear()
    async_dispatcher_send(hass, connection_state_signal(entry.entry_id))
    await hass.async_block_till_done()
    assert hass.states.get(mute_id).state == STATE_UNAVAILABLE

    # Back online, but no value yet: still unavailable, not a stale "off".
    coordinator.connection_available = True
    async_dispatcher_send(hass, connection_state_signal(entry.entry_id))
    await hass.async_block_till_done()
    assert hass.states.get(mute_id).state == STATE_UNAVAILABLE
    await initial_states(hass, coordinator)
    assert hass.states.get(mute_id).state == STATE_OFF

    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    coordinator = hass.data[DOMAIN][entry.entry_id]
    writer = old.async_write_ha_state = Mock()
    await initial_states(hass, coordinator)
    writer.assert_not_called()  # the old entity no longer listens
    assert entity_id(hass, entry, "mute") == mute_id
    assert er.async_get(hass).async_get(mute_id).device_id == original_device
    assert len([e for e in er.async_get(hass).entities.values() if e.unique_id.endswith("_reply_0")]) == 1


async def test_states_reach_only_the_owning_miniserver(hass, loxapp3, intercom, mock_connection, mock_entry):
    """Two Miniservers with identical control and state uuids stay apart."""
    entry_a, coordinator_a = intercom
    await initial_states(hass, coordinator_a)
    # The second Miniserver gets the same structure with another serial.
    loxapp3["msInfo"]["serialNr"] = "MS-B"
    entry_b = MockConfigEntry(
        domain=DOMAIN,
        version=4,
        data={},
        options={**mock_entry.options, "host": "second.test"},
    )
    entry_b.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry_b.entry_id)
    await hass.async_block_till_done()
    coordinator_b = hass.data[DOMAIN][entry_b.entry_id]
    await initial_states(hass, coordinator_b)

    mute_a, mute_b = entity_id(hass, entry_a, "mute"), entity_id(hass, entry_b, "mute")
    assert mute_a != mute_b
    await push(hass, coordinator_b, muted=1)
    assert hass.states.get(mute_a).state == STATE_OFF
    assert hass.states.get(mute_b).state == STATE_ON


async def test_secured_intercom_has_feedback_but_no_actors(hass, loxapp3, mock_connection, mock_entry, setup_loxone_entry):
    loxapp3["controls"]["front"]["isSecured"] = True
    loxapp3["controls"]["duplicate"]["isSecured"] = True
    await setup_loxone_entry(mock_entry)
    coordinator = hass.data[DOMAIN][mock_entry.entry_id]
    await initial_states(hass, coordinator)
    assert hass.states.get(entity_id(hass, mock_entry, "ringing")).state == STATE_OFF
    assert not any(
        entity.domain in {"switch", "button"}
        for entity in er.async_get(hass).entities.values()
        if entity.config_entry_id == mock_entry.entry_id
    )
    assert mock_connection.sent == []


@pytest.mark.parametrize(
    "payload",
    [None, {}, "not-json", "[" * 1100 + "0" + "]" * 1100, " " * 65537, '["One",null,"Three"]', ["One", "", "Three"]],
    ids=["missing", "object", "invalid-json", "nested", "oversized", "nullable-slots", "empty-slots"],
)
def test_voice_reply_parser(payload):
    result = controls.voice_replies(payload)
    assert result == (["One", "", "Three"] if isinstance(payload, list) or payload == '["One",null,"Three"]' else [])


def test_voice_reply_discovery_is_bounded():
    assert len(controls.voice_replies(["Reply"] * 1000)) == controls.MAX_REPLIES
