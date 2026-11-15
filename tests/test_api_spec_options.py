"""Use of the pyloxone-api spec options: client identity, public key pin,
structure file cache, HTTPS status.

Needs pyloxone-api with ``client_info`` / ``structure_cache`` /
``public_key_pin`` (the spec branches).
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import issue_registry as ir

from custom_components.loxone.const import DOMAIN
from custom_components.loxone.coordinator import (
    CLIENT_INFO,
    FileStructureCache,
    _ConfigEntryTokenStore,
    cleared_token_data,
    structure_cache_path,
)
from pyloxone_api.connection import LoxoneConnection
from pyloxone_api.exceptions import LoxonePublicKeyMismatchError, LoxoneTokenError

PIN = "sha256:" + "ab" * 32
CLIENT_UUID = "0e1d2c3b-4a59-6878-ffff112233445566"
BINDING = {"url": "miniserver.test", "port": 8080, "username": "admin"}

STORED = {
    "token": "jwt",
    "valid_until": 999999999,
    "hash_alg": "SHA256",
    "unsecure_password": False,
    "binding": BINDING,
    "client_uuid": CLIENT_UUID,
    "public_key_pin": PIN,
}


# --- token store ---------------------------------------------------------------


def test_cleared_token_data_keeps_client_and_pin():
    cleared = cleared_token_data(dict(STORED))
    assert cleared["token"] == "" and cleared["valid_until"] == "" and cleared["hash_alg"] == ""
    assert "unsecure_password" not in cleared
    assert cleared["binding"] == BINDING
    assert cleared["client_uuid"] == CLIENT_UUID
    assert cleared["public_key_pin"] == PIN


def _store(data: dict):
    entry = SimpleNamespace(data=data, entry_id="e1")
    updates = []

    def update_entry(_entry, data):
        updates.append(data)
        _entry.data = data

    hass = SimpleNamespace(config_entries=SimpleNamespace(async_update_entry=update_entry))
    return _ConfigEntryTokenStore(hass, entry), entry, updates


def test_store_load_without_token_still_returns_pin_and_client():
    store, _, _ = _store(cleared_token_data(dict(STORED)))
    loaded = store.load()
    assert loaded["public_key_pin"] == PIN
    assert loaded["client_uuid"] == CLIENT_UUID


def test_store_load_empty_entry_is_none():
    store, _, _ = _store({})
    assert store.load() is None


def test_store_reset_keeps_binding_and_pin():
    store, entry, _ = _store(dict(STORED))
    store.save(None)
    assert entry.data["token"] == ""
    assert entry.data["binding"] == BINDING
    assert entry.data["public_key_pin"] == PIN


def test_library_reads_pin_and_client_after_token_reset():
    """The library sees the pin and the client uuid without a token."""
    data = cleared_token_data(dict(STORED))
    store, _, _ = _store(data)
    api = LoxoneConnection(host="miniserver.test", port=8080, username="admin", password="pw", token_store=store)
    data["binding"] = api._token_binding  # noqa: SLF001 - bind to this connection
    api = LoxoneConnection(host="miniserver.test", port=8080, username="admin", password="pw", token_store=store)
    assert api.public_key_pin == PIN
    assert api.client_uuid == CLIENT_UUID


# --- structure cache ---------------------------------------------------------


def test_file_structure_cache_roundtrip(tmp_path):
    cache = FileStructureCache(tmp_path / "sub" / "loxone.structure.e1")
    assert cache.load() is None
    cache.save({"lastModified": "2026-03-17 18:48:13", "controls": {}})
    assert cache.load() == {"lastModified": "2026-03-17 18:48:13", "controls": {}}
    assert not list(tmp_path.rglob("*.tmp"))
    cache.remove()
    assert cache.load() is None
    cache.remove()  # missing file is fine


def test_file_structure_cache_ignores_broken_file(tmp_path):
    path = tmp_path / "loxone.structure.e1"
    path.write_text("{not json")
    assert FileStructureCache(path).load() is None
    path.write_text("[1, 2]")
    assert FileStructureCache(path).load() is None


# --- integration ---------------------------------------------------------------


@pytest.fixture
def created(monkeypatch):
    """Capture the keyword arguments LoxoneConnection is created with."""
    captured: list[dict] = []
    original = LoxoneConnection.__init__

    def init(self, *args, **kwargs):
        captured.append(kwargs)
        original(self, *args, **kwargs)

    monkeypatch.setattr(LoxoneConnection, "__init__", init)
    return captured


async def test_connection_gets_client_info_and_structure_cache(
    hass, mock_connection, mock_entry, setup_loxone_entry, created
):
    await setup_loxone_entry(mock_entry)
    kwargs = created[-1]
    assert kwargs["client_info"] == CLIENT_INFO
    cache = kwargs["structure_cache"]
    assert isinstance(cache, FileStructureCache)
    assert str(cache.path) == structure_cache_path(hass, mock_entry.entry_id)


async def test_remove_entry_deletes_cached_structure(hass, mock_connection, mock_entry, setup_loxone_entry):
    await setup_loxone_entry(mock_entry)
    path = structure_cache_path(hass, mock_entry.entry_id)
    await hass.async_add_executor_job(FileStructureCache(path).save, {"lastModified": "x"})
    await hass.config_entries.async_remove(mock_entry.entry_id)
    await hass.async_block_till_done()
    assert await hass.async_add_executor_job(FileStructureCache(path).load) is None


def _issue(hass, kind: str, entry):
    return ir.async_get(hass).async_get_issue(DOMAIN, f"{kind}_{entry.entry_id}")


async def test_public_key_mismatch_stops_setup_and_offers_repair(hass, mock_connection, mock_entry, setup_loxone_entry):
    mock_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(mock_entry, data={**STORED})

    async def mismatch(self, session=None, *, connect_websocket=True):
        raise LoxonePublicKeyMismatchError("different key")

    with patch.object(LoxoneConnection, "open", new=mismatch):
        await hass.config_entries.async_setup(mock_entry.entry_id)
        await hass.async_block_till_done()

    # Final: no retry loop.
    assert mock_entry.state is ConfigEntryState.SETUP_ERROR
    issue = _issue(hass, "public_key_changed", mock_entry)
    assert issue is not None
    assert issue.is_fixable
    assert issue.severity is ir.IssueSeverity.ERROR

    # The repair flow forgets the pin (the token and the client uuid stay)
    # and reloads; this time the Miniserver answers and the issue is gone.
    from homeassistant.components.repairs import DOMAIN as REPAIRS_DOMAIN
    from homeassistant.setup import async_setup_component

    from custom_components.loxone.repairs import async_create_fix_flow

    assert await async_setup_component(hass, REPAIRS_DOMAIN, {})
    flow = await async_create_fix_flow(hass, issue.issue_id, issue.data)
    flow.hass = hass
    form = await flow.async_step_init()
    assert form["step_id"] == "confirm"
    result = await flow.async_step_confirm({})
    assert result["type"] == "create_entry"
    await hass.async_block_till_done()

    assert "public_key_pin" not in mock_entry.data
    assert mock_entry.data["client_uuid"] == CLIENT_UUID
    assert mock_entry.state is ConfigEntryState.LOADED
    assert _issue(hass, "public_key_changed", mock_entry) is None


async def test_public_key_mismatch_while_running_creates_issue_without_reload(
    hass, mock_connection, mock_entry, setup_loxone_entry
):
    async def run_mismatch(self, on_state=None, callback=None, **kwargs):
        raise LoxonePublicKeyMismatchError("different key")

    with (
        patch.object(LoxoneConnection, "run", new=run_mismatch),
        patch.object(hass.config_entries, "async_schedule_reload") as reload,
    ):
        await setup_loxone_entry(mock_entry)
        await hass.async_block_till_done()
        assert _issue(hass, "public_key_changed", mock_entry) is not None
        reload.assert_not_called()


async def test_token_error_keeps_pin_and_client(hass, mock_connection, mock_entry, setup_loxone_entry):
    mock_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(mock_entry, data={**STORED})

    async def run_token_error(self, on_state=None, callback=None, **kwargs):
        raise LoxoneTokenError("token gone")

    with (
        patch.object(LoxoneConnection, "run", new=run_token_error),
        patch.object(hass.config_entries, "async_schedule_reload"),
    ):
        await hass.config_entries.async_setup(mock_entry.entry_id)
        await hass.async_block_till_done()

    assert mock_entry.data["token"] == ""
    assert mock_entry.data["public_key_pin"] == PIN
    assert mock_entry.data["client_uuid"] == CLIENT_UUID
    assert mock_entry.data["binding"] == BINDING


@pytest.mark.parametrize(
    ("status", "scheme", "available", "expired"),
    [
        (1, "http", True, False),
        (1, "https", False, False),
        (2, "https", False, True),
        (0, "http", False, False),
        (None, "http", False, False),
    ],
)
async def test_https_issues(hass, mock_connection, mock_entry, setup_loxone_entry, status, scheme, available, expired):
    original_open = LoxoneConnection.open

    async def open_with_status(self, session=None, *, connect_websocket=True):
        result = await original_open(self, session, connect_websocket=connect_websocket)
        self.https_status = status
        self.scheme = scheme
        return result

    with (
        patch.object(LoxoneConnection, "open", new=open_with_status),
        patch.object(LoxoneConnection, "tls_hostname", new="192-168-1-20.504F94A23DB1.dyndns.loxonecloud.com"),
    ):
        await setup_loxone_entry(mock_entry)

    https = _issue(hass, "https_available", mock_entry)
    assert (https is not None) is available
    if https is not None:
        assert https.translation_placeholders["hostname"] == "192-168-1-20.504F94A23DB1.dyndns.loxonecloud.com"
    assert (_issue(hass, "certificate_expired", mock_entry) is not None) is expired


def test_translations_cover_the_issues():
    from pathlib import Path

    for lang in ("en", "de", "cs"):
        path = Path(__file__).parents[1] / "custom_components" / "loxone" / "translations" / f"{lang}.json"
        issues = json.loads(path.read_text())["issues"]
        assert {"public_key_changed", "https_available", "certificate_expired", "remote_connect_denied"} <= set(issues)
        assert "confirm" in issues["public_key_changed"]["fix_flow"]["step"]


# --- Remote Connect --------------------------------------------------------------


async def test_remote_connect_host_is_passed_through(hass, mock_connection, setup_loxone_entry, created):
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(
        domain=DOMAIN,
        version=4,
        data={},
        options={
            "host": "connect.loxonecloud.com/504F94A23DB1",
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
    await setup_loxone_entry(entry)
    assert entry.state is ConfigEntryState.LOADED
    assert created[-1]["host"] == "connect.loxonecloud.com/504F94A23DB1"


async def test_remote_connect_denied_stops_setup(hass, mock_connection, mock_entry):
    from pyloxone_api.exceptions import LoxoneRemoteConnectDeniedError

    message = "Remote Connect refused (418): Access through Loxone Remote Connect is only possible with the Loxone App or Loxone Config."

    async def denied(self, session=None, *, connect_websocket=True):
        raise LoxoneRemoteConnectDeniedError(message, code=418)

    mock_entry.add_to_hass(hass)
    with patch.object(LoxoneConnection, "open", new=denied):
        await hass.config_entries.async_setup(mock_entry.entry_id)
        await hass.async_block_till_done()

    assert mock_entry.state is ConfigEntryState.SETUP_ERROR
    issue = _issue(hass, "remote_connect_denied", mock_entry)
    assert issue is not None
    assert not issue.is_fixable
    assert issue.translation_placeholders["code"] == "418"
    assert "Loxone App" in issue.translation_placeholders["message"]


async def test_remote_connect_denied_while_running(hass, mock_connection, mock_entry, setup_loxone_entry):
    from pyloxone_api.exceptions import LoxoneRemoteConnectDeniedError

    async def run_denied(self, on_state=None, callback=None, **kwargs):
        raise LoxoneRemoteConnectDeniedError("Remote Connect refused (403)", code=403)

    with (
        patch.object(LoxoneConnection, "run", new=run_denied),
        patch.object(hass.config_entries, "async_schedule_reload") as reload,
    ):
        await setup_loxone_entry(mock_entry)
        await hass.async_block_till_done()
        assert _issue(hass, "remote_connect_denied", mock_entry) is not None
        reload.assert_not_called()
