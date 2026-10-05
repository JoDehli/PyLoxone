"""The integration sets up, creates entities, receives state and unloads.

These run the real ``custom_components.loxone`` inside the Home Assistant test
harness against the synthetic structure file; only the network side of
``LoxoneConnection`` is replaced (see ``conftest.mock_connection``).
"""

from __future__ import annotations

import asyncio
from collections import Counter

from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import entity_registry as er

# Hand-copied from tests/fixtures/LoxAPP3.json.
SWITCH_UUID = "63746c3a-0157-9766-ffff-e6720526f6f6000087"  # "Living Room Light Switch"
SWITCH_ACTIVE_STATE_UUID = "36333734-0158-9336-ffff-d303135372d3000088"  # its "active" state


async def test_entry_loads_and_unloads(hass, mock_connection, mock_entry, setup_loxone_entry):
    entry = await setup_loxone_entry(mock_entry)
    assert entry.state is ConfigEntryState.LOADED

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED


async def test_every_platform_creates_entities(hass, mock_connection, mock_entry, setup_loxone_entry):
    """One entity per fixture control type reaches the registry.

    The counts are a floor, not an exact snapshot: adding support for a
    control type the fixture already carries must not break this test.
    """
    await setup_loxone_entry(mock_entry)
    registry = er.async_get(hass)
    domains = Counter(entry.domain for entry in registry.entities.values() if entry.platform == "loxone")
    for domain in (
        "alarm_control_panel",
        "binary_sensor",
        "button",
        "climate",
        "cover",
        "fan",
        "light",
        "media_player",
        "number",
        "select",
        "sensor",
        "switch",
    ):
        assert domains[domain] >= 1, f"no {domain} entity was created; got {dict(domains)}"


async def test_state_message_updates_an_entity(
    hass, mock_connection, mock_entry, setup_loxone_entry, known_handler_errors
):
    """A value pushed on the websocket (here: the bus event the listener fires)
    becomes entity state."""
    await setup_loxone_entry(mock_entry)
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id("switch", "loxone", SWITCH_UUID)
    assert entity_id, "the fixture's Switch control did not create a switch entity"

    mock_connection.feed(SWITCH_ACTIVE_STATE_UUID, 1.0)
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == "on"

    mock_connection.feed(SWITCH_ACTIVE_STATE_UUID, 0.0)
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == "off"


async def test_service_call_sends_a_command(
    hass, mock_connection, mock_entry, setup_loxone_entry, known_handler_errors
):
    """Turning a switch on sends the Loxone ``On`` command to the control's uuid."""
    await setup_loxone_entry(mock_entry)
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id("switch", "loxone", SWITCH_UUID)

    # entities are unavailable until their first state message
    mock_connection.feed(SWITCH_ACTIVE_STATE_UUID, 0.0)
    await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == "off"

    await hass.services.async_call("switch", "turn_on", {"entity_id": entity_id}, blocking=True)
    await hass.async_block_till_done()
    # the bus listener hands the command to a bare asyncio task HA does not track
    await asyncio.sleep(0)
    await hass.async_block_till_done()

    assert {"uuid": SWITCH_UUID, "value": "On", "code": None} in mock_connection.sent


async def test_unreachable_miniserver_retries_setup(hass, mock_entry, enable_custom_integrations):
    """A connection error during setup raises ConfigEntryNotReady (HA retries)."""
    from unittest.mock import patch

    from custom_components.loxone.pyloxone_api.connection import LoxoneConnection

    async def _refuse(self, session=None):
        message = "connection refused"
        raise OSError(message)

    with patch.object(LoxoneConnection, "open", new=_refuse):
        mock_entry.add_to_hass(hass)
        await hass.config_entries.async_setup(mock_entry.entry_id)
        await hass.async_block_till_done()

    assert mock_entry.state is ConfigEntryState.SETUP_RETRY
