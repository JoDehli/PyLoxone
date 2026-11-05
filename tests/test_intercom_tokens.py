"""Dedicated token lifecycle, persistence and separation from main app auth."""

import asyncio
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME
from homeassistant.util import dt as dt_util
from tests.ha_test_helpers import MockConfigEntry, async_fire_time_changed

from custom_components.loxone.intercom.tokens import (
    AUTH_DATA,
    LOXONE_EPOCH_TIMESTAMP,
    IntercomTokenManager,
    async_remove_intercom_token,
)
from custom_components.loxone.pyloxone_api.exceptions import IntercomTokenError


def expiry(seconds=3600):
    return dt_util.utcnow().timestamp() - LOXONE_EPOCH_TIMESTAMP + seconds


@pytest.fixture
async def manager_factory(hass):
    managers = []

    def create(data=None, username="test-user"):
        entry = MockConfigEntry(
            domain="loxone", options={CONF_USERNAME: username}, data=data or {"token": "main-app-token"}
        )
        entry.add_to_hass(hass)
        count = 0

        async def issue(*args):
            nonlocal count
            count += 1
            await asyncio.sleep(0)
            return {"token": f"intercom-{count}", "validUntil": expiry()}

        api = SimpleNamespace(async_intercom_token=AsyncMock(side_effect=issue))
        manager = IntercomTokenManager(hass, entry, api)
        managers.append(manager)
        return manager, entry, api

    yield create
    for manager in managers:
        await manager.async_close()


async def test_concurrent_first_calls_share_a_dedicated_token(manager_factory):
    manager, entry, api = manager_factory()
    result = await asyncio.gather(*(manager.async_credentials() for _ in range(5)))
    assert result == [("test-user", "intercom-1")] * 5
    api.async_intercom_token.assert_awaited_once_with(manager.client_id)
    assert entry.data["token"] == "main-app-token"
    assert entry.data[AUTH_DATA]["permission"] == 0


async def test_restart_reuses_persisted_token_and_client_identity(hass, manager_factory):
    manager, entry, _ = manager_factory()
    await manager.async_credentials()
    await manager.async_close()
    fresh, _, api = manager_factory(dict(entry.data))
    assert fresh.client_id == manager.client_id
    assert await fresh.async_credentials() == ("test-user", "intercom-1")
    api.async_intercom_token.assert_not_awaited()


async def test_renews_on_schedule_and_preserves_main_token(hass, freezer, manager_factory):
    manager, entry, api = manager_factory()
    await manager.async_credentials()
    freezer.move_to(dt_util.utcnow() + timedelta(seconds=3541))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done(wait_background_tasks=True)
    assert await manager.async_credentials() == ("test-user", "intercom-2")
    assert api.async_intercom_token.await_args.args == (manager.client_id, "intercom-1")
    assert entry.data["token"] == "main-app-token"


async def test_revoked_token_is_reissued_when_refresh_is_rejected(manager_factory):
    manager, entry, api = manager_factory()
    await manager.async_credentials()
    api.async_intercom_token.side_effect = [
        IntercomTokenError("rejected", 401),
        {"token": "replacement", "validUntil": expiry()},
    ]
    assert await manager.async_credentials(renew=True) == ("test-user", "replacement")
    assert api.async_intercom_token.await_args_list[-2].args == (manager.client_id, "intercom-1")
    assert api.async_intercom_token.await_args_list[-1].args == (manager.client_id,)
    assert entry.data["token"] == "main-app-token"


async def test_invalidating_old_session_does_not_discard_newer_token(manager_factory):
    manager, entry, _ = manager_factory()
    await manager.async_credentials()
    await manager.async_credentials(renew=True)
    await manager.async_invalidate("intercom-1")
    assert entry.data[AUTH_DATA]["token"] == "intercom-2"
    await manager.async_invalidate("intercom-2")
    assert entry.data[AUTH_DATA]["token"] == ""
    assert await manager.async_credentials() == ("test-user", "intercom-3")


async def test_expired_token_is_replaced_instead_of_refreshed(manager_factory):
    manager, _, api = manager_factory(
        {
            AUTH_DATA: {
                "username": "test-user",
                "client_id": "11111111-1111-4111-8111-111111111111",
                "permission": 0,
                "token": "expired",
                "valid_until": expiry(-10),
            }
        }
    )
    assert await manager.async_credentials() == ("test-user", "intercom-1")
    api.async_intercom_token.assert_awaited_once_with("11111111-1111-4111-8111-111111111111")


async def test_transient_renewal_failure_retries_without_losing_valid_token(hass, freezer, manager_factory):
    manager, entry, api = manager_factory()
    await manager.async_credentials()
    api.async_intercom_token.side_effect = IntercomTokenError("offline")
    with pytest.raises(IntercomTokenError, match="Could not obtain"):
        await manager.async_credentials(renew=True)
    assert entry.data[AUTH_DATA]["token"] == "intercom-1"
    api.async_intercom_token.side_effect = None
    api.async_intercom_token.return_value = {"token": "after-retry", "validUntil": expiry()}
    freezer.move_to(dt_util.utcnow() + timedelta(seconds=61))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done(wait_background_tasks=True)
    assert entry.data[AUTH_DATA]["token"] == "after-retry"


async def test_unload_cancels_renewal_and_prevents_new_requests(hass, freezer, manager_factory):
    manager, entry, api = manager_factory()
    await manager.async_credentials()
    await manager.async_close()
    freezer.move_to(dt_util.utcnow() + timedelta(hours=2))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done(wait_background_tasks=True)
    assert api.async_intercom_token.await_count == 1
    assert entry.data[AUTH_DATA]["token"] == "intercom-1"
    with pytest.raises(IntercomTokenError, match="closed"):
        await manager.async_credentials()


@pytest.mark.parametrize(
    "value",
    [
        {"token": "", "validUntil": 1},
        {"token": "bad", "validUntil": "tomorrow"},
        {"token": "bad", "validUntil": float("inf")},
        {"token": "bad", "validUntil": 1},
    ],
)
async def test_malformed_issue_response_never_becomes_stored_credentials(manager_factory, value):
    manager, entry, api = manager_factory()
    api.async_intercom_token.side_effect = None
    api.async_intercom_token.return_value = value
    with pytest.raises(IntercomTokenError):
        await manager.async_credentials()
    assert not entry.data[AUTH_DATA]["token"]
    assert entry.data["token"] == "main-app-token"


async def test_changed_username_does_not_reuse_another_accounts_token(manager_factory):
    manager, entry, _ = manager_factory()
    await manager.async_credentials()
    other, _, api = manager_factory(dict(entry.data), username="another-user")
    assert other.client_id != manager.client_id
    assert await other.async_credentials() == ("another-user", "intercom-1")
    api.async_intercom_token.assert_awaited_once()


@pytest.mark.parametrize("close_fails", [False, True])
async def test_removal_reconnects_to_revoke_only_the_dedicated_token(hass, monkeypatch, caplog, close_fails):
    from custom_components.loxone.pyloxone_api import connection

    entry = MockConfigEntry(
        domain="loxone",
        options={
            CONF_HOST: "192.0.2.1",
            CONF_PORT: 80,
            CONF_USERNAME: "test-user",
            CONF_PASSWORD: "password",
        },
        data={
            "token": "main-app",
            AUTH_DATA: {
                "username": "test-user",
                "client_id": "client-uuid",
                "permission": 0,
                "token": "dedicated",
            },
        },
    )
    entry.add_to_hass(hass)
    ready = asyncio.Event()
    ready.set()
    pending = asyncio.Event()
    api = SimpleNamespace(
        open=AsyncMock(),
        run=pending.wait,
        close=AsyncMock(),
        _authenticated_event=ready,
        async_intercom_token=AsyncMock(),
    )
    monkeypatch.setattr(connection, "LoxoneConnection", lambda **kwargs: api)
    if close_fails:
        api.close.side_effect = RuntimeError("secret-token-in-transport-error")
    await async_remove_intercom_token(hass, entry)
    api.async_intercom_token.assert_awaited_once_with("client-uuid", "dedicated", revoke=True)
    api.close.assert_awaited_once()
    assert "secret-token-in-transport-error" not in caplog.text


async def test_unload_cancels_inflight_background_renewal(hass, freezer, manager_factory):
    manager, _, api = manager_factory()
    await manager.async_credentials()
    entered = asyncio.Event()

    async def pending(*args):
        entered.set()
        await asyncio.Future()

    api.async_intercom_token.side_effect = pending
    freezer.move_to(dt_util.utcnow() + timedelta(seconds=3541))
    async_fire_time_changed(hass, dt_util.utcnow())
    await entered.wait()
    task = manager._refresh_task
    await manager.async_close()
    assert task.cancelled()


@pytest.mark.parametrize("code", [401, 403, 4003])
async def test_rejected_credentials_stop_automatic_retries(hass, freezer, manager_factory, code):
    manager, entry, api = manager_factory()
    api.async_intercom_token.side_effect = IntercomTokenError("account rejected", code)
    with pytest.raises(IntercomTokenError) as error:
        await manager.async_credentials()
    assert error.value.code == code
    freezer.move_to(dt_util.utcnow() + timedelta(minutes=10))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done(wait_background_tasks=True)
    assert api.async_intercom_token.await_count == 1
    assert not entry.data[AUTH_DATA]["token"]
    assert entry.data["token"] == "main-app-token"


async def test_cancelled_viewer_does_not_cancel_shared_token_issuance(manager_factory):
    manager, entry, api = manager_factory()
    entered, release = asyncio.Event(), asyncio.Event()

    async def pending(*args):
        entered.set()
        await release.wait()
        return {"token": "dedicated", "validUntil": expiry()}

    api.async_intercom_token.side_effect = pending
    viewer = asyncio.create_task(manager.async_credentials())
    await entered.wait()
    viewer.cancel()
    await asyncio.gather(viewer, return_exceptions=True)
    assert not manager._credential_task.cancelled()
    release.set()
    assert await manager.async_credentials() == ("test-user", "dedicated")
    assert entry.data[AUTH_DATA]["token"] == "dedicated"
    api.async_intercom_token.assert_awaited_once()


@pytest.mark.parametrize("bad_expiry", [True, 1e308, 10**500, -1, None, "tomorrow"])
async def test_corrupt_stored_expiry_is_replaced_without_timer_errors(manager_factory, bad_expiry):
    manager, _, api = manager_factory(
        {
            "token": "main-app-token",
            AUTH_DATA: {
                "username": "test-user",
                "client_id": "11111111-1111-4111-8111-111111111111",
                "permission": 0,
                "token": "old",
                "valid_until": bad_expiry,
            },
        }
    )
    assert await manager.async_credentials() == ("test-user", "intercom-1")
    api.async_intercom_token.assert_awaited_once_with(manager.client_id)


@pytest.mark.parametrize("client_id", [None, 123, "../invalid/client", "not-a-uuid"])
async def test_invalid_client_identity_discards_the_old_token(manager_factory, client_id):
    from uuid import UUID

    manager, entry, api = manager_factory(
        {
            AUTH_DATA: {
                "username": "test-user",
                "client_id": client_id,
                "permission": 0,
                "token": "old",
                "valid_until": expiry(),
            }
        }
    )
    assert str(UUID(manager.client_id)) == manager.client_id
    assert await manager.async_credentials() == ("test-user", "intercom-1")
    api.async_intercom_token.assert_awaited_once_with(manager.client_id)
    assert entry.data[AUTH_DATA]["client_id"] == manager.client_id


async def test_stored_app_token_is_never_reused_as_an_intercom_token(manager_factory):
    manager, _, api = manager_factory(
        {
            "token": "main-app-token",
            AUTH_DATA: {
                "username": "test-user",
                "client_id": "11111111-1111-4111-8111-111111111111",
                "permission": 0,
                "token": "main-app-token",
                "valid_until": expiry(),
            },
        }
    )
    assert await manager.async_credentials() == ("test-user", "intercom-1")
    api.async_intercom_token.assert_awaited_once_with(manager.client_id)


async def test_issue_response_cannot_substitute_the_app_token(manager_factory):
    manager, entry, api = manager_factory()
    api.async_intercom_token.side_effect = None
    api.async_intercom_token.return_value = {"token": "main-app-token", "validUntil": expiry()}
    with pytest.raises(IntercomTokenError):
        await manager.async_credentials()
    assert not entry.data[AUTH_DATA]["token"]
    assert entry.data["token"] == "main-app-token"


async def test_renewal_joining_a_cached_lookup_still_schedules_the_next_refresh(hass, freezer, manager_factory):
    manager, _, api = manager_factory()
    await manager.async_credentials()
    release = asyncio.Event()

    async def cached():
        await release.wait()
        return "test-user", "intercom-1"

    manager._credential_task = asyncio.create_task(cached())
    freezer.move_to(dt_util.utcnow() + timedelta(seconds=3541))
    async_fire_time_changed(hass, dt_util.utcnow())
    for _ in range(10):
        if manager._refresh_task is not None:
            break
        await asyncio.sleep(0)
    assert manager._refresh_task is not None
    release.set()
    await hass.async_block_till_done(wait_background_tasks=True)
    assert manager._cancel_refresh is not None
    freezer.move_to(dt_util.utcnow() + timedelta(seconds=31))
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done(wait_background_tasks=True)
    assert api.async_intercom_token.await_count == 2
