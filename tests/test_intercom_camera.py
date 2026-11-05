"""Entry-owned Intercom discovery, stable identity and state-driven addressing."""

from __future__ import annotations

import asyncio
import base64
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from Crypto.Cipher import AES, PKCS1_v1_5
from Crypto.PublicKey import RSA
from Crypto.Util.Padding import unpad
import pytest
from homeassistant.const import CONF_USERNAME, STATE_UNAVAILABLE, Platform
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_send
from tests.ha_test_helpers import MockConfigEntry
from tests.intercom_helpers import OFFER, NegotiatingSocket
from webrtc_models import RTCIceCandidateInit

import custom_components.loxone as integration
from custom_components.loxone import camera
from custom_components.loxone.const import DOMAIN, LOXONE_PLATFORMS
from custom_components.loxone.intercom.tokens import LOXONE_EPOCH_TIMESTAMP
from homeassistant.util import dt as dt_util

MODERN_HA = pytest.mark.skipif(not camera._SUPPORTS_INTERCOM, reason="Native Intercom camera requires HA 2026.11")


def structure():
    """Provide two native devices, a duplicate block, and unrelated controls."""
    front = {
        "name": "Front door",
        "type": "IntercomV2",
        "uuidAction": "front-control",
        "room": "hall",
        "cat": "access",
        "details": {"deviceUuid": "front-hardware", "deviceType": 1, "serialNr": "TEST-FRONT"},
        "states": {"address": "front-address", "deviceState": "front-online", "version": "front-version"},
    }
    rear = deepcopy(front)
    rear.update(name="Rear door", uuidAction="rear-control")
    rear["details"] = {"deviceUuid": "rear-hardware", "deviceType": 1}
    rear["states"] = {"address": "rear-address", "deviceState": "rear-online"}
    legacy = deepcopy(front)
    legacy.update(type="Intercom", uuidAction="legacy-control")
    custom = deepcopy(front)
    custom["details"] = {"deviceUuid": "custom-hardware", "deviceType": 0}
    trust = deepcopy(front)
    trust["details"] = {"deviceUuid": "trust-hardware", "trustAddress": "another-miniserver"}
    return {
        "rooms": {"hall": {"name": "Hall"}},
        "cats": {"access": {"name": "Access"}},
        "controls": {
            "front": front,
            "front-duplicate": deepcopy(front),
            "rear": rear,
            "legacy": legacy,
            "custom": custom,
            "trust": trust,
            "switch": {"type": "Switch", "uuidAction": "switch-control"},
        },
    }


@pytest.fixture
async def setup_cameras(hass, enable_custom_integrations, monkeypatch):
    """Use HA's actual entity/device registries while mocking only the Miniserver."""
    coordinators = {}
    created = {}
    entries = []
    original_factory = camera.LoxoneIntercomCamera

    def capture(coordinator, entry, control, uuid):
        entity = original_factory(coordinator, entry, control, uuid)
        created.setdefault(entry.entry_id, []).append(entity)
        return entity

    async def setup_entry(hass, entry):
        coordinator = coordinators[entry.entry_id]
        hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
        await hass.config_entries.async_forward_entry_setups(entry, [Platform.CAMERA])
        return True

    monkeypatch.setattr(camera, "LoxoneIntercomCamera", capture)
    monkeypatch.setattr(integration, "async_setup_entry", setup_entry)

    async def add(*, serial="MS-A", unique_id=None, config=None, username="test-a", token="token-a", cached=None):
        entry = MockConfigEntry(
            domain=DOMAIN,
            title=serial or "Miniserver",
            unique_id=serial or unique_id,
            version=4,
            options={CONF_USERNAME: username},
            data={},
        )
        current_token = {"token": token}
        coordinator = SimpleNamespace(
            config_entry=entry,
            connection_available=True,
            listeners=[],
            _listening_task=None,
            intercom_state_values=dict(cached or {}),
            async_cleanup=AsyncMock(),
            api=SimpleNamespace(
                get_token_dict=lambda: dict(current_token),
                close=AsyncMock(),
                async_intercom_token=AsyncMock(
                    return_value={
                        "token": "intercom-" + token,
                        "validUntil": dt_util.utcnow().timestamp() - LOXONE_EPOCH_TIMESTAMP + 3600,
                    }
                ),
            ),
            miniserver=SimpleNamespace(
                serial=serial, lox_config=SimpleNamespace(json=config if config is not None else structure())
            ),
        )
        coordinator.current_token = current_token

        async def cleanup():
            if getattr(coordinator, "intercom_tokens", None) is not None:
                await coordinator.intercom_tokens.async_close()
                coordinator.intercom_tokens = None

        coordinator.async_cleanup.side_effect = cleanup
        coordinators[entry.entry_id] = coordinator
        entry.add_to_hass(hass)
        entries.append(entry)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        entities = created.get(entry.entry_id, [])
        # Duplicate blocks are filtered before registration, so find the registered instances.
        entities = [entity for entity in entities if getattr(entity, "hass", None) is hass]
        return entry, coordinator, entities

    yield add

    for entry in reversed(entries):
        if entry.entry_id in hass.data.get(DOMAIN, {}):
            await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def feed(hass, entry, **states):
    async_dispatcher_send(hass, integration.state_update_signal(entry.entry_id), states)
    await hass.async_block_till_done()


def front(entities):
    return next(entity for entity in entities if entity.unique_id.endswith("front-hardware_camera"))


def test_platform_is_registered():
    assert Platform.CAMERA in LOXONE_PLATFORMS


@pytest.mark.parametrize(
    ("address", "expected"),
    [
        ("192.0.2.10", "http://192.0.2.10/"),
        ("192.0.2.10:8080", "http://192.0.2.10:8080/"),
        ("http://192.0.2.10/", "http://192.0.2.10/"),
        ("https://intercom.local", "https://intercom.local/"),
        ("2001:db8::1", "http://[2001:db8::1]/"),
        ("[2001:db8::1]:8080", "http://[2001:db8::1]:8080/"),
        (None, None),
        ("", None),
        ("unknown", None),
        ("0.0.0.0", None),
        ("::", None),
        ("http://user:password@192.0.2.10", None),
        ("http://192.0.2.10/path", None),
        ("http://192.0.2.10/?token=value", None),
        ("ws://192.0.2.10", None),
        ("not an address", None),
        ("192.0.2.10:99999", None),
    ],
)
def test_advertised_address_validation(address, expected):
    assert camera.intercom_url(address) == expected


@MODERN_HA
async def test_discovers_devices_and_groups_under_the_owning_miniserver(hass, setup_cameras, caplog):
    entry, coordinator, entities = await setup_cameras()
    assert sorted(entity.unique_id for entity in entities) == [
        "MS-A_front-hardware_camera",
        "MS-A_rear-hardware_camera",
    ]
    assert "does not generate unique IDs" not in caplog.text
    entity = front(entities)
    registry = er.async_get(hass)
    registered = registry.async_get(entity.entity_id)
    assert registered.config_entry_id == entry.entry_id
    device = dr.async_get(hass).async_get(registered.device_id)
    assert device.name == "Front door"
    assert device.serial_number == "TEST-FRONT"
    assert device.model == "Intercom Gen 2"
    assert dr.async_get(hass).async_get(device.via_device_id).identifiers == {(DOMAIN, "MS-A")}
    assert ar.async_get(hass).async_get_area(device.area_id).name == "Hall"
    await feed(hass, entry, **{"front-address": "192.0.2.10", "front-online": 1.0})
    assert hass.states.get(entity.entity_id).attributes["category"] == "Access"
    assert coordinator.miniserver.lox_config.json == structure()


@MODERN_HA
@pytest.mark.parametrize("unique_id", [None, "configured-miniserver"])
async def test_missing_serial_keeps_parent_and_camera_identity_across_reload(hass, setup_cameras, unique_id):
    entry, _, entities = await setup_cameras(serial=None, unique_id=unique_id)
    entity = front(entities)
    identity = f"{unique_id or entry.entry_id}_front-hardware_camera"
    assert entity.unique_id == identity
    registry = er.async_get(hass)
    registered = registry.async_get(entity.entity_id)
    device_registry = dr.async_get(hass)
    device = device_registry.async_get(registered.device_id)
    parent = device_registry.async_get(device.via_device_id)
    assert parent.identifiers == {(DOMAIN, unique_id or entry.entry_id)}
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    reloaded = registry.async_get(entity.entity_id)
    assert reloaded.unique_id == identity
    assert reloaded.device_id == device.id
    assert device_registry.async_get(device.id).via_device_id == parent.id


@MODERN_HA
async def test_camera_enabled_after_initial_push_reads_entry_metadata(hass, setup_cameras):
    _, _, entities = await setup_cameras(cached={"front-address": "192.0.2.10", "front-online": 1.0})
    assert front(entities).available
    assert front(entities)._address == "http://192.0.2.10/"


@MODERN_HA
async def test_closing_while_waiting_for_a_token_never_opens_a_device_session(hass, setup_cameras, monkeypatch):
    entry, coordinator, entities = await setup_cameras()
    entity = front(entities)
    await feed(hass, entry, **{"front-address": "192.0.2.10", "front-online": 1.0})
    entered = asyncio.Event()

    async def waiting(*args):
        entered.set()
        await asyncio.Future()

    coordinator.api.async_intercom_token.side_effect = waiting
    monkeypatch.setattr(camera, "OfferPlan", lambda _: SimpleNamespace())
    factory = Mock()
    monkeypatch.setattr(camera, "IntercomSession", factory)
    task = asyncio.create_task(entity.async_handle_async_webrtc_offer("offer", "pending", Mock()))
    await entered.wait()
    entity.close_webrtc_session("pending")
    await asyncio.gather(task, return_exceptions=True)
    assert task.cancelled()
    factory.assert_not_called()
    assert not entity._sessions


@MODERN_HA
async def test_device_token_rejection_retries_once_with_fresh_credentials(hass, setup_cameras, monkeypatch):
    entry, coordinator, entities = await setup_cameras()
    entity = front(entities)
    await feed(hass, entry, **{"front-address": "192.0.2.10", "front-online": 1.0})
    plan = SimpleNamespace(has_audio=False, video_offer=lambda: "wire-offer", restore_answer=lambda _: "browser-answer")
    monkeypatch.setattr(camera, "OfferPlan", lambda _: plan)
    used = []
    first = SimpleNamespace(
        open=AsyncMock(side_effect=camera.IntercomAuthenticationError("rejected")), close=AsyncMock()
    )
    second = SimpleNamespace(
        open=AsyncMock(),
        close=AsyncMock(),
        release_candidates=Mock(),
        request=AsyncMock(side_effect=[{"callState": 0}, {"sdp": "wire-answer"}]),
    )
    instances = iter((first, second))

    def factory(hass, client, url, credentials, send_message):
        used.append(credentials())
        return next(instances)

    monkeypatch.setattr(camera, "IntercomSession", factory)
    coordinator.api.async_intercom_token.side_effect = [
        {"token": "old", "validUntil": dt_util.utcnow().timestamp() - LOXONE_EPOCH_TIMESTAMP + 3600},
        {"token": "replacement", "validUntil": dt_util.utcnow().timestamp() - LOXONE_EPOCH_TIMESTAMP + 3600},
    ]
    send = Mock()
    await entity.async_handle_async_webrtc_offer("offer", "retry", send)
    assert used == [("test-a", "old"), ("test-a", "replacement")]
    first.close.assert_awaited_once()
    assert send.call_args.args[0].answer == "browser-answer"


@MODERN_HA
async def test_browser_candidates_arriving_during_token_issuance_are_forwarded(hass, setup_cameras, monkeypatch):
    entry, coordinator, entities = await setup_cameras()
    entity = front(entities)
    await feed(hass, entry, **{"front-address": "192.0.2.10", "front-online": 1.0})
    entered, release, answer_ready = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def issue(*args):
        entered.set()
        await release.wait()
        return {"token": "dedicated", "validUntil": dt_util.utcnow().timestamp() - LOXONE_EPOCH_TIMESTAMP + 3600}

    coordinator.api.async_intercom_token.side_effect = issue
    plan = SimpleNamespace(has_audio=False, video_offer=lambda: "offer", restore_answer=lambda _: "answer")
    monkeypatch.setattr(camera, "OfferPlan", lambda _: plan)
    session = SimpleNamespace(
        open=AsyncMock(),
        close=AsyncMock(),
        answer_ready=answer_ready,
        release_candidates=Mock(side_effect=answer_ready.set),
        send_candidate=AsyncMock(),
        request=AsyncMock(side_effect=[{"callState": 0}, {"sdp": "answer"}]),
    )
    monkeypatch.setattr(camera, "IntercomSession", Mock(return_value=session))
    task = asyncio.create_task(entity.async_handle_async_webrtc_offer("offer", "early", Mock()))
    await entered.wait()
    candidate = SimpleNamespace(candidate="browser-ice")
    await entity.async_on_webrtc_candidate("early", candidate)
    session.send_candidate.assert_not_awaited()
    release.set()
    await task
    session.send_candidate.assert_awaited_once_with(candidate)
    assert not entity._pending_candidates


@MODERN_HA
async def test_waits_for_address_and_online_state_then_updates_firmware(hass, setup_cameras):
    entry, _, entities = await setup_cameras()
    entity = front(entities)
    assert hass.states.get(entity.entity_id).state == STATE_UNAVAILABLE
    await feed(hass, entry, **{"front-address": "192.0.2.10"})
    assert not entity.available
    await feed(hass, entry, **{"front-online": 1.0, "front-version": "17.00.06.01"})
    assert entity.available
    assert entity._address == "http://192.0.2.10/"
    assert dr.async_get(hass).async_get(entity.device_entry.id).sw_version == "17.00.06.01"


@MODERN_HA
async def test_dhcp_change_keeps_registry_identity_and_closes_the_old_session(hass, setup_cameras):
    entry, _, entities = await setup_cameras()
    entity = front(entities)
    await feed(hass, entry, **{"front-address": "192.0.2.10", "front-online": 1.0})
    old = SimpleNamespace(close=AsyncMock())
    entity._sessions["old-peer"] = old
    entity_id, device_id, unique_id = entity.entity_id, entity.device_entry.id, entity.unique_id
    await feed(hass, entry, **{"front-address": "192.0.2.20"})
    assert entity._address == "http://192.0.2.20/"
    assert (entity.entity_id, entity.device_entry.id, entity.unique_id) == (entity_id, device_id, unique_id)
    old.close.assert_awaited_once()


@MODERN_HA
async def test_two_miniservers_do_not_share_state_or_authentication(hass, setup_cameras):
    entry_a, co_a, entities_a = await setup_cameras()
    _, co_b, entities_b = await setup_cameras(serial="MS-B", username="test-b", token="token-b")
    a, b = front(entities_a), front(entities_b)
    # Deliberately identical control and state UUIDs in both structure files.
    await feed(hass, entry_a, **{"front-address": "192.0.2.10", "front-online": 1.0})
    assert a.available
    assert not b.available
    assert a.unique_id != b.unique_id
    assert a.device_entry.id != b.device_entry.id
    assert await a._credentials() == ("test-a", "intercom-token-a")
    assert await b._credentials() == ("test-b", "intercom-token-b")
    co_a.current_token["token"] = "refreshed-token-a"
    assert await a._credentials() == ("test-a", "intercom-token-a")
    assert co_b.current_token == {"token": "token-b"}


@MODERN_HA
async def test_disconnect_requires_fresh_address_and_device_state(hass, setup_cameras):
    entry, coordinator, entities = await setup_cameras()
    entity = front(entities)
    await feed(hass, entry, **{"front-address": "192.0.2.10", "front-online": 1.0})
    old = SimpleNamespace(close=AsyncMock())
    entity._sessions["old-peer"] = old
    coordinator.connection_available = False
    async_dispatcher_send(hass, integration.connection_state_signal(entry.entry_id))
    await hass.async_block_till_done()
    assert not entity.available
    old.close.assert_awaited_once()
    coordinator.connection_available = True
    async_dispatcher_send(hass, integration.connection_state_signal(entry.entry_id))
    await hass.async_block_till_done()
    assert not entity.available
    await feed(hass, entry, **{"front-address": "192.0.2.20", "front-online": 1.0})
    assert entity.available


@MODERN_HA
async def test_offline_and_invalid_address_are_unavailable(hass, setup_cameras):
    entry, _, entities = await setup_cameras()
    entity = front(entities)
    await feed(hass, entry, **{"front-address": "192.0.2.10", "front-online": 1.0})
    await feed(hass, entry, **{"front-online": 2.0})
    assert not entity.available
    await feed(hass, entry, **{"front-online": 1.0, "front-address": "http://invalid.local/path"})
    assert not entity.available


@MODERN_HA
async def test_reload_reuses_entities_and_removes_old_listeners(hass, setup_cameras):
    entry, _, entities = await setup_cameras()
    old = front(entities)
    entity_id, device_id, unique_id = old.entity_id, old.device_entry.id, old.unique_id
    writer = Mock()
    old.async_write_ha_state = writer
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    writer.reset_mock()
    await feed(hass, entry, **{"front-address": "192.0.2.20", "front-online": 1.0})
    writer.assert_not_called()
    registered = er.async_get(hass).async_get_entity_id("camera", DOMAIN, unique_id)
    assert registered == entity_id
    assert er.async_get(hass).async_get(entity_id).device_id == device_id
    assert len([e for e in er.async_get(hass).entities.values() if e.platform == DOMAIN]) == 2


async def test_older_ha_skips_only_the_new_camera_platform(hass, setup_cameras, monkeypatch):
    monkeypatch.setattr(camera, "_SUPPORTS_INTERCOM", False)
    entry, _, entities = await setup_cameras()
    assert not entities
    assert entry.entry_id in hass.data[DOMAIN]


async def test_miniserver_without_intercoms_has_no_cameras(hass, setup_cameras):
    entry, _, entities = await setup_cameras(config={"controls": {}})
    assert not entities
    assert entry.entry_id in hass.data[DOMAIN]


@MODERN_HA
async def test_busy_audio_does_not_start_or_hang_up_another_call(hass, setup_cameras, monkeypatch):
    entry, _, entities = await setup_cameras()
    entity = front(entities)
    await feed(hass, entry, **{"front-address": "192.0.2.10", "front-online": 1.0})
    session = SimpleNamespace(open=AsyncMock(), close=AsyncMock(), request=AsyncMock(return_value={"callState": 1}))
    monkeypatch.setattr(camera, "IntercomSession", Mock(return_value=session))
    sender = Mock()
    await entity.async_handle_async_webrtc_offer(OFFER, "busy", sender)
    assert sender.call_args.args[0].code == "intercom_busy"
    session.request.assert_awaited_once_with("info")
    session.close.assert_awaited_once()
    assert not entity._sessions
    assert not entity._send_messages


@MODERN_HA
async def test_unexpected_errors_never_expose_transport_payloads(hass, setup_cameras, monkeypatch, caplog):
    entry, _, entities = await setup_cameras()
    entity = front(entities)
    await feed(hass, entry, **{"front-address": "192.0.2.10", "front-online": 1.0})
    session = SimpleNamespace(
        open=AsyncMock(), close=AsyncMock(), request=AsyncMock(side_effect=ValueError("secret-token-and-sdp"))
    )
    monkeypatch.setattr(camera, "IntercomSession", Mock(return_value=session))
    sender = Mock()
    await entity.async_handle_async_webrtc_offer(OFFER, "error", sender)
    error = sender.call_args.args[0]
    assert error.code == "intercom_negotiation_failed"
    assert "secret-token-and-sdp" not in str(error.as_dict())
    assert "secret-token-and-sdp" not in caplog.text
    session.close.assert_awaited_once()
    assert not entity._offer_tasks
    assert not entity._pending_candidates
    assert not entity._send_messages


@MODERN_HA
async def test_established_signalling_loss_reports_error_and_removes_session(hass, setup_cameras):
    entry, _, entities = await setup_cameras()
    entity = front(entities)
    sender = Mock()
    current = SimpleNamespace(close=AsyncMock(), failure=camera.IntercomConnectionError("Intercom connection closed"))
    entity._sessions["lost"] = current
    entity._send_messages["lost"] = sender
    entity._session_disconnected("lost", current)
    await hass.async_block_till_done()
    assert sender.call_args.args[0].code == "intercom_connection_lost"
    current.close.assert_awaited_once()
    assert not entity._sessions
    assert not entity._send_messages


@MODERN_HA
async def test_old_connection_callback_cannot_close_a_replacement(hass, setup_cameras):
    _, _, entities = await setup_cameras()
    entity = front(entities)
    old = SimpleNamespace(failure=camera.IntercomConnectionError("Old connection ended"))
    current = SimpleNamespace(close=AsyncMock())
    entity._sessions["reused"] = current
    entity._send_messages["reused"] = Mock()
    entity._session_disconnected("reused", old)
    assert entity._sessions["reused"] is current
    current.close.assert_not_awaited()
    entity._send_messages["reused"].assert_not_called()


@MODERN_HA
async def test_whole_offer_timeout_cleans_state_without_cancelling_shared_auth(hass, setup_cameras, monkeypatch):
    entry, coordinator, entities = await setup_cameras()
    entity = front(entities)
    await feed(hass, entry, **{"front-address": "192.0.2.10", "front-online": 1.0})
    entered = asyncio.Event()

    async def stalled(*args):
        entered.set()
        await asyncio.Future()

    coordinator.api.async_intercom_token.side_effect = stalled
    monkeypatch.setattr(camera, "NEGOTIATION_TIMEOUT", 0.05)
    sender = Mock()
    await asyncio.wait_for(entity.async_handle_async_webrtc_offer(OFFER, "slow", sender), 1)
    assert entered.is_set()
    assert sender.call_args.args[0].code == "intercom_timeout"
    assert not coordinator.intercom_tokens._credential_task.cancelled()
    assert not entity._sessions
    assert not entity._offer_tasks
    assert not entity._pending_candidates
    assert not entity._send_messages


@MODERN_HA
@pytest.mark.parametrize("reject_initial_token", [False, True])
async def test_real_signalling_reauthenticates_and_recovers_after_socket_loss(
    hass, setup_cameras, monkeypatch, reject_initial_token
):
    """Use the actual camera, token manager, crypto, SDP and reader over a framed fake socket."""
    entry, coordinator, entities = await setup_cameras()
    entity = front(entities)
    identity = entity.entity_id, entity.unique_id, entity.device_entry.id
    hass.config_entries.async_update_entry(entry, data={"token": "main-app-token"})
    expiry = dt_util.utcnow().timestamp() - LOXONE_EPOCH_TIMESTAMP + 3600
    coordinator.api.async_intercom_token.side_effect = [
        {"token": "dedicated-first", "validUntil": expiry},
        {"token": "dedicated-replacement", "validUntil": expiry},
    ]
    key = await hass.async_add_executor_job(RSA.generate, 2048)
    challenge = ["synthetic-challenge", format(key.n, "x"), format(key.e, "x")]
    sockets = []

    async def connect(*args, **kwargs):
        peer = NegotiatingSocket(challenge, reject_auth=reject_initial_token and not sockets)
        sockets.append(peer)
        return peer

    client = SimpleNamespace(ws_connect=AsyncMock(side_effect=connect))
    monkeypatch.setattr(camera, "async_get_clientsession", lambda _: client)
    await feed(hass, entry, **{"front-address": "192.0.2.10", "front-online": 1.0})
    sender = Mock()
    offer = OFFER.replace("a=mid:audio\r\na=recvonly", "a=mid:audio\r\na=sendrecv")
    await entity.async_handle_async_webrtc_offer(offer, "viewer", sender)
    messages = [call.args[0] for call in sender.call_args_list]
    assert len(messages) == 2
    answer, candidate_message = messages
    assert answer.answer.index("m=audio") < answer.answer.index("m=video")
    assert "a=mid:audio\r\na=sendrecv" in answer.answer
    assert (candidate_message.candidate.sdp_mid, candidate_message.candidate.sdp_m_line_index) == ("audio", 0)
    peer = sockets[-1]
    calls = [message["params"] for message in peer.sent if message.get("method") == "call"]
    assert [params[1:] for params in calls] == [["new", False, 0], ["add_audio", False, 0]]
    assert "m=audio" not in calls[0][0]["sdp"]
    assert calls[1][0]["sdp"].index("m=video") < calls[1][0]["sdp"].index("m=audio")
    await entity.async_on_webrtc_candidate("viewer", RTCIceCandidateInit("candidate:browser-audio", sdp_mid="audio"))
    assert peer.sent[-1]["params"] == ["candidate:browser-audio", 1]

    lost_session = entity._sessions["viewer"]
    peer.incoming.put_nowait(None)
    # HA may eagerly start cleanup and cancel the reader from its disconnect callback.
    await asyncio.wait_for(asyncio.gather(lost_session.reader, return_exceptions=True), 1)
    await hass.async_block_till_done()
    assert isinstance(lost_session.failure, camera.IntercomConnectionError)
    assert sender.call_args.args[0].code == "intercom_connection_lost"
    assert not entity._sessions
    assert peer.closed
    assert not any(message.get("method") == "hangup" for message in peer.sent)
    assert entity.available

    retry_sender = Mock()
    await entity.async_handle_async_webrtc_offer(offer, "viewer", retry_sender)
    assert any(hasattr(call.args[0], "answer") for call in retry_sender.call_args_list)
    assert (entity.entity_id, entity.unique_id, entity.device_entry.id) == identity
    assert coordinator.api.async_intercom_token.await_count == (2 if reject_initial_token else 1)
    expected_tokens = (
        ["dedicated-first", "dedicated-replacement", "dedicated-replacement"]
        if reject_initial_token
        else ["dedicated-first", "dedicated-first"]
    )
    for socket, expected in zip(sockets, expected_tokens, strict=True):
        username, encrypted_key, encrypted_token = socket.sent[0]["result"]["data"]
        envelope = PKCS1_v1_5.new(key).decrypt(base64.b64decode(encrypted_key), b"invalid").decode()
        aes_key, iv, nonce = envelope.split(":")
        assert username == "test-a"
        assert nonce == "synthetic-challenge"
        clear = AES.new(bytes.fromhex(aes_key), AES.MODE_CBC, bytes.fromhex(iv)).decrypt(
            base64.b64decode(encrypted_token)
        )
        assert unpad(clear, AES.block_size).decode() == expected
    assert entry.data["token"] == "main-app-token"
    assert entry.data["intercom_auth"]["permission"] == 0
    entity.close_webrtc_session("viewer")
    await hass.async_block_till_done()
    assert [message.get("method") for message in sockets[-1].sent].count("hangup") == 1
    assert all(socket.closed and socket.close_count == 1 for socket in sockets)
    assert not entity._sessions
    assert not entity._offer_tasks
    assert not entity._pending_candidates
    assert not entity._send_messages
