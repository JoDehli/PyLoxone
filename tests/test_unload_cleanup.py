"""Tests for Loxone unload cleanup error visibility.

Covers the ``except Exception: pass`` removal in
``async_unload_entry`` / ``LoxoneCoordinator.async_cleanup``:

- one failing listener must not block the rest or ``api.close()``,
  and must leave a WARNING with traceback;
- unload must cancel the supervisor task before closing the API
  (the task may sit in backoff sleep, which ``close()`` alone
  would not interrupt);
- a normal cancellation must not log at ERROR.
"""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

from custom_components.loxone import async_unload_entry
from custom_components.loxone.const import DOMAIN
from custom_components.loxone.coordinator import LoxoneCoordinator


def _make_hass(coordinator, entry_id="test-entry"):
    removed = []

    class _Services:
        def async_remove(self, domain, service):
            removed.append((domain, service))

    class _ConfigEntries:
        async def async_unload_platforms(self, entry, platforms):
            return True

    hass = SimpleNamespace(
        data={DOMAIN: {entry_id: coordinator}},
        services=_Services(),
        config_entries=_ConfigEntries(),
    )
    return hass, removed


def test_cleanup_continues_after_failing_listener(caplog):
    """A raising listener is logged, others still run, api closes."""
    calls: list[str] = []

    def _ok1():
        calls.append("ok1")

    def _bad():
        calls.append("bad")
        raise RuntimeError("boom-unsubscribe")

    def _ok2():
        calls.append("ok2")

    api = SimpleNamespace(close=AsyncMock())
    fake_self = SimpleNamespace(listeners=[_ok1, _bad, _ok2], api=api)

    with caplog.at_level(logging.WARNING):
        asyncio.run(LoxoneCoordinator.async_cleanup(fake_self))

    assert calls == ["ok1", "bad", "ok2"]
    assert fake_self.listeners == []
    api.close.assert_awaited_once()
    warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("Failed to unsubscribe" in r.getMessage() for r in warnings)
    assert any(r.exc_info is not None for r in warnings)


def test_unload_cancels_task_before_close():
    """Supervisor task is cancelled before ``api.close()`` runs."""
    order: list[str] = []

    async def _scenario():
        async def _sleeper():
            await asyncio.sleep(3600)

        task = asyncio.create_task(_sleeper())

        async def _close():
            order.append("close")
            # Cancel already requested by unload before cleanup runs.
            assert task.cancelled() or task.done() or task.cancelling()

        api = SimpleNamespace(close=_close)
        entry = SimpleNamespace(entry_id="test-entry")
        coordinator = SimpleNamespace(
            config_entry=entry,
            listeners=[],
            api=api,
            _listening_task=task,
        )

        async def _cleanup():
            await LoxoneCoordinator.async_cleanup(coordinator)

        coordinator.async_cleanup = _cleanup
        hass, _ = _make_hass(coordinator)

        result = await async_unload_entry(hass, entry)

        assert result is True
        assert order == ["close"]
        assert task.done()
        assert coordinator._listening_task is None
        assert hass.data[DOMAIN] == {}

    asyncio.run(_scenario())


def test_unload_cancel_does_not_log_error(caplog):
    """Cancelling a live supervisor task stays at DEBUG, not ERROR."""
    api = SimpleNamespace(close=AsyncMock())
    entry = SimpleNamespace(entry_id="test-entry")

    async def _scenario():
        async def _sleeper():
            await asyncio.sleep(3600)

        coordinator = SimpleNamespace(
            config_entry=entry,
            listeners=[],
            api=api,
            _listening_task=asyncio.create_task(_sleeper()),
        )

        async def _cleanup():
            await LoxoneCoordinator.async_cleanup(coordinator)

        coordinator.async_cleanup = _cleanup
        hass, _ = _make_hass(coordinator)
        with caplog.at_level(logging.DEBUG):
            result = await async_unload_entry(hass, entry)
        assert result is True

    asyncio.run(_scenario())

    assert api.close.await_count == 1
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]
