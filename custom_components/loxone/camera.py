"""Discover native Intercom Gen 2 cameras from a PyLoxone config entry."""

from __future__ import annotations

import asyncio
from ipaddress import ip_address
import logging
import re
from typing import TYPE_CHECKING

from homeassistant.components import camera as camera_platform
from homeassistant.components.camera import (
    Camera,
    CameraEntityFeature,
)
from homeassistant.core import callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo
from yarl import URL

from . import connection_state_signal, state_update_signal
from .const import DOMAIN
from .compat import supports_intercom
from .intercom.device import IntercomDevice, intercom_devices
from .intercom.errors import IntercomBusyError, IntercomConnectionError, IntercomError, IntercomProtocolError
from .pyloxone_api.exceptions import IntercomTokenError

_SUPPORTS_INTERCOM = supports_intercom()
if _SUPPORTS_INTERCOM:
    from homeassistant.components.camera import WebRTCAnswer, WebRTCClientConfiguration, WebRTCError
    from webrtc_models import RTCConfiguration, RTCIceServer

    from .intercom.sdp import OfferPlan
    from .intercom.signaling import IntercomAuthenticationError, IntercomSession
    from .intercom.tokens import IntercomTokenManager

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import LoxoneCoordinator

_LOGGER = logging.getLogger(__name__)
NEGOTIATION_TIMEOUT = 45
_HOSTNAME = re.compile(r"[a-zA-Z0-9](?:[a-zA-Z0-9.-]*[a-zA-Z0-9])?")


def intercom_url(value: object) -> str | None:
    """Normalize an advertised device address without accepting URL credentials or paths."""
    if not isinstance(value, str) or not (address := value.strip()):
        return None
    try:
        parsed_ip = ip_address(address)
    except ValueError:
        pass
    else:
        if parsed_ip.is_unspecified:
            return None
        return str(URL.build(scheme="http", host=str(parsed_ip), path="/"))
    try:
        url = URL(address if "://" in address else "http://" + address)
        host = url.host
        if (
            url.scheme not in {"http", "https"}
            or not host
            or url.user is not None
            or url.password is not None
            or url.path not in {"", "/"}
            or url.query_string
            or url.fragment
            or url.port == 0
        ):
            return None
        try:
            parsed_ip = ip_address(host)
        except ValueError:
            if host.lower() in {"unknown", "none", "null"} or not _HOSTNAME.fullmatch(host):
                return None
        else:
            if parsed_ip.is_unspecified:
                return None
    except (
        ValueError,
        UnicodeError,
    ):
        return None
    return str(url.with_path("/"))


async def async_setup_entry(
    hass: HomeAssistant, config_entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Create one camera per native Intercom device owned by this entry."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]
    structure = coordinator.miniserver.lox_config.json or {}
    controls = [
        (uuid, control)
        for uuid, control in structure.get("controls", {}).items()
        if isinstance(control, dict) and control.get("type") == "IntercomV2"
    ]
    if not controls:
        return
    # The rest of PyLoxone remains loadable with its existing HA minimum.
    if not _SUPPORTS_INTERCOM:
        _LOGGER.info("Native Intercom cameras require Home Assistant 2026.11 or newer")
        return
    entities = []
    for device in intercom_devices(coordinator, config_entry):
        camera = LoxoneIntercomCamera(coordinator, config_entry, device.control, device.uuid)
        entities.append(camera)
    if entities:
        entities[0]._device.ensure_parent(hass)
    if entities and getattr(coordinator, "intercom_tokens", None) is None:
        coordinator.intercom_tokens = IntercomTokenManager(hass, config_entry, coordinator.api)
    async_add_entities(entities)


class LoxoneIntercomCamera(Camera):
    """An entry-owned Intercom with a UUID identity and a dynamic network address."""

    _attr_supported_features = CameraEntityFeature.STREAM
    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_name = None

    def __init__(self, coordinator: LoxoneCoordinator, entry: ConfigEntry, control: dict, uuid: str) -> None:
        """Keep configuration and authentication tied to the owning Miniserver."""
        super().__init__()
        self._coordinator = coordinator
        self._entry = entry
        self._device = IntercomDevice(coordinator, entry, control, uuid)
        self._control_uuid = control.get("uuidAction") or uuid
        self._states = dict(self._device.states)
        self._details = dict(control.get("details") or {})
        self._structure = coordinator.miniserver.lox_config.json or {}
        self._device_key = self._device.key
        self._attr_unique_id = f"{self._device_key}_camera"
        self._device_name = control.get("name") or self._details.get("deviceName") or "Intercom"
        self._room = self._device.room
        self._category = self._device.category
        self._address: str | None = None
        self._device_state: object = None
        self._firmware: str | None = None
        self._sessions: dict[str, IntercomSession] = {}
        self._offer_tasks: dict[str, asyncio.Task] = {}
        self._pending_candidates: dict[str, list] = {}
        self._send_messages: dict[str, object] = {}
        self._closing_tasks: set[asyncio.Task] = set()
        if _SUPPORTS_INTERCOM:
            self._attr_camera_entity_capabilities = camera_platform.CameraEntityCapabilities(two_way_audio=True)
        self._attr_extra_state_attributes = {
            "uuid": self._control_uuid,
            "platform": DOMAIN,
            "device_type": "IntercomV2",
            "room": self._room,
            "category": self._category,
        }

    @property
    def device_info(self) -> DeviceInfo:
        """Associate the camera with its hardware and parent Miniserver."""
        return self._device.device_info(self.hass, self._firmware)

    @property
    def available(self) -> bool:
        """Wait for the device address and online state from the owning connection."""
        online = not self._states.get("deviceState") or self._device_state in (1, "1", "1.0")
        return bool(self._address and online and self._coordinator.connection_available)

    async def async_added_to_hass(self) -> None:
        """Listen to Miniserver state events and connection changes until removal."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                state_update_signal(self._entry.entry_id),
                self._handle_states,
            )
        )
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                connection_state_signal(self._entry.entry_id),
                self._connection_changed,
            )
        )
        self._handle_states(self._coordinator.intercom_state_values)

    @callback
    def _connection_changed(self) -> None:
        if not self._coordinator.connection_available:
            self._address = None
            self._device_state = None
            self._close_sessions()
        self.async_write_ha_state()

    @callback
    def _handle_states(self, states: dict) -> None:
        changed = False
        if (uuid := self._states.get("address")) and uuid in states:
            address = intercom_url(states[uuid])
            if address != self._address:
                self._close_sessions()
                self._address = address
            changed = True
        if (uuid := self._states.get("deviceState")) and uuid in states:
            self._device_state = states[uuid]
            if self._device_state not in (1, "1", "1.0"):
                self._close_sessions()
            changed = True
        if (uuid := self._states.get("version")) and uuid in states:
            value = states[uuid]
            self._firmware = value if isinstance(value, str) and value else None
            device = dr.async_get(self.hass).async_get_device_by_identifier(
                (DOMAIN, self._device_key), self._entry.entry_id
            )
            if device is not None:
                dr.async_get(self.hass).async_update_device(device.id, sw_version=self._firmware)
            changed = True
        if changed:
            self.async_write_ha_state()

    async def _credentials(self) -> tuple[str, str]:
        """Use only the owning entry's dedicated Intercom token."""
        return await self._coordinator.intercom_tokens.async_credentials()

    async def async_camera_image(self, width=None, height=None):
        """The native WebRTC camera currently supplies live media only."""
        return None

    @callback
    def _async_get_webrtc_client_configuration(self):
        return WebRTCClientConfiguration(
            configuration=RTCConfiguration(
                ice_servers=[
                    RTCIceServer(urls="stun:stun.loxonecloud.com:3478"),
                ]
            )
        )

    async def async_handle_async_webrtc_offer(self, offer_sdp, session_id, send_message):
        """Translate the browser offer on an authenticated device session."""
        session = None
        offer_task = asyncio.current_task()
        self._offer_tasks[session_id] = offer_task
        self._pending_candidates[session_id] = []
        self._send_messages[session_id] = send_message
        try:
            async with asyncio.timeout(NEGOTIATION_TIMEOUT):
                if self._closing_tasks:
                    await asyncio.shield(asyncio.gather(*tuple(self._closing_tasks), return_exceptions=True))
                previous = self._sessions.pop(session_id, None)
                if previous:
                    await previous.close()
                if not self.available:
                    send_message(WebRTCError("intercom_unavailable", "Intercom address or online state is unavailable"))
                    return
                plan = OfferPlan(offer_sdp)
                for attempt in range(2):
                    credentials = await self._credentials()
                    if not self.available:
                        raise IntercomConnectionError("Intercom became unavailable")
                    session = IntercomSession(
                        self.hass,
                        async_get_clientsession(self.hass),
                        self._address,
                        lambda: credentials,
                        send_message,
                    )
                    self._sessions[session_id] = session
                    session.on_disconnect = lambda current=session: self._session_disconnected(session_id, current)
                    session.plan = plan
                    try:
                        await session.open()
                        break
                    except IntercomAuthenticationError:
                        await session.close()
                        await self._coordinator.intercom_tokens.async_invalidate(credentials[1])
                        if attempt:
                            raise
                info = await session.request("info")
                if not isinstance(info, dict):
                    raise IntercomProtocolError("Intercom returned invalid device information")
                if plan.has_audio:
                    call_state = info.get("callState")
                    if call_state in (1, "1") and not isinstance(call_state, bool):
                        raise IntercomBusyError("Intercom audio is in use; close other calls first")
                    if isinstance(call_state, bool) or call_state not in (0, "0"):
                        raise IntercomProtocolError("Intercom audio call state is unavailable")
                answer = await session.request(
                    "call",
                    [
                        {"type": "offer", "sdp": plan.video_offer()},
                        "new",
                        False,
                        0,
                    ],
                )
                if plan.has_audio:
                    answer = await session.request(
                        "call",
                        [
                            {"type": "offer", "sdp": plan.combined_offer()},
                            "add_audio",
                            False,
                            0,
                        ],
                    )
                if not isinstance(answer, dict) or not isinstance(answer.get("sdp"), str):
                    raise IntercomProtocolError("Intercom returned an invalid media answer")
                send_message(WebRTCAnswer(plan.restore_answer(answer["sdp"])))
                session.release_candidates()
                for candidate in self._pending_candidates.pop(session_id, []):
                    await session.send_candidate(candidate)
        except asyncio.CancelledError:
            if self._sessions.get(session_id) is session:
                self._sessions.pop(session_id, None)
            if session is not None:
                await asyncio.shield(session.close())
            raise
        except Exception as error:
            _LOGGER.warning("Intercom negotiation failed: %s", type(error).__name__)
            self._send_error(session_id, error)
            if self._sessions.get(session_id) is session:
                self._sessions.pop(session_id, None)
            if session is not None:
                await session.close()
        finally:
            self._pending_candidates.pop(session_id, None)
            if self._offer_tasks.get(session_id) is offer_task:
                self._offer_tasks.pop(session_id, None)
            if session_id not in self._sessions:
                self._send_messages.pop(session_id, None)

    @callback
    def _send_error(self, session_id, error):
        """Only expose integration-owned messages, never raw peer/transport text."""
        if isinstance(error, IntercomError):
            code, message = error.code, str(error)
        elif isinstance(error, TimeoutError):
            code, message = "intercom_timeout", "Intercom did not respond in time"
        elif isinstance(error, IntercomTokenError):
            code, message = (
                "intercom_authentication_failed",
                "Could not authenticate the Intercom; check the PyLoxone account",
            )
        else:
            code, message = "intercom_negotiation_failed", "Could not establish the Intercom stream"
        sender = self._send_messages.get(session_id)
        if sender is not None:
            try:
                sender(WebRTCError(code, message))
            except Exception as callback_error:
                _LOGGER.debug("Intercom frontend connection closed (%s)", type(callback_error).__name__)

    @callback
    def _session_disconnected(self, session_id, session):
        if self._sessions.get(session_id) is not session or session_id in self._offer_tasks:
            return  # An opening offer reports its own error and performs cleanup.
        self._send_error(session_id, session.failure or IntercomConnectionError("Intercom connection closed"))
        self.close_webrtc_session(session_id)

    async def async_on_webrtc_candidate(self, session_id, candidate):
        session = self._sessions.get(session_id)
        if session_id in self._pending_candidates:
            candidates = self._pending_candidates[session_id]
            if len(candidates) < 128:
                candidates.append(candidate)
            else:
                self._send_error(session_id, IntercomProtocolError("Too many browser ICE candidates"))
                self.close_webrtc_session(session_id)
            return
        if session is not None:
            try:
                await session.send_candidate(candidate)
            except Exception as error:
                _LOGGER.warning("Intercom ICE exchange failed")
                if self._sessions.get(session_id) is session:
                    self._send_error(session_id, error)
                    self.close_webrtc_session(session_id)

    @callback
    def close_webrtc_session(self, session_id):
        self._send_messages.pop(session_id, None)
        self._pending_candidates.pop(session_id, None)
        offer_task = self._offer_tasks.pop(session_id, None)
        if offer_task is not None and offer_task is not asyncio.current_task():
            offer_task.cancel()
            self._closing_tasks.add(offer_task)
            offer_task.add_done_callback(self._closing_tasks.discard)
        session = self._sessions.pop(session_id, None)
        if session:
            task = self.hass.async_create_task(session.close(), "loxone_intercom_hangup")
            self._closing_tasks.add(task)
            task.add_done_callback(self._closing_tasks.discard)

    @callback
    def _close_sessions(self) -> None:
        for session_id in set(self._sessions) | set(self._offer_tasks):
            self.close_webrtc_session(session_id)

    async def async_will_remove_from_hass(self) -> None:
        """Release only this entity's media sessions and inherited subscriptions."""
        self._close_sessions()
        if self._closing_tasks:
            await asyncio.gather(*tuple(self._closing_tasks), return_exceptions=True)
        await super().async_will_remove_from_hass()
