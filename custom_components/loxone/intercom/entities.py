"""Miniserver-backed Intercom sensors and actions for every supported HA version."""

from __future__ import annotations

import asyncio
import json
import logging

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.components.button import ButtonEntity
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.components.switch import SwitchEntity
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity, EntityCategory

from .. import connection_state_signal, state_update_signal
from ..const import DOMAIN
from .device import intercom_devices, registered_device

_LOGGER = logging.getLogger(__name__)
COMMAND_TIMEOUT = 10
MAX_REPLIES = 32
DEVICE_STATES = {0: "unknown", 1: "online", 2: "rebooting", 3: "initializing"}


def binary_value(value):
    """Avoid treating malformed or missing feedback as an enabled state."""
    if value in (0, "0", "0.0", False):
        return False
    if value in (1, "1", "1.0", True):
        return True
    return None


def device_state(value):
    if isinstance(value, bool):
        return None
    for number in DEVICE_STATES:
        if value in (number, str(number), f"{number}.0"):
            return number
    return None


def voice_replies(value):
    """Preserve preset indexes, including empty slots; bound state-driven discovery."""
    if isinstance(value, str):
        if len(value) > 65536:
            return []
        try:
            value = json.loads(value)
        except (ValueError, RecursionError):
            return []
    if not isinstance(value, list):
        return []
    if any(text is not None and not isinstance(text, str) for text in value[:MAX_REPLIES]):
        return []
    return [text if isinstance(text, str) else "" for text in value[:MAX_REPLIES]]


class IntercomEntity(Entity):
    """Subscribe to the owning entry and retain no state after its disconnect."""

    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(self, device, key, name, state_key=None):
        super().__init__()
        self.device = device
        self._state_key = state_key
        self._values = {}
        self._attr_unique_id = f"{device.key}_{key}"
        self._attr_name = name
        self._attr_extra_state_attributes = {
            "uuid": device.action_uuid,
            "platform": DOMAIN,
            "device_type": "IntercomV2",
            "room": device.room,
            "category": device.category,
        }

    @property
    def value(self):
        return self._values.get(self.device.states.get(self._state_key))

    @property
    def available(self):
        return self.device.coordinator.connection_available

    @property
    def device_info(self):
        firmware = self._values.get(self.device.states.get("version"))
        return self.device.device_info(self.hass, firmware if isinstance(firmware, str) else None)

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(self.hass, state_update_signal(self.device.entry.entry_id), self._handle_states)
        )
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, connection_state_signal(self.device.entry.entry_id), self._connection_changed
            )
        )
        self._handle_states(self.device.coordinator.intercom_state_values)

    @callback
    def _connection_changed(self):
        if not self.device.coordinator.connection_available:
            self._values.clear()
            self._updated()
        self.async_write_ha_state()

    @callback
    def _handle_states(self, states):
        updates = {uuid: states[uuid] for uuid in self.device.states.values() if uuid in states}
        if not updates:
            return
        self._values.update(updates)
        self._updated()
        firmware = updates.get(self.device.states.get("version"))
        if isinstance(firmware, str) and firmware:
            device = registered_device(self.hass, (DOMAIN, self.device.key), self.device.entry.entry_id)
            if device is not None and device.sw_version != firmware:
                dr.async_get(self.hass).async_update_device(device.id, sw_version=firmware)
        self.async_write_ha_state()

    @callback
    def _updated(self):
        """Update derived attributes after a state push."""


class IntercomRinging(IntercomEntity, BinarySensorEntity):
    """The bell's current ringing state, suitable for state-triggered automations."""

    _attr_icon = "mdi:bell-ring"

    def __init__(self, device):
        super().__init__(device, "ringing", "Ringing", "bell")

    @property
    def is_on(self):
        return binary_value(self.value)

    @property
    def available(self):
        return super().available and self.is_on is not None


class IntercomOnline(IntercomEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, device):
        super().__init__(device, "online", "Online", "deviceState")

    @property
    def is_on(self):
        state = device_state(self.value)
        return state == 1 if state is not None else None

    @property
    def available(self):
        return super().available and self.is_on is not None


class IntercomDeviceStatus(IntercomEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = list(DEVICE_STATES.values())
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, device):
        super().__init__(device, "device_state", "Device status", "deviceState")

    @property
    def native_value(self):
        return DEVICE_STATES.get(device_state(self.value))


class IntercomFirmware(IntercomEntity, SensorEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    _attr_icon = "mdi:chip"

    def __init__(self, device):
        super().__init__(device, "firmware", "Firmware", "version")

    @property
    def native_value(self):
        return self.value if isinstance(self.value, str) and self.value else None


class IntercomActor(IntercomEntity):
    @property
    def available(self):
        if not super().available:
            return False
        if uuid := self.device.states.get("jLocked"):
            value = self._values.get(uuid)
            if value == "":
                return True
            if isinstance(value, str):
                if len(value) > 4096:
                    return False
                try:
                    value = json.loads(value)
                except (ValueError, RecursionError):
                    return False
            return isinstance(value, dict) and value.get("locked") == 0 and not value.get("reason")
        return True

    async def _command(self, command, uuid=None):
        if not self.available:
            raise HomeAssistantError("Intercom control is unavailable or locked")
        try:
            async with asyncio.timeout(COMMAND_TIMEOUT):
                await self.device.coordinator.api.send_websocket_command(uuid or self.device.action_uuid, command)
        except Exception as error:
            _LOGGER.warning("Intercom command failed (%s)", type(error).__name__)
            raise HomeAssistantError("Could not send the Intercom command") from None


class IntercomMute(IntercomActor, SwitchEntity):
    """Mute the Loxone bell, with state confirmed only by Miniserver feedback."""

    _attr_icon = "mdi:bell-off"

    def __init__(self, device):
        super().__init__(device, "mute", "Mute doorbell", "muted")

    @property
    def is_on(self):
        return binary_value(self.value)

    @property
    def available(self):
        return super().available and self.is_on is not None

    async def async_turn_on(self, **kwargs):
        await self._command("mute/1")

    async def async_turn_off(self, **kwargs):
        await self._command("mute/0")


class IntercomActionButton(IntercomActor, ButtonEntity):
    _attr_icon = "mdi:gesture-tap-button"

    def __init__(self, device, key, name, command, target=None):
        super().__init__(device, key, name)
        self._command_value = command
        self._target = target

    async def async_press(self):
        await self._command(self._command_value, self._target)


class IntercomReply(IntercomActionButton):
    _attr_icon = "mdi:account-voice"

    def __init__(self, device, index):
        super().__init__(device, f"reply_{index}", f"Play reply {index + 1}", f"playTts/{index}")
        self._index = index
        self._state_key = "answers"

    @property
    def available(self):
        replies = voice_replies(self.value)
        online_uuid = self.device.states.get("deviceState")
        online = not online_uuid or device_state(self._values.get(online_uuid)) == 1
        return super().available and online and self._index < len(replies) and bool(replies[self._index])

    @callback
    def _updated(self):
        replies = voice_replies(self.value)
        self._attr_extra_state_attributes["message"] = replies[self._index] if self._index < len(replies) else None


def _devices(hass, entry, structure):
    if not any(
        isinstance(control, dict) and control.get("type") == "IntercomV2"
        for control in (structure.get("controls") or {}).values()
    ):
        return []
    devices = list(intercom_devices(hass.data[DOMAIN][entry.entry_id], entry))
    if devices:
        devices[0].ensure_parent(hass)
    return devices


def intercom_binary_sensors(hass, entry, structure):
    entities = []
    for device in _devices(hass, entry, structure):
        if device.states.get("bell"):
            entities.append(IntercomRinging(device))
        if device.states.get("deviceState"):
            entities.append(IntercomOnline(device))
    return entities


def intercom_sensors(hass, entry, structure):
    entities = []
    for device in _devices(hass, entry, structure):
        if device.states.get("deviceState"):
            entities.append(IntercomDeviceStatus(device))
        if device.states.get("version"):
            entities.append(IntercomFirmware(device))
    return entities


def intercom_switches(hass, entry, structure):
    return [
        IntercomMute(device)
        for device in _devices(hass, entry, structure)
        if device.states.get("muted") and not device.control.get("isSecured")
    ]


def intercom_buttons(hass, entry, structure, async_add_entities):
    """Discover output/dismiss buttons now, and voice presets on their first state push."""
    devices = [device for device in _devices(hass, entry, structure) if not device.control.get("isSecured")]
    entities = []
    created = set()
    for device in devices:
        if device.states.get("bell"):
            button = IntercomActionButton(device, "dismiss", "Dismiss ringing", "answer")
            button._attr_icon = "mdi:bell-cancel"
            entities.append(button)
        for key, sub in (device.control.get("subControls") or {}).items():
            if not isinstance(sub, dict) or sub.get("type") not in {"Pushbutton", "IntercomSubControl"}:
                continue
            if sub.get("isSecured"):
                _LOGGER.info("Skipping a secured Intercom output; use PyLoxone's secured command action")
                continue
            uuid = sub.get("uuidAction") or key
            if not isinstance(uuid, str) or not uuid or (device.key, uuid) in created:
                continue
            created.add((device.key, uuid))
            entities.append(IntercomActionButton(device, f"{uuid}_output", sub.get("name") or "Output", "pulse", uuid))

    def new_replies(states):
        replies = []
        for device in devices:
            uuid = device.states.get("answers")
            if not uuid or uuid not in states:
                continue
            for index, text in enumerate(voice_replies(states[uuid])):
                identity = device.key, index
                if text and identity not in created:
                    created.add(identity)
                    replies.append(IntercomReply(device, index))
        return replies

    @callback
    def discover_replies(states):
        if replies := new_replies(states):
            async_add_entities(replies)

    if devices:
        entry.async_on_unload(async_dispatcher_connect(hass, state_update_signal(entry.entry_id), discover_replies))
        entities.extend(new_replies(devices[0].coordinator.intercom_state_values))
    return entities
