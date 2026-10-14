"""Connection-state callback must actually refresh registry entities."""

from __future__ import annotations

import inspect
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.loxone import async_refresh_on_connection_state


async def test_connection_state_change_awaits_entity_refresh(hass):
    entry = MockConfigEntry(domain="loxone", data={})
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    registry.async_get_or_create("switch", "loxone", "uuid-1", config_entry=entry)
    coordinator = SimpleNamespace(connection_available=True)

    refresh = AsyncMock()
    with patch("homeassistant.helpers.entity_component.async_update_entity", refresh):
        result = async_refresh_on_connection_state(hass, entry, coordinator, "disconnected")
        if inspect.isawaitable(result):
            await result

    assert coordinator.connection_available is False
    refresh.assert_awaited_once()
