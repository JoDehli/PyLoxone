"""Tests for running more than one Miniserver (several config entries).

- commands are routed to the Miniserver that owns the control uuid;
- unloading one entry keeps the shared services for the others;
- entity bus listeners are unsubscribed when the entity is removed.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.loxone import (LoxoneEntity, _coordinator_for_uuid,
                                      _resolve_command_target,
                                      async_unload_entry)
from custom_components.loxone.const import DOMAIN
from custom_components.loxone.coordinator import (LoxoneCoordinator,
                                                  _collect_control_uuids)


def _coordinator(entry_id: str, controls: dict) -> LoxoneCoordinator:
    co = LoxoneCoordinator.__new__(LoxoneCoordinator)
    co.config_entry = SimpleNamespace(entry_id=entry_id)
    co._control_uuids = _collect_control_uuids({"controls": controls})
    co.api = SimpleNamespace(send_websocket_command=AsyncMock())
    return co


def _hass(*coordinators):
    return SimpleNamespace(
        data={DOMAIN: {co.config_entry.entry_id: co for co in coordinators}}
    )


def test_collect_control_uuids_includes_subcontrols():
    uuids = _collect_control_uuids(
        {
            "controls": {
                "ctrl-a": {
                    "uuidAction": "ctrl-a",
                    "subControls": {"sub-a1": {"uuidAction": "sub-a1"}},
                },
                "ctrl-b": {"uuidAction": "ctrl-b"},
            }
        }
    )
    assert uuids == {"ctrl-a", "sub-a1", "ctrl-b"}


def test_single_miniserver_gets_every_uuid():
    """With one entry the routing is unchanged, also for unknown uuids."""
    co = _coordinator("a", {"ctrl-a": {}})
    hass = _hass(co)
    assert _coordinator_for_uuid(hass, "ctrl-a") is co
    assert _coordinator_for_uuid(hass, "not-in-structure") is co


def test_uuid_is_routed_to_owning_miniserver():
    co_a = _coordinator("a", {"ctrl-a": {}})
    co_b = _coordinator("b", {"ctrl-b": {"subControls": {"sub-b": {}}}})
    hass = _hass(co_a, co_b)

    assert _coordinator_for_uuid(hass, "ctrl-a") is co_a
    assert _coordinator_for_uuid(hass, "ctrl-b") is co_b
    assert _coordinator_for_uuid(hass, "sub-b") is co_b
    assert _coordinator_for_uuid(hass, "unknown") is None


def test_service_with_unknown_uuid_raises_on_multiple_miniservers():
    hass = _hass(
        _coordinator("a", {"ctrl-a": {}}), _coordinator("b", {"ctrl-b": {}})
    )
    call = SimpleNamespace(data={"uuid": "unknown", "value": "on"})
    with pytest.raises(HomeAssistantError):
        _resolve_command_target(hass, call)


def test_unload_keeps_shared_services():
    """Unloading one entry must not remove the services of the others."""
    removed = []

    async def _scenario():
        co = SimpleNamespace(
            config_entry=SimpleNamespace(entry_id="a"),
            listeners=[],
            api=SimpleNamespace(close=AsyncMock()),
            _listening_task=None,
            async_cleanup=AsyncMock(),
        )

        class _ConfigEntries:
            async def async_unload_platforms(self, entry, platforms):
                return True

        hass = SimpleNamespace(
            data={DOMAIN: {"a": co}},
            services=SimpleNamespace(
                async_remove=lambda domain, service: removed.append(service)
            ),
            config_entries=_ConfigEntries(),
        )
        assert await async_unload_entry(hass, co.config_entry) is True

    asyncio.run(_scenario())
    assert removed == []


def test_entity_listener_is_removed_with_the_entity():
    unsubscribed = []

    def _unsub():
        unsubscribed.append(True)

    entity = LoxoneEntity.__new__(LoxoneEntity)
    on_remove = []
    entity.async_on_remove = on_remove.append
    entity.hass = SimpleNamespace(
        bus=SimpleNamespace(async_listen=lambda event, handler: _unsub)
    )

    asyncio.run(entity.async_added_to_hass())

    assert on_remove == [_unsub]
    on_remove[0]()
    assert unsubscribed == [True]
