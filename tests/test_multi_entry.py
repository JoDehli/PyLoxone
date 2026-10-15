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


class _Bus:
    def __init__(self):
        self.listeners: dict[str, list] = {}
        self.removed: list[str] = []

    def async_listen_once(self, event_type, listener):
        self.listeners.setdefault(event_type, []).append(listener)

        def unsub():
            self.removed.append(event_type)

        return unsub


class _Entry:
    def __init__(self):
        self.on_unload: list = []

    def async_on_unload(self, func):
        self.on_unload.append(func)

    def unload(self):
        for func in self.on_unload:
            func()


def test_pending_listen_once_is_removed_on_unload():
    from custom_components.loxone import _async_listen_once_until_unload

    hass = SimpleNamespace(bus=_Bus())
    entry = _Entry()

    async def stop_event(_event):
        raise AssertionError("must not run")

    _async_listen_once_until_unload(hass, entry, "homeassistant_stop", stop_event)
    entry.unload()

    assert hass.bus.removed == ["homeassistant_stop"]


def test_fired_listen_once_is_not_removed_again():
    """HA logs an exception for the unsubscribe of an already fired
    ``listen_once``; the helper must skip it.
    """
    from custom_components.loxone import _async_listen_once_until_unload

    hass = SimpleNamespace(bus=_Bus())
    entry = _Entry()
    calls = []

    async def started(event):
        calls.append(event)

    _async_listen_once_until_unload(hass, entry, "homeassistant_started", started)
    asyncio.run(hass.bus.listeners["homeassistant_started"][0]("evt"))
    entry.unload()

    assert calls == ["evt"]
    assert hass.bus.removed == []


def test_options_change_reloads_but_token_update_does_not():
    from custom_components.loxone import _reload_on_options_change

    entry = SimpleNamespace(
        entry_id="a", title="PyLoxone", options={"host": "10.0.0.1"}, data={}
    )
    reloads = []
    hass = SimpleNamespace(
        config_entries=SimpleNamespace(async_schedule_reload=reloads.append)
    )
    listener = _reload_on_options_change(entry)

    # Token refresh: only ``data`` changes.
    entry.data = {"token": "new"}
    asyncio.run(listener(hass, entry))
    assert reloads == []

    # Options flow: host changed.
    entry.options = {"host": "10.0.0.2"}
    asyncio.run(listener(hass, entry))
    assert reloads == ["a"]


def _loaded_coordinator(entry_id: str, title: str, project: str):
    miniserver = SimpleNamespace(
        serial=f"SN-{entry_id}",
        software_version=[15, 0],
        lox_config=SimpleNamespace(
            json={
                "msInfo": {
                    "projectName": project,
                    "localUrl": "local",
                    "remoteUrl": "remote",
                }
            }
        ),
    )
    return SimpleNamespace(
        config_entry=SimpleNamespace(entry_id=entry_id, title=title),
        miniserver=miniserver,
    )


def test_diagnostics_returns_the_requested_entry():
    from custom_components.loxone.diagnostics import \
        async_get_config_entry_diagnostics

    co_a = _loaded_coordinator("a", "A", "House A")
    co_b = _loaded_coordinator("b", "B", "House B")
    hass = SimpleNamespace(data={DOMAIN: {"a": co_a, "b": co_b}})

    result = asyncio.run(
        async_get_config_entry_diagnostics(hass, SimpleNamespace(entry_id="b"))
    )
    assert result["LoxAPP3.json"]["msInfo"]["projectName"] == "House B"

    missing = asyncio.run(
        async_get_config_entry_diagnostics(hass, SimpleNamespace(entry_id="x"))
    )
    assert "error" in missing


def test_system_health_lists_every_miniserver():
    from custom_components.loxone.system_health import system_health_info

    one = SimpleNamespace(data={DOMAIN: {"a": _loaded_coordinator("a", "A", "House A")}})
    assert asyncio.run(system_health_info(one))["Project Name"] == "House A"

    two = SimpleNamespace(
        data={
            DOMAIN: {
                "a": _loaded_coordinator("a", "A", "House A"),
                "b": _loaded_coordinator("b", "B", "House B"),
            }
        }
    )
    info = asyncio.run(system_health_info(two))
    assert info["Project Name (A)"] == "House A"
    assert info["Project Name (B)"] == "House B"

    none_loaded = SimpleNamespace(data={DOMAIN: {}})
    assert asyncio.run(system_health_info(none_loaded))["Project Name"] == "Unavailable"
