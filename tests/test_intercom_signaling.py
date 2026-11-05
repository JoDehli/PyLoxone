"""Token-provider authentication and SDP translation without live hardware."""

from __future__ import annotations

import asyncio
import base64
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, call

from Crypto.Cipher import AES, PKCS1_v1_5
from Crypto.PublicKey import RSA
from Crypto.Util.Padding import unpad
import pytest
from webrtc_models import RTCIceCandidateInit

from custom_components.loxone.intercom.sdp import OfferPlan, kind, mid, split_sdp
from custom_components.loxone.intercom.signaling import IntercomSession
from tests.intercom_helpers import OFFER


def test_transport_credentials_stay_with_their_media():
    plan = OfferPlan(OFFER)
    _, sections = split_sdp(plan.combined_offer())
    assert [kind(section) for section in sections] == ["video", "audio"]
    assert "a=ice-ufrag:videoU" in sections[0]
    assert "a=ice-pwd:videoPassword" in sections[0]
    assert "a=ice-ufrag:audioU" in sections[1]
    assert "a=ice-pwd:audioPassword" in sections[1]
    _, bootstrap = split_sdp(plan.video_offer())
    assert len(bootstrap) == 1
    assert mid(bootstrap[0]) == "0"


def test_device_answer_returns_to_original_browser_media_ids():
    plan = OfferPlan(OFFER)
    wire_answer = "\r\n".join(
        [
            "v=0",
            "s=-",
            "t=0 0",
            "a=ice-ufrag:remoteU",
            "m=video 9 UDP/TLS/RTP/SAVPF 99",
            "a=mid:0",
            "a=sendonly",
            "m=audio 9 UDP/TLS/RTP/SAVPF 0",
            "a=mid:1",
            "a=sendonly",
            "",
        ]
    )
    header, sections = split_sdp(plan.restore_answer(wire_answer))
    assert "a=ice-ufrag:remoteU" in header
    assert [kind(section) for section in sections] == ["audio", "video"]
    assert [mid(section) for section in sections] == ["audio", "video"]


async def test_closing_unowned_socket_does_not_hang_up_another_call():
    session = IntercomSession(None, None, "unused", lambda: ("unused", "unused"), lambda message: None)
    session.ws = SimpleNamespace(closed=False, close=AsyncMock())
    session.reader = asyncio.create_task(asyncio.sleep(60))
    session.request = AsyncMock()
    await session.close()
    session.request.assert_not_awaited()
    session.ws.close.assert_awaited_once()
    assert session.reader.cancelled()


async def test_owned_call_is_hung_up_before_socket_closes():
    session = IntercomSession(None, None, "unused", lambda: ("unused", "unused"), lambda message: None)
    session.ws = SimpleNamespace(closed=False, close=AsyncMock())
    session.reader = asyncio.create_task(asyncio.sleep(60))
    session.has_call = True
    session.request = AsyncMock()
    operations = Mock()
    operations.attach_mock(session.request, "request")
    operations.attach_mock(session.ws.close, "close")
    await session.close()
    assert operations.mock_calls == [call.request("hangup"), call.close()]
    assert session.reader.cancelled()


async def test_candidates_use_device_order():
    session = IntercomSession(None, None, "unused", lambda: ("unused", "unused"), lambda message: None)
    session.plan = OfferPlan(OFFER)
    session.answer_ready.set()
    session.request = AsyncMock()
    await session.send_candidate(RTCIceCandidateInit("candidate:audio", sdp_m_line_index=0))
    session.request.assert_awaited_once_with("addIceCandidate", ["candidate:audio", 1])
    session.request.reset_mock()
    await session.send_candidate(RTCIceCandidateInit("candidate:video", sdp_m_line_index=1))
    session.request.assert_awaited_once_with("addIceCandidate", ["candidate:video", 0])


@pytest.mark.parametrize("pem", [False, True, "compact"])
async def test_authentication_reads_provider_and_encrypts_the_current_token(hass, pem):
    private_key = RSA.generate(2048)
    params = ["session-challenge", format(private_key.n, "x"), format(private_key.e, "x")]
    if pem:
        public_key = private_key.public_key().export_key().decode()
        params.append(public_key.replace("\n", "") if pem == "compact" else public_key)

    class Socket:
        closed = False
        sent = []

        def __init__(self):
            self.responses = iter(
                [
                    {"jsonrpc": "2.0", "id": 0, "method": "authenticate", "params": params},
                    {"jsonrpc": "2.0", "method": "ready"},
                ]
            )
            self.sent = []

        async def receive_json(self):
            return next(self.responses)

        async def send_json(self, message):
            self.sent.append(message)

        async def close(self):
            self.closed = True

        def __aiter__(self):
            return self

        async def __anext__(self):
            await asyncio.Future()

    socket = Socket()
    client = SimpleNamespace(ws_connect=AsyncMock(return_value=socket))
    current = {"token": "old-token"}
    session = IntercomSession(
        hass, client, "http://intercom.local/", lambda: ("test-user", current["token"]), lambda message: None
    )
    current["token"] = "current-miniserver-token"
    try:
        await session.open()
        username, encrypted_key, encrypted_token = socket.sent[0]["result"]["data"]
        assert username == "test-user"
        envelope = PKCS1_v1_5.new(private_key).decrypt(base64.b64decode(encrypted_key), b"invalid").decode()
        key_hex, iv_hex, challenge = envelope.split(":")
        assert challenge == "session-challenge"
        clear = AES.new(bytes.fromhex(key_hex), AES.MODE_CBC, bytes.fromhex(iv_hex)).decrypt(
            base64.b64decode(encrypted_token)
        )
        assert unpad(clear, AES.block_size).decode() == "current-miniserver-token"
        client.ws_connect.assert_awaited_once_with(
            "http://intercom.local/", protocols=["webrtc-signaling"], heartbeat=20
        )
    finally:
        await session.close()
