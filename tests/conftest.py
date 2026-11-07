"""Shared fixtures for the PyLoxone test suite.

Three fixtures let a test set up the real integration inside the Home
Assistant test harness (``pytest-homeassistant-custom-component``) without a
Miniserver:

* ``loxapp3``          -- the synthetic structure file ``tests/fixtures/LoxAPP3_harness.json``
                          (40 controls covering every type the platforms handle)
* ``mock_connection``  -- patches ``LoxoneConnection`` so that ``open()`` seeds
                          that structure file instead of talking to the network,
                          records every outbound command, and lets a test push a
                          state message to the entities with ``feed(uuid, value)``
* ``mock_entry``       -- a config entry shaped like a real one (version 4,
                          connection settings in ``options``)

``enable_custom_integrations`` is re-defined here so that ``custom_components``
resolves to this repository's folder (the harness's own copy of the fixture
points it at the harness's testing config, which would make
``custom_components.loxone`` un-importable).
"""

from __future__ import annotations

import asyncio
import copy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def loxapp3() -> dict:
    """The synthetic structure file (the shape of ``api.structure_file``)."""
    return json.loads((FIXTURES_DIR / "LoxAPP3_harness.json").read_text())


@pytest.fixture
def enable_custom_integrations(hass):
    """Point ``custom_components`` at this repository and clear the loader cache."""
    import custom_components
    from homeassistant import loader

    original = list(custom_components.__path__)
    custom_components.__path__ = [str(REPO_ROOT / "custom_components")]
    hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
    yield
    custom_components.__path__ = original


@pytest.fixture
def mock_connection(hass, loxapp3, enable_custom_integrations):
    """Replace the network side of ``LoxoneConnection``.

    ``open()`` seeds ``structure_file`` from the fixture and marks the socket
    open; ``run()`` reports "connected" until the entry is unloaded;
    the two send methods record what the integration would have sent.

    The yielded namespace offers:

    * ``feed(uuid, value)`` -- deliver one state message exactly the way the
      live listener does (the ``loxone_event`` bus event entities subscribe to)
    * ``sent`` -- list of ``{"uuid", "value", "code"}`` dicts, one per command
    """
    from custom_components.loxone import helpers
    from custom_components.loxone.const import EVENT
    from custom_components.loxone.pyloxone_api.connection import LoxoneConnection

    # Devices are cached per uuid in a module-level dict in ``helpers``; a
    # previous test would otherwise decide this test's device model.
    helpers.device_registry.clear()

    namespace = SimpleNamespace(sent=[], sessions=[])

    async def _fake_open(self, session=None, *, connect_websocket=True):
        # A copy per connection: platform setup mutates the structure it is
        # given, and the session-scoped fixture must stay pristine between tests.
        self.structure_file = copy.deepcopy(loxapp3)
        self.miniserver_version = loxapp3.get("softwareVersion")
        self.connection = Mock()
        self.connection.protocol.state.name = "OPEN"
        self._session_key = b"\x00" * 32
        self._fake_closed = asyncio.Event()
        namespace.sessions.append(self._fake_closed)
        return self.connection

    async def _fake_run(self, on_state=None, callback=None, **kwargs):
        # The supervisor: report "connected", then stay up until close()
        # (entry unload) ends the session.
        if on_state is not None:
            on_state("connected")
        await self._fake_closed.wait()

    async def _fake_close(self, *args, **kwargs):
        self.connection = None
        if getattr(self, "_fake_closed", None) is not None:
            self._fake_closed.set()

    async def _fake_send(self, entity_uuid, value, *args, **kwargs):
        namespace.sent.append({"uuid": entity_uuid, "value": value, "code": None})

    async def _fake_send_secured(self, entity_uuid, value, code, *args, **kwargs):
        namespace.sent.append({"uuid": entity_uuid, "value": value, "code": code})

    def feed(uuid: str, value) -> None:
        hass.bus.async_fire(EVENT, {uuid: value})

    namespace.feed = feed

    with (
        patch.object(LoxoneConnection, "open", new=_fake_open),
        patch.object(LoxoneConnection, "run", new=_fake_run),
        patch.object(LoxoneConnection, "close", new=_fake_close),
        patch.object(LoxoneConnection, "send_websocket_command", new=_fake_send),
        patch.object(LoxoneConnection, "send_secured__websocket_command", new=_fake_send_secured),
    ):
        yield namespace
        # End any session a test left running so no listener task lingers.
        for session in namespace.sessions:
            session.set()
        await_pending = [s for s in namespace.sessions if not s.is_set()]
        assert not await_pending


@pytest.fixture
def mock_entry() -> MockConfigEntry:
    """A config entry as the current config flow creates it.

    ``generate_scenes`` is off because scene generation starts a delayed timer
    that would outlive the test's event loop; a test that needs scenes enables
    it explicitly.
    """
    return MockConfigEntry(
        domain="loxone",
        version=4,
        data={},
        options={
            "host": "miniserver.test",
            "port": 8080,
            "username": "admin",
            "password": "secret",
            "verify_ssl": True,
            "generate_scenes": False,
            "generate_scenes_delay": 3,
            "generate_lightcontroller_subcontrols": False,
        },
        unique_id="TEST-SERIAL-0001",
    )


@pytest.fixture
def setup_loxone_entry(hass):
    """Coroutine fixture: ``await setup_loxone_entry(entry)`` adds ``entry`` to
    ``hass``, sets it up and waits for the platforms."""

    async def _setup(entry: MockConfigEntry) -> MockConfigEntry:
        entry.add_to_hass(hass)
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        return entry

    return _setup
