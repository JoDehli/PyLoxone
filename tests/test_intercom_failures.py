"""Peer failures, bounded waits, close races and SDP/ICE validation."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import aiohttp
import pytest
from webrtc_models import RTCIceCandidateInit

from custom_components.loxone.intercom import signaling
from custom_components.loxone.intercom.errors import (
    IntercomBusyError,
    IntercomConnectionError,
    IntercomIceError,
    IntercomProtocolError,
    IntercomSDPError,
)
from custom_components.loxone.intercom.sdp import OfferPlan
from custom_components.loxone.intercom.signaling import IntercomSession
from tests.intercom_helpers import OFFER, Socket


@pytest.fixture
async def peer(hass):
    session = IntercomSession(hass, None, "http://intercom.invalid/", lambda: ("test", "test-token"), Mock())
    session.ws = Socket()
    session.plan = OfferPlan(OFFER)
    session.reader = hass.async_create_background_task(session._receive(), "test_intercom_peer")
    yield session
    await session.close()


async def test_connect_is_included_in_authentication_deadline(hass, monkeypatch):
    monkeypatch.setattr(signaling, "OPEN_TIMEOUT", 0.05)
    client = SimpleNamespace(ws_connect=AsyncMock(side_effect=lambda *a, **k: None))

    async def stalled(*args, **kwargs):
        await asyncio.Future()

    client.ws_connect.side_effect = stalled
    session = IntercomSession(hass, client, "http://intercom.invalid/", lambda: ("test", "token"), Mock())
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(session.open(), 1)
    await session.close()
    assert session.reader is None


async def test_stalled_write_is_bounded_and_drops_its_waiter(peer, monkeypatch):
    monkeypatch.setattr(signaling, "RPC_TIMEOUT", 0.05)

    async def stalled(message):
        await asyncio.Future()

    peer.ws.send_json = stalled
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(peer.request("info"), 1)
    assert not peer.pending


async def test_late_rpc_after_timeout_cannot_complete_a_new_request(peer, monkeypatch):
    monkeypatch.setattr(signaling, "RPC_TIMEOUT", 0.05)
    with pytest.raises(TimeoutError):
        await peer.request("info")
    old_id = peer.ws.sent[-1]["id"]
    monkeypatch.setattr(signaling, "RPC_TIMEOUT", 1)
    current = asyncio.create_task(peer.request("info"))
    await asyncio.sleep(0)
    new_id = peer.ws.sent[-1]["id"]
    peer.ws.feed({"id": old_id, "result": {"code": 200, "data": "old"}})
    peer.ws.feed({"id": new_id, "result": {"code": 200, "data": "new"}})
    assert await asyncio.wait_for(current, 1) == "new"
    assert not peer.pending


async def test_remote_disconnect_fails_pending_requests_immediately(peer):
    callback = Mock()
    peer.on_disconnect = callback
    request = asyncio.create_task(peer.request("info"))
    await asyncio.sleep(0)
    peer.ws.incoming.put_nowait(None)
    with pytest.raises(IntercomConnectionError):
        await asyncio.wait_for(request, 1)
    callback.assert_called_once()
    assert not peer.pending
    with pytest.raises(IntercomConnectionError):
        await asyncio.wait_for(peer.request("info"), 1)


@pytest.mark.parametrize(
    "payload",
    [
        "not-json-secret-token",
        "[]",
        '{"method": {}, "private": "secret-token"}',
        '{"method":"addIceCandidate","params":[]}',
        '{"id":[],"result":{}}',
    ],
)
async def test_malformed_peer_messages_fail_closed_without_echoing_payloads(peer, payload, caplog):
    peer.ws.incoming.put_nowait(SimpleNamespace(type=aiohttp.WSMsgType.TEXT, data=payload))
    await asyncio.wait_for(peer.reader, 1)
    assert isinstance(peer.failure, IntercomProtocolError)
    assert "secret-token" not in str(peer.failure)
    assert "secret-token" not in caplog.text


@pytest.mark.parametrize(
    ("notification", "error_type"),
    [
        ("kick", IntercomConnectionError),
        ("closeDueToNoDemand", IntercomConnectionError),
        ("noIceMatchFound", IntercomIceError),
        ("onlineChanged", IntercomConnectionError),
    ],
)
async def test_device_end_notifications_release_only_the_ended_session(peer, notification, error_type):
    peer.has_call = True
    peer.on_disconnect = Mock()
    peer.ws.feed({"method": notification, "params": [False]})
    await asyncio.wait_for(peer.reader, 1)
    assert isinstance(peer.failure, error_type)
    peer.on_disconnect.assert_called_once()
    await peer.close()
    assert not any(message.get("method") == "hangup" for message in peer.ws.sent)


async def test_rpc_busy_response_is_actionable_and_does_not_claim_a_call(peer):
    request = asyncio.create_task(peer.request("call", []))
    await asyncio.sleep(0)
    rpc_id = peer.ws.sent[-1]["id"]
    peer.ws.feed({"id": rpc_id, "result": {"code": 486, "data": "private-server-data"}})
    with pytest.raises(IntercomBusyError) as error:
        await request
    assert "private-server-data" not in str(error.value)
    assert not peer.has_call
    await peer.close()
    assert not any(message.get("method") == "hangup" for message in peer.ws.sent)


@pytest.mark.parametrize("result", [None, [], {"code": "secret-token"}])
async def test_malformed_rpc_results_are_sanitized(peer, result):
    request = asyncio.create_task(peer.request("info"))
    await asyncio.sleep(0)
    peer.ws.feed({"id": peer.ws.sent[-1]["id"], "result": result})
    with pytest.raises(IntercomProtocolError) as error:
        await request
    assert "secret-token" not in str(error.value)


async def test_concurrent_closers_share_cleanup_when_one_waiter_is_cancelled(peer):
    entered, release = asyncio.Event(), asyncio.Event()
    original = peer.ws.close

    async def slow_close():
        entered.set()
        await release.wait()
        await original()

    peer.ws.close = slow_close
    first = asyncio.create_task(peer.close())
    await entered.wait()
    second = asyncio.create_task(peer.close())
    first.cancel()
    await asyncio.gather(first, return_exceptions=True)
    assert not peer._close_task.cancelled()
    release.set()
    await asyncio.wait_for(second, 1)
    assert peer.ws.close_count == 1
    assert peer.reader.done()


async def test_owned_hangup_without_reply_cannot_block_cleanup(peer, monkeypatch):
    monkeypatch.setattr(signaling, "CLOSE_TIMEOUT", 0.05)
    peer.has_call = True
    await asyncio.wait_for(peer.close(), 1)
    assert peer.reader.done()
    assert peer.ws.closed
    assert not peer.pending
    assert [m["method"] for m in peer.ws.sent] == ["hangup"]


async def test_remote_candidate_buffer_is_bounded(peer, monkeypatch):
    monkeypatch.setattr(signaling, "MAX_PENDING_CANDIDATES", 2)
    for _ in range(3):
        peer.ws.feed({"method": "addIceCandidate", "params": ["candidate:peer", 0]})
    await asyncio.wait_for(peer.reader, 1)
    assert isinstance(peer.failure, IntercomProtocolError)
    assert len(peer.remote_candidates) == 2
    await peer.close()
    assert not peer.remote_candidates


async def test_mid_only_candidate_selects_its_own_transport(peer):
    peer.answer_ready.set()
    peer.request = AsyncMock()
    await peer.send_candidate(RTCIceCandidateInit("candidate:audio", sdp_mid="audio"))
    peer.request.assert_awaited_once_with("addIceCandidate", ["candidate:audio", 1])
    index, mid = peer.plan.remote_candidate_target(None, "0")
    assert (index, mid) == (1, "video")


@pytest.mark.parametrize(("index", "mid"), [(99, None), (-1, None), (True, None), (None, "unknown"), (0, "video")])
def test_mismatched_candidate_targets_are_rejected(index, mid):
    with pytest.raises(IntercomProtocolError):
        OfferPlan(OFFER).local_candidate_target(index, mid)


@pytest.mark.parametrize(
    "offer",
    [
        None,
        "",
        "x" * 262145,
        OFFER.replace("a=mid:audio", "a=mid:video"),
        OFFER.replace("a=mid:audio\r\n", ""),
        OFFER.replace("o=- 123 2 IN IP4 127.0.0.1", "o=invalid"),
        OFFER.replace("m=video 9 UDP/TLS/RTP/SAVPF 99", "m=video"),
    ],
)
def test_invalid_offers_are_rejected_before_device_negotiation(offer):
    with pytest.raises(IntercomSDPError):
        OfferPlan(offer)


def test_direction_and_codec_attributes_survive_translation():
    offer = OFFER.replace("a=recvonly", "a=sendrecv", 1)
    plan = OfferPlan(offer)
    wire = plan.combined_offer()
    video, audio = wire.split("m=video", 1)[1].split("m=audio", 1)
    assert "a=recvonly" in video
    assert "a=sendrecv" in audio
    assert "RTP/SAVPF 99" in video
    assert "RTP/SAVPF 0" in audio


def test_answer_with_unexpected_media_ids_is_rejected():
    plan = OfferPlan(OFFER)
    answer = plan.combined_offer().replace("a=group:BUNDLE 0 1\r\n", "").replace("a=mid:0", "a=mid:other")
    with pytest.raises(IntercomSDPError):
        plan.restore_answer(answer)


@pytest.mark.parametrize(
    "challenge",
    [
        None,
        [],
        {"method": "other"},
        {"method": "authenticate", "params": None},
        {"method": "authenticate", "params": ["nonce", "x" * 2049, "10001"]},
    ],
)
async def test_bad_authentication_challenge_closes_its_partial_socket(hass, challenge):
    socket = Socket()
    socket.feed(challenge)
    client = SimpleNamespace(ws_connect=AsyncMock(return_value=socket))
    session = IntercomSession(hass, client, "http://intercom.invalid/", lambda: ("test", "token"), Mock())
    with pytest.raises(IntercomProtocolError):
        await session.open()
    assert socket.closed
    assert session.reader is None
    assert session._close_task.done()


async def test_cancel_during_challenge_releases_the_socket(hass):
    socket = Socket()
    client = SimpleNamespace(ws_connect=AsyncMock(return_value=socket))
    session = IntercomSession(hass, client, "http://intercom.invalid/", lambda: ("test", "token"), Mock())
    task = asyncio.create_task(session.open())
    await asyncio.sleep(0)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    assert task.cancelled()
    await session.close()
    assert socket.closed
    assert session.reader is None


async def test_socket_close_errors_do_not_skip_reader_cleanup(peer, caplog):
    peer.ws.close = AsyncMock(side_effect=RuntimeError("private-token-must-not-leak"))
    await peer.close()
    assert peer.reader.done()
    assert "private-token-must-not-leak" not in caplog.text
