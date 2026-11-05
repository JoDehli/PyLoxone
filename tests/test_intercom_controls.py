"""Real-platform Intercom state, actions, discovery and lifecycle without hardware."""

import asyncio
from copy import deepcopy
import json
from unittest.mock import Mock

import pytest
from homeassistant.const import CONF_HOST, STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_send

from custom_components.loxone import connection_state_signal
from custom_components.loxone.compat import supports_intercom
from custom_components.loxone.const import DOMAIN
from custom_components.loxone.intercom import entities as controls
from tests.ha_test_helpers import MockConfigEntry


def structure():
    """Every state/command is synthetic, including intentionally protected outputs."""
    device = {
        "name": "Front intercom",
        "type": "IntercomV2",
        "uuidAction": "front-control",
        "room": "hall",
        "cat": "entrance",
        "details": {"deviceType": 1, "deviceUuid": "front-hardware", "serialNo": "TEST-INTERCOM"},
        "states": {name: "front-" + name for name in controls_device_states()},
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
    return {
        "front": device,
        "duplicate": deepcopy(device),
        "custom": custom,
        "trust": trust,
    }


def controls_device_states():
    return ("bell", "muted", "deviceState", "version", "address", "answers", "jLocked")


@pytest.fixture
async def setup_intercom(hass, mock_connection, mock_entry, enable_custom_integrations, monkeypatch):
    api = mock_connection
    api.structure_file["msInfo"]["serialNr"] = "MS-A"
    api.structure_file["controls"] = structure()
    api.structure_file["rooms"] = {"hall": {"name": "Hall"}}
    api.structure_file["cats"] = {"entrance": {"name": "Entrance"}}
    mock_entry.add_to_hass(hass)

    async def start():
        assert await hass.config_entries.async_setup(mock_entry.entry_id)
        await hass.async_block_till_done()
        return mock_entry, hass.data[DOMAIN][mock_entry.entry_id], api

    yield start


def entity_id(hass, entry, suffix):
    matches = [
        entity.entity_id
        for entity in er.async_get(hass).entities.values()
        if entity.config_entry_id == entry.entry_id and entity.unique_id.endswith("_" + suffix)
    ]
    assert len(matches) == 1
    return matches[0]


async def push(hass, api, **states):
    for key, value in states.items():
        api.feed("front-" + key, value)
    await hass.async_block_till_done()


async def initial_states(hass, api):
    await push(
        hass,
        api,
        bell=0.0,
        muted=0.0,
        deviceState=1.0,
        version="17.00.06.01",
        address="192.0.2.10",
        answers=json.dumps(["Please wait", "", "Leave the parcel"]),
        jLocked="",
    )


async def test_discovery_shares_hardware_with_camera_and_preserves_structure(hass, setup_intercom):
    entry, coordinator, api = await setup_intercom()
    await initial_states(hass, api)
    suffixes = ["ringing", "online", "device_state", "mute", "dismiss", "release-control_output", "reply_0", "reply_2"]
    registry = er.async_get(hass)
    registered = [registry.async_get(entity_id(hass, entry, suffix)) for suffix in suffixes]
    assert len({e.device_id for e in registered}) == 1
    device = dr.async_get(hass).async_get(registered[0].device_id)
    assert device.model == "Intercom Gen 2"
    assert device.serial_number == "TEST-INTERCOM"
    assert device.sw_version == "17.00.06.01"
    assert device.via_device_id
    if supports_intercom():
        assert registry.async_get(entity_id(hass, entry, "camera")).device_id == device.id
    else:
        assert coordinator.intercom_tokens is None
        assert not any(e.entity_id.startswith("camera.") for e in registered)
    assert registry.async_get(entity_id(hass, entry, "firmware")).disabled_by == er.RegistryEntryDisabler.INTEGRATION
    assert not any(e.unique_id.endswith("protected_output") for e in registry.entities.values())
    assert coordinator.miniserver.lox_config.json["controls"] == structure()


async def test_bell_and_mute_use_independent_feedback(hass, setup_intercom):
    entry, _, api = await setup_intercom()
    await initial_states(hass, api)
    bell, mute = entity_id(hass, entry, "ringing"), entity_id(hass, entry, "mute")
    assert hass.states.get(bell).state == STATE_OFF
    await push(hass, api, bell=1.0, muted=1.0)
    assert hass.states.get(bell).state == STATE_ON
    assert hass.states.get(mute).state == STATE_ON
    await push(hass, api, bell=0.0)
    assert hass.states.get(bell).state == STATE_OFF
    assert hass.states.get(mute).state == STATE_ON


async def test_mute_commands_wait_for_feedback_without_optimistic_state(hass, setup_intercom):
    entry, _, api = await setup_intercom()
    await initial_states(hass, api)
    mute = entity_id(hass, entry, "mute")
    await hass.services.async_call("switch", "turn_on", {"entity_id": mute}, blocking=True)
    api.send_websocket_command.assert_awaited_once_with("front-control", "mute/1")
    assert hass.states.get(mute).state == STATE_OFF
    await push(hass, api, muted=1)
    assert hass.states.get(mute).state == STATE_ON
    await hass.services.async_call("switch", "turn_off", {"entity_id": mute}, blocking=True)
    assert api.send_websocket_command.await_args.args == ("front-control", "mute/0")
    assert hass.states.get(mute).state == STATE_ON
    await push(hass, api, muted=0)
    assert hass.states.get(mute).state == STATE_OFF


async def test_dismiss_and_outputs_send_distinct_commands_and_targets(hass, setup_intercom):
    entry, _, api = await setup_intercom()
    await initial_states(hass, api)
    await hass.services.async_call("button", "press", {"entity_id": entity_id(hass, entry, "dismiss")}, blocking=True)
    api.send_websocket_command.assert_awaited_once_with("front-control", "answer")
    await hass.services.async_call(
        "button", "press", {"entity_id": entity_id(hass, entry, "release-control_output")}, blocking=True
    )
    assert api.send_websocket_command.await_args.args == ("release-control", "pulse")
    api.send_secured_websocket_command.assert_not_awaited()


async def test_voice_presets_discover_update_and_keep_original_indexes(hass, setup_intercom):
    entry, _, api = await setup_intercom()
    await initial_states(hass, api)
    first, third = entity_id(hass, entry, "reply_0"), entity_id(hass, entry, "reply_2")
    assert hass.states.get(third).attributes["message"] == "Leave the parcel"
    await hass.services.async_call("button", "press", {"entity_id": third}, blocking=True)
    api.send_websocket_command.assert_awaited_once_with("front-control", "playTts/2")
    await push(hass, api, answers=json.dumps(["Updated reply", "New reply"]))
    second = entity_id(hass, entry, "reply_1")
    assert hass.states.get(first).attributes["message"] == "Updated reply"
    assert hass.states.get(second).attributes["message"] == "New reply"
    assert hass.states.get(third).state == STATE_UNAVAILABLE
    count = len(er.async_get(hass).entities)
    await push(hass, api, answers=json.dumps(["Updated reply", "New reply"]))
    assert len(er.async_get(hass).entities) == count
    await push(hass, api, answers=json.dumps(["Updated reply", "New reply", "Restored"]))
    assert entity_id(hass, entry, "reply_2") == third
    assert hass.states.get(third).state != STATE_UNAVAILABLE


@pytest.mark.parametrize(("value", "expected"), [(0, "unknown"), (1, "online"), (2, "rebooting"), (3, "initializing")])
async def test_status_keeps_offline_and_initializing_distinct(hass, setup_intercom, value, expected):
    entry, _, api = await setup_intercom()
    await initial_states(hass, api)
    await push(hass, api, deviceState=value)
    assert hass.states.get(entity_id(hass, entry, "device_state")).state == expected
    assert hass.states.get(entity_id(hass, entry, "online")).state == (STATE_ON if value == 1 else STATE_OFF)


async def test_malformed_states_do_not_ring_or_enable_control(hass, setup_intercom):
    entry, _, api = await setup_intercom()
    await initial_states(hass, api)
    await push(hass, api, bell=2, muted="invalid", deviceState=True, answers="not-json", jLocked="not-json")
    for key in ("ringing", "mute", "reply_0", "reply_2", "online"):
        assert hass.states.get(entity_id(hass, entry, key)).state == STATE_UNAVAILABLE
    assert hass.states.get(entity_id(hass, entry, "device_state")).state == "unknown"
    api.send_websocket_command.assert_not_awaited()


async def test_locked_controls_cannot_send_commands(hass, setup_intercom):
    entry, _, api = await setup_intercom()
    await initial_states(hass, api)
    mute = hass.data["switch"].get_entity(entity_id(hass, entry, "mute"))
    await push(hass, api, jLocked=json.dumps({"locked": 1, "reason": "Test lock"}))
    assert not mute.available
    with pytest.raises(HomeAssistantError, match="unavailable or locked"):
        await mute.async_turn_on()
    api.send_websocket_command.assert_not_awaited()
    await push(hass, api, jLocked="")
    assert mute.available


async def test_transport_error_is_safe_and_command_is_not_retried(hass, setup_intercom, caplog):
    entry, _, api = await setup_intercom()
    await initial_states(hass, api)
    api.send_websocket_command.side_effect = ValueError("private-password-and-response")
    mute = hass.data["switch"].get_entity(entity_id(hass, entry, "mute"))
    with pytest.raises(HomeAssistantError, match="Could not send the Intercom command") as error:
        await mute.async_turn_on()
    assert "private-password" not in str(error.value)
    assert "private-password" not in caplog.text
    assert api.send_websocket_command.await_count == 1


async def test_stalled_command_has_a_deadline(hass, setup_intercom, monkeypatch):
    entry, _, api = await setup_intercom()
    await initial_states(hass, api)

    async def stalled(*args):
        await asyncio.Future()

    api.send_websocket_command.side_effect = stalled
    monkeypatch.setattr(controls, "COMMAND_TIMEOUT", 0.01)
    mute = hass.data["switch"].get_entity(entity_id(hass, entry, "mute"))
    with pytest.raises(HomeAssistantError, match="Could not send the Intercom command"):
        await asyncio.wait_for(mute.async_turn_on(), 1)
    assert api.send_websocket_command.await_count == 1


async def test_disconnect_clears_feedback_and_reload_removes_old_listeners(hass, setup_intercom):
    entry, coordinator, api = await setup_intercom()
    await initial_states(hass, api)
    mute_id = entity_id(hass, entry, "mute")
    old = hass.data["switch"].get_entity(mute_id)
    original_device = er.async_get(hass).async_get(mute_id).device_id
    coordinator.connection_available = False
    coordinator.intercom_state_values.clear()
    async_dispatcher_send(hass, connection_state_signal(entry.entry_id))
    await hass.async_block_till_done()
    assert hass.states.get(mute_id).state == STATE_UNAVAILABLE
    coordinator.connection_available = True
    async_dispatcher_send(hass, connection_state_signal(entry.entry_id))
    await hass.async_block_till_done()
    assert hass.states.get(mute_id).state == STATE_UNAVAILABLE
    await initial_states(hass, api)
    assert hass.states.get(mute_id).state == STATE_OFF
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    writer = old.async_write_ha_state = Mock()
    await initial_states(hass, api)
    writer.assert_not_called()
    assert entity_id(hass, entry, "mute") == mute_id
    assert er.async_get(hass).async_get(mute_id).device_id == original_device
    assert len([e for e in er.async_get(hass).entities.values() if e.unique_id.endswith("_reply_0")]) == 1


async def test_identical_control_uuids_route_to_the_owning_miniserver(hass, setup_intercom, monkeypatch):
    from custom_components.loxone import coordinator as coordinator_module

    entry_a, _, api_a = await setup_intercom()
    await initial_states(hass, api_a)
    api_b = type(api_a)()
    api_b.structure_file = deepcopy(api_a.structure_file)
    api_b.structure_file["msInfo"]["serialNr"] = "MS-B"
    monkeypatch.setattr(coordinator_module, "LoxoneConnection", lambda **kwargs: api_b)
    entry_b = MockConfigEntry(
        domain=DOMAIN,
        title="Second Miniserver",
        unique_id="MS-B",
        version=4,
        options={**entry_a.options, CONF_HOST: "192.0.2.2"},
        data={},
    )
    entry_b.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry_b.entry_id)
    await hass.async_block_till_done()
    await initial_states(hass, api_b)
    mute_a, mute_b = entity_id(hass, entry_a, "mute"), entity_id(hass, entry_b, "mute")
    assert mute_a != mute_b
    await hass.services.async_call("switch", "turn_on", {"entity_id": mute_b}, blocking=True)
    api_b.send_websocket_command.assert_awaited_once_with("front-control", "mute/1")
    api_a.send_websocket_command.assert_not_awaited()
    await push(hass, api_b, muted=1)
    assert hass.states.get(mute_a).state == STATE_OFF
    assert hass.states.get(mute_b).state == STATE_ON


@pytest.mark.parametrize(
    "payload",
    [None, {}, "not-json", "[" * 1100 + "0" + "]" * 1100, " " * 65537, '["One",null,"Three"]', ["One", "", "Three"]],
    ids=["missing", "object", "invalid-json", "nested", "oversized", "nullable-slots", "empty-slots"],
)
def test_voice_reply_parser_keeps_indexes_without_evaluating_code(payload):
    result = controls.voice_replies(payload)
    assert result == (["One", "", "Three"] if isinstance(payload, list) or payload == '["One",null,"Three"]' else [])


def test_voice_reply_discovery_is_bounded():
    assert len(controls.voice_replies(["Reply"] * 1000)) == controls.MAX_REPLIES


async def test_secured_parent_exposes_feedback_without_unsecured_actors(hass, setup_intercom, mock_connection):
    mock_connection.structure_file["controls"]["front"]["isSecured"] = True
    entry, _, api = await setup_intercom()
    await initial_states(hass, api)
    assert hass.states.get(entity_id(hass, entry, "ringing")).state == STATE_OFF
    assert not any(
        entity.domain in {"switch", "button"}
        for entity in er.async_get(hass).entities.values()
        if entity.config_entry_id == entry.entry_id
    )
    api.send_websocket_command.assert_not_awaited()
