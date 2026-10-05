"""Shared fixtures for the PyLoxone test suite.

Three fixtures let a test set up the real integration inside the Home
Assistant test harness (``pytest-homeassistant-custom-component``) without a
Miniserver:

* ``loxapp3``          -- the synthetic structure file ``tests/fixtures/LoxAPP3.json``
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
import gc
import json
import traceback
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="session")
def loxapp3() -> dict:
    """The static LoxAPP3.json fixture (the shape of ``api.structure_file``)."""
    return json.loads((FIXTURES_DIR / "LoxAPP3.json").read_text())


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
    open; ``start_listening()`` stays "connected" until the entry is unloaded;
    the two send methods record what the integration would have sent.

    The yielded namespace offers:

    * ``feed(uuid, value)`` -- deliver one state message exactly the way the
      live listener does (the ``loxone_event`` bus event entities subscribe to)
    * ``sent`` -- list of ``{"uuid", "value", "code"}`` dicts, one per command
    """
    from custom_components.loxone.const import EVENT
    from custom_components.loxone.pyloxone_api.connection import LoxoneConnection

    namespace = SimpleNamespace(sent=[], sessions=[])

    async def _fake_open(self, session=None):
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

    async def _fake_listen(self, callback=None):
        # A live session: stays up until close() (entry unload) ends it.
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
        patch.object(LoxoneConnection, "start_listening", new=_fake_listen),
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


# Entity event handlers that raise KeyError on *every* state message because
# they index a state key their control does not have.  The harness turns any
# unhandled task exception into a test error, so a test that pushes a state
# message needs ``known_handler_errors`` until these are fixed:
#   switch.py  LoxoneSwitch.event_handler     states["active"]   (presence / intercom sub-controls)
#   cover.py   LoxoneWindow.event_handler     states["direction"]
#   cover.py   LoxoneJalousie.event_handler   states["shadePosition"]
KNOWN_HANDLER_ERRORS = {
    ("switch.py", "active"),
    ("cover.py", "direction"),
    ("cover.py", "shadePosition"),
}


@pytest.fixture
async def known_handler_errors(hass):
    """Swallow the KeyErrors listed in ``KNOWN_HANDLER_ERRORS`` and fail the
    test when they stop occurring (then the fixture must be dropped from it).
    Any other loop exception still reaches the harness and fails the test."""
    loop = asyncio.get_running_loop()
    harness_handler = loop.get_exception_handler()
    seen: list[tuple[str, str]] = []

    def _handler(loop_, context):
        exc = context.get("exception")
        if isinstance(exc, KeyError) and exc.args:
            frame = traceback.extract_tb(exc.__traceback__)[-1]
            key = (frame.filename.rsplit("/", 1)[-1], exc.args[0])
            if key in KNOWN_HANDLER_ERRORS:
                seen.append(key)
                return
        harness_handler(loop_, context)

    loop.set_exception_handler(_handler)
    yield seen
    # Make every finished task give up its exception before handing the
    # handler back to the harness.
    await hass.async_block_till_done()
    gc.collect()
    await asyncio.sleep(0)
    loop.set_exception_handler(harness_handler)
    assert seen, (
        "no known handler KeyError was raised: the bugs in KNOWN_HANDLER_ERRORS are fixed, "
        "remove the known_handler_errors fixture from this test"
    )
