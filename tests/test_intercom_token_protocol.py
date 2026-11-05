"""Encrypted token RPCs cannot overwrite or disrupt main-session authentication."""

import asyncio
import hashlib
import hmac
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from custom_components.loxone.pyloxone_api.connection import LoxoneConnection
from custom_components.loxone.pyloxone_api.exceptions import IntercomTokenError
from custom_components.loxone.pyloxone_api.loxone_token import LoxoneToken
from custom_components.loxone.pyloxone_api.message import TextMessage


def reply(command, value, code=200):
    return TextMessage(json.dumps({"LL": {"control": command, "code": code, "value": value}}))


@pytest.fixture
def api():
    connection = LoxoneConnection(host="192.0.2.1", username="test user", password="secret", port=80)
    connection.connection = SimpleNamespace(
        protocol=SimpleNamespace(state=SimpleNamespace(name="OPEN")), close=AsyncMock()
    )
    connection.miniserver_version = [17, 3]
    connection._authenticated_event.set()
    connection._token = LoxoneToken(token="main-app", valid_until=999999999, hash_alg="SHA256")
    connection._key = "main-session-key"
    connection._token_change_callback = Mock()
    return connection


@pytest.mark.parametrize("algorithm", ["SHA1", "SHA256"])
async def test_issue_is_encrypted_permission_zero_without_main_auth_side_effects(api, algorithm):
    commands = []

    async def send(command, encrypted):
        assert encrypted is True
        commands.append(command)
        value = (
            {"key": "AB" * 16, "salt": "user-salt", "hashAlg": algorithm}
            if "getkey2" in command
            else {
                "token": "dedicated",
                "validUntil": 999999998,
            }
        )
        await api._websocket_event(reply(command, value))

    api._send_text_command = AsyncMock(side_effect=send)
    assert (await api.async_intercom_token("client-uuid"))["token"] == "dedicated"
    assert commands[0] == "jdev/sys/getkey2/test%20user"
    algo = getattr(hashlib, algorithm.lower())
    pwd = algo(b"secret:user-salt").hexdigest().upper()
    digest = hmac.new(bytes.fromhex("AB" * 16), ("test user:" + pwd).encode(), algo).hexdigest()
    assert commands[1] == f"jdev/sys/getjwt/{digest}/test%20user/0/client-uuid/PyLoxone%20Intercom"
    assert api.get_token_dict()["token"] == "main-app"
    assert api._key == "main-session-key"
    api._token_change_callback.assert_not_called()
    assert api._message_queue.empty()


async def test_refresh_and_revoke_target_only_the_dedicated_token(api):
    async def send(command, encrypted):
        assert encrypted
        await api._websocket_event(reply(command, {"token": "refreshed", "validUntil": 999999998}))

    api._send_text_command = AsyncMock(side_effect=send)
    await api.async_intercom_token("client", "dedicated")
    api._send_text_command.assert_awaited_with("jdev/sys/refreshjwt/dedicated/test%20user", encrypted=True)
    await api.async_intercom_token("client", "dedicated", revoke=True)
    api._send_text_command.assert_awaited_with("jdev/sys/killtoken/dedicated/test%20user", encrypted=True)
    assert api.get_token_dict()["token"] == "main-app"


async def test_dedicated_rejection_does_not_escalate_main_authentication(api):
    async def send(command, encrypted):
        await api._websocket_event(reply(command, "", 401))

    api._send_text_command = AsyncMock(side_effect=send)
    with pytest.raises(IntercomTokenError) as rejected:
        await api.async_intercom_token("client", "revoked")
    assert rejected.value.code == 401
    assert api._auth_failure is None
    assert api._authenticated_event.is_set()
    assert api.get_token_dict()["token"] == "main-app"


async def test_token_requests_wait_for_the_main_refresh_lock(api):
    async def send(command, encrypted):
        await api._websocket_event(reply(command, {"token": "renewed"}))

    api._send_text_command = AsyncMock(side_effect=send)
    await api._token_refresh_lock.acquire()
    task = asyncio.create_task(api.async_intercom_token("client", "dedicated"))
    await asyncio.sleep(0)
    api._send_text_command.assert_not_awaited()
    api._token_refresh_lock.release()
    await task
    api._send_text_command.assert_awaited_once()


async def test_timeout_discards_late_reply_and_requires_reconnect(api):
    api._send_text_command = AsyncMock()
    with pytest.raises(TimeoutError):
        await api._request_intercom_command("jdev/sys/getjwt/not-a-main-token", timeout=0.001)
    assert api._reconnect_event.is_set()
    assert not api._authenticated_event.is_set()
    await api._websocket_event(reply("jdev/sys/getjwt/not-a-main-token", {"token": "late-dedicated"}))
    assert api.get_token_dict()["token"] == "main-app"
    api._token_change_callback.assert_not_called()
    with pytest.raises(IntercomTokenError, match="not authenticated"):
        await api.async_intercom_token("client")


async def test_decrypted_byte_control_is_routed_before_main_handlers(api):
    pending = asyncio.get_running_loop().create_future()
    api._intercom_reply = ("getjwt", pending)
    message = reply("jdev/sys/getjwt/example", {"token": "dedicated"})
    message.control = message.control.encode()
    assert api._handle_intercom_reply(message)
    assert (await pending)["token"] == "dedicated"
    assert api.get_token_dict()["token"] == "main-app"


async def test_cancelled_request_cannot_poison_main_token_later(api):
    sent = asyncio.Event()

    async def send(*args, **kwargs):
        sent.set()

    api._send_text_command = AsyncMock(side_effect=send)
    task = asyncio.create_task(api.async_intercom_token("client", "dedicated"))
    await sent.wait()
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert task.cancelled()
    await api._websocket_event(reply("jdev/sys/refreshjwt/dedicated/test%20user", {"token": "late"}))
    assert api.get_token_dict()["token"] == "main-app"
    assert api._reconnect_event.is_set()
