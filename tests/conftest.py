"""Shared fixtures for the legacy and official HA test plugins.

Re-root custom integration imports at this checkout. Each hass instance uses
an empty integration device cache and synthetic Miniserver configuration.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import asyncio
from copy import deepcopy
import json
from unittest.mock import AsyncMock

from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME

from tests.ha_test_helpers import MockConfigEntry

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def enable_custom_integrations(hass):
    """Re-points ``custom_components`` at the repo's ``custom_components/`` and
    clears the loader integration cache.
    """
    import custom_components

    from homeassistant import loader
    from custom_components.loxone import helpers

    original = list(custom_components.__path__)
    custom_components.__path__ = [str(REPO_ROOT / "custom_components")]
    hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
    # Every hass fixture models a new HA process; unit tests must not leave
    # the integration's module-level device cache in that new instance.
    helpers.device_registry.clear()
    yield
    helpers.device_registry.clear()
    custom_components.__path__ = original


@pytest.fixture
def mock_entry():
    """Normal entry configuration without any real Miniserver credentials."""
    return MockConfigEntry(
        domain="loxone",
        title="Test Miniserver",
        unique_id="TEST-SERIAL-0001",
        version=4,
        data={},
        options={
            CONF_HOST: "192.0.2.1",
            CONF_PORT: 80,
            CONF_USERNAME: "test-user",
            CONF_PASSWORD: "test-password",
            "verify_ssl": True,
            "generate_scenes": False,
            "generate_scenes_delay": 3,
            "generate_lightcontroller_subcontrols": False,
        },
    )


@pytest.fixture
async def mock_connection(hass, monkeypatch):
    """Drive the real integration using only a synthetic structure and events."""
    from custom_components.loxone import coordinator

    structure = json.loads((REPO_ROOT / "tests/fixtures/LoxAPP3.json").read_text())

    class Connection:
        connection = None
        is_connected = True

        def __init__(self):
            self.structure_file = deepcopy(structure)
            self.open = AsyncMock()
            self.close = AsyncMock()
            self.kill_token = AsyncMock()
            self.send_websocket_command = AsyncMock()
            self.send_secured_websocket_command = AsyncMock()
            self.callback = None

        async def run(self, *, on_state, callback):
            self.callback = callback
            on_state("connected")
            await asyncio.Event().wait()

        def get_token_dict(self):
            return {"token": "test-app-token", "valid_until": 999999999, "hash_alg": "SHA256"}

        def feed(self, uuid, value):
            assert self.callback is not None
            hass.async_create_task(self.callback({uuid: value}))

    api = Connection()
    monkeypatch.setattr(coordinator, "LoxoneConnection", lambda **kwargs: api)
    yield api
    for entry in hass.config_entries.async_entries("loxone"):
        if entry.entry_id in hass.data.get("loxone", {}):
            await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
