"""HA glue tests for the connection layer (coordinator/services).

These stay in the integration repo: they exercise Home Assistant wiring
(coordinator, services, entity availability) on top of pyloxone_api.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from pyloxone_api.connection import LoxoneConnection


class TestTokenChangeCallback:
    """``_signal_token_changed`` / ``kill_token``.

    The integration passes a ``token_change_callback`` so a
    fresh token (initial auth or refresh) can be persisted to
    HA's ``ConfigEntry.data``. ``kill_token`` invalidates the
    JWT on the Miniserver side so a subsequent restart can't
    reuse a token the previous session already abandoned.
    """

    @pytest.fixture
    def conn(self):
        return LoxoneConnection(
            host="192.0.2.1",
            username="user",
            password="password",
            port=8080,
        )

    def test_signal_no_callback_is_noop(self, conn):
        """If no callback was passed, ``_signal_token_changed``
        is a no-op (the common case for tests / non-HA
        callers).
        """
        # Just call; absence of exception is the assertion.
        conn._signal_token_changed()

    def test_signal_invokes_sync_callback(self, conn):
        """A plain function callback is invoked with the token
        dict and the result is dropped (sync callbacks don't
        need awaiting).
        """
        seen: list[dict] = []

        def cb(token_dict):
            seen.append(token_dict)

        # Manually inject the callback (the param is on
        # ``LoxoneBaseConnection.__init__`` but the field
        # name is ``_token_change_callback``).
        conn._token_change_callback = cb
        conn._token.token = "abc123"
        conn._token.valid_until = 9999999999
        conn._token.key = ""
        conn._token.hash_alg = "SHA1"

        conn._signal_token_changed()
        assert len(seen) == 1
        assert seen[0]["token"] == "abc123"
        assert seen[0]["valid_until"] == 9999999999
        assert seen[0]["hash_alg"] == "SHA1"

    def test_signal_async_callback_spawns_task(self, conn):
        """An async callback is detected via ``iscoroutine``;
        the coroutine is handed to ``_spawn_task`` so the
        caller isn't blocked and any exception is logged via
        the standard done-callback path.
        """
        from unittest.mock import patch

        from pyloxone_api import (
            connection as conn_mod,
        )

        async def acb(token_dict):
            return None

        with patch.object(conn_mod.LoxoneConnection, "_spawn_task") as spawn:
            conn._token_change_callback = acb
            conn._token.token = "tok"
            conn._token.valid_until = 100
            conn._token.key = ""
            conn._token.hash_alg = "SHA1"

            conn._signal_token_changed()
        assert spawn.called
        # The first arg of the call is a coroutine, the second
        # is the name we use for the spawned task.
        call = spawn.call_args
        assert call[0][0].__class__.__name__ == "coroutine"
        assert call[1]["name"] == "loxone.token-changed"

    def test_signal_swallows_callback_exception(self, conn):
        """A callback that raises must not break the token
        handler — the exception is logged at WARNING, not
        re-raised.
        """
        from unittest.mock import patch

        from pyloxone_api import (
            connection as conn_mod,
        )

        def bad_cb(token_dict):
            raise RuntimeError("simulated persistence failure")

        with patch.object(conn_mod._LOGGER, "warning") as warn:
            conn._token_change_callback = bad_cb
            conn._token.token = "tok"
            conn._token.valid_until = 100
            conn._token.key = ""
            conn._token.hash_alg = "SHA1"

            # No exception propagates out of the call.
            conn._signal_token_changed()
        assert warn.called

    @pytest.mark.asyncio
    async def test_kill_token_without_token_is_noop(self, conn):
        """If ``self._token.token`` is empty, ``kill_token``
        is a no-op — there's nothing to invalidate.
        """
        # ``conn._token`` is a fresh LoxoneToken (token="").
        await conn.kill_token()  # must not raise

    @pytest.mark.asyncio
    async def test_kill_token_sends_command(self, conn, monkeypatch):
        """With a token set, ``kill_token`` sends
        ``jdev/sys/killtoken/<token>/<user>`` via
        ``_send_text_command``.

        Both path segments matter: the Miniserver answers 400 and
        keeps the token alive when the user segment is missing.
        The user is the percent-encoded form used everywhere else
        in the protocol layer, so a non-ASCII username must not
        break the command path.
        """
        sent: list[str] = []

        async def fake_send(self, command, encrypted=True):
            sent.append((command, encrypted))

        from pyloxone_api import (
            connection as conn_mod,
        )

        # Patch the method on the *class* so it works on the
        # instance too.
        monkeypatch.setattr(
            conn_mod.LoxoneConnection, "_send_text_command", fake_send
        )
        # Percent-encoded, to prove ``kill_token`` sends the
        # encoded username and not the raw one.
        monkeypatch.setattr(conn, "_encoded_username", "b%C3%B6b")

        conn._token.token = "test-jwt-abc"
        await conn.kill_token()
        assert len(sent) == 1
        assert sent[0][0] == "jdev/sys/killtoken/test-jwt-abc/b%C3%B6b"
        # The raw token must not cross the network in clear text
        # (ws:// on Gen1): the kill goes through command encryption.
        assert sent[0][1] is True

    @pytest.mark.asyncio
    async def test_kill_token_never_logs_the_token(self, conn, monkeypatch, caplog):
        """Neither ``kill_token`` nor ``_send_text_command`` may put
        the raw token into the (DEBUG) log.
        """
        import logging

        from pyloxone_api import (
            connection as conn_mod,
        )

        # Run the real ``_send_text_command`` up to the websocket send.
        sent: list[str] = []

        class _Ws:
            async def send(self, message):
                sent.append(message)

        monkeypatch.setattr(
            conn_mod.LoxoneConnection, "is_connected", property(lambda self: True)
        )
        conn.connection = _Ws()
        conn._generate_salt()
        conn._token.token = "secret-jwt-123"

        with caplog.at_level(
            logging.DEBUG, logger="pyloxone_api.connection"
        ):
            await conn.kill_token()

        assert len(sent) == 1
        assert sent[0].startswith("jdev/sys/enc/")
        assert "secret-jwt-123" not in sent[0]
        assert "secret-jwt-123" not in caplog.text
        assert "jdev/sys/killtoken/…" in caplog.text

    def test_coordinator_persists_token_without_logging_secret(self):
        """A refresh callback merges the new token into entry
        data, preserves unrelated data, and confirms persistence
        without putting the secret itself in the log.
        """
        from unittest.mock import patch

        from custom_components.loxone.coordinator import _ConfigEntryTokenStore

        entry = SimpleNamespace(
            entry_id="entry-a",
            title="Test Miniserver",
            data={"existing_setting": "preserved"},
        )
        saved: list[dict] = []

        class _ConfigEntries:
            def async_update_entry(self, config_entry, *, data):
                saved.append(data)
                config_entry.data = data

        hass = SimpleNamespace(config_entries=_ConfigEntries())
        store = _ConfigEntryTokenStore(hass, entry)
        refreshed_token = {
            "token": "secret-token-value",
            "valid_until": 2_000_000_000,
            "hash_alg": "SHA256",
        }

        with patch("custom_components.loxone.coordinator._LOGGER.info") as info:
            store.save(refreshed_token)

        assert len(saved) == 1
        assert entry.data == {
            "existing_setting": "preserved",
            **refreshed_token,
        }
        assert info.called
        assert "secret-token-value" not in str(info.call_args)


class TestRefreshTokenServiceRouting:
    """The integration-wide service must dispatch to only the
    selected config entry, even when several entries are loaded.
    """

    @pytest.mark.asyncio
    async def test_service_refreshes_only_selected_entry(self):
        from types import SimpleNamespace

        from custom_components.loxone import _async_handle_refresh_token
        from custom_components.loxone.const import DOMAIN

        calls: list[str] = []

        class _Api:
            def __init__(self, entry_id):
                self.entry_id = entry_id

            async def async_refresh_token(self):
                calls.append(self.entry_id)

        def _coordinator(entry_id):
            return SimpleNamespace(
                config_entry=SimpleNamespace(
                    entry_id=entry_id, domain=DOMAIN, title=f"Loxone {entry_id}"
                ),
                api=_Api(entry_id),
            )

        hass = SimpleNamespace(
            data={DOMAIN: {"entry-a": _coordinator("entry-a"),
                           "entry-b": _coordinator("entry-b")}}
        )
        call = SimpleNamespace(data={"config_entry_id": "entry-b"})

        await _async_handle_refresh_token(hass, call)
        assert calls == ["entry-b"]

    @pytest.mark.asyncio
    async def test_service_rejects_unloaded_or_invalid_entry(self):
        from types import SimpleNamespace

        from homeassistant.exceptions import HomeAssistantError

        from custom_components.loxone import _async_handle_refresh_token
        from custom_components.loxone.const import DOMAIN

        hass = SimpleNamespace(data={DOMAIN: {}})
        call = SimpleNamespace(data={"config_entry_id": "not-loaded"})

        with pytest.raises(HomeAssistantError, match="not loaded"):
            await _async_handle_refresh_token(hass, call)

    @pytest.mark.asyncio
    async def test_global_service_registers_once(self, hass):
        from custom_components.loxone import async_setup
        from custom_components.loxone.const import (
            DOMAIN,
            SERVICE_REFRESH_TOKEN,
        )

        assert await async_setup(hass, {})
        assert await async_setup(hass, {})
        assert hass.services.has_service(DOMAIN, SERVICE_REFRESH_TOKEN)


class TestCoordinatorTokenCleanup:
    """``async_cleanup`` must not kill the persisted token (P4)."""

    @pytest.mark.asyncio
    async def test_cleanup_does_not_kill_token_by_default(self):
        from custom_components.loxone.coordinator import LoxoneCoordinator

        calls = []

        class _FakeApi:
            async def kill_token(self):
                calls.append("kill")

            async def close(self):
                calls.append("close")

        coordinator = LoxoneCoordinator.__new__(LoxoneCoordinator)
        coordinator.listeners = []
        coordinator.api = _FakeApi()

        await coordinator.async_cleanup()

        assert calls == ["close"]

    @pytest.mark.asyncio
    async def test_cleanup_kills_token_on_request(self):
        from custom_components.loxone.coordinator import LoxoneCoordinator

        calls = []

        class _FakeApi:
            async def kill_token(self):
                calls.append("kill")

            async def close(self):
                calls.append("close")

        coordinator = LoxoneCoordinator.__new__(LoxoneCoordinator)
        coordinator.listeners = []
        coordinator.api = _FakeApi()

        await coordinator.async_cleanup(kill_token=True)

        assert calls == ["kill", "close"]

    @pytest.mark.asyncio
    async def test_remove_entry_kills_token_while_connected(self):
        """Removing the entry invalidates the token — but only while
        the websocket is still open; after unload it is a no-op and
        the token simply expires.
        """
        from types import SimpleNamespace as NS

        from custom_components.loxone import async_remove_entry

        calls = []

        class _FakeApi:
            is_connected = True

            async def kill_token(self):
                calls.append("kill")

        coordinator = NS(
            config_entry=NS(entry_id="abc"),
            api=_FakeApi(),
        )
        hass = NS(data={"loxone": {"abc": coordinator}})

        await async_remove_entry(hass, NS(entry_id="abc"))

        assert calls == ["kill"]

    @pytest.mark.asyncio
    async def test_remove_entry_skips_kill_when_disconnected(self):
        from types import SimpleNamespace as NS

        from custom_components.loxone import async_remove_entry

        calls = []

        class _FakeApi:
            is_connected = False

            async def kill_token(self):
                calls.append("kill")

        coordinator = NS(
            config_entry=NS(entry_id="abc"),
            api=_FakeApi(),
        )
        hass = NS(data={"loxone": {"abc": coordinator}})

        await async_remove_entry(hass, NS(entry_id="abc"))

        assert calls == []


class TestEntityAvailability:
    """Entities follow the connection state (P5)."""

    def test_entity_inherits_availability_property(self):
        from custom_components.loxone import LoxoneEntity

        # The base class must define an ``available`` property that
        # ANDs the entity flag with the connection state; the sensor
        # override must consult the same helper.
        assert isinstance(LoxoneEntity.available, property)
        assert hasattr(LoxoneEntity, "_connection_available")

    def test_connection_available_defaults_to_true_without_coordinator(self):
        from custom_components.loxone import LoxoneEntity

        entity = LoxoneEntity.__new__(LoxoneEntity)
        entity._attr_available = True
        # No ``hass``/registry entry → must not block availability.
        entity.hass = SimpleNamespace(data={})
        assert entity._connection_available() is True

    def test_connection_unavailable_marks_entity_unavailable(self):
        from types import SimpleNamespace as NS

        from custom_components.loxone import LoxoneEntity

        class _Coordinator:
            connection_available = False

        entity = LoxoneEntity.__new__(LoxoneEntity)
        entity._attr_available = True
        entity.registry_entry = NS(config_entry_id="abc")
        entity.hass = NS(data={"loxone": {"abc": _Coordinator()}})

        assert entity.available is False

    def test_connection_available_with_value(self):
        from types import SimpleNamespace as NS

        from custom_components.loxone import LoxoneEntity

        class _Coordinator:
            connection_available = True

        entity = LoxoneEntity.__new__(LoxoneEntity)
        entity._attr_available = True
        entity.registry_entry = NS(config_entry_id="abc")
        entity.hass = NS(data={"loxone": {"abc": _Coordinator()}})

        assert entity.available is True


