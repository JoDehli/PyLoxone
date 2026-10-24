"""Support for Loxone binary sensors."""

from __future__ import annotations

import logging
from typing import Literal, final

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.components.binary_sensor import (BinarySensorDeviceClass,
                                                    BinarySensorEntity)
from homeassistant.components.sensor import CONF_STATE_CLASS
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (CONF_DEVICE_CLASS, CONF_NAME,
                                 CONF_UNIT_OF_MEASUREMENT, CONF_VALUE_TEMPLATE,
                                 STATE_OFF, STATE_ON, STATE_UNKNOWN)
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from . import LoxoneEntity
from .const import CONF_ACTIONID, DOMAIN, EVENT, SENDDOMAIN
from .helpers import (add_room_and_cat_to_value_values, get_all,
                      get_or_create_device)
from .miniserver import get_miniserver_from_hass
from .window_monitor import (LoxoneWindowContactSensor,
                             LoxoneWindowLockSensor, WindowContact,
                             has_lock_info, window_contacts)

_LOGGER = logging.getLogger(__name__)
NEW_SENSOR = "binairy_sensors"
DEFAULT_NAME = "Loxone Binary Sensor"

LOXONE_DEVICE_CLASS_MAP: dict[str, BinarySensorDeviceClass] = {
    "presence": BinarySensorDeviceClass.PRESENCE,
    "smoke": BinarySensorDeviceClass.SMOKE,
}


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_devices: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up Loxone Sensor from yaml"""
    value_template = config.get(CONF_VALUE_TEMPLATE)
    if value_template is not None:
        value_template.hass = hass

    # Devices from yaml
    if config != {}:
        # Here setup all Sensors in Yaml-File
        new_sensor = LoxoneCustomBinarySensor(**config)
        async_add_devices([new_sensor])
        return True
    return True


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up entry."""
    miniserver = get_miniserver_from_hass(hass, config_entry)
    loxconfig = miniserver.lox_config.json
    entities = []

    for sensor in get_all(loxconfig, "InfoOnlyDigital"):
        sensor = add_room_and_cat_to_value_values(loxconfig, sensor)
        sensor.update({"type": "digital"})
        entities.append(LoxoneDigitalSensor(**sensor))

    for sensor in get_all(loxconfig, "PresenceDetector"):
        sensor = add_room_and_cat_to_value_values(loxconfig, sensor)
        sensor.update({"type": "presence"})
        entities.append(LoxoneDigitalSensor(**sensor))

    for sensor in get_all(loxconfig, "SmokeAlarm"):
        sensor = add_room_and_cat_to_value_values(loxconfig, sensor)
        sensor.update({"type": "smoke"})
        entities.append(LoxoneDigitalSensor(**sensor))

    # #524: one window binary sensor per WindowMonitor contact, plus a lock
    # binary sensor for the contacts that turn out to have a lock input.
    try:
        contacts = window_contacts(loxconfig)
        entities.extend(LoxoneWindowContactSensor(contact) for contact in contacts)
        entities.extend(_setup_window_locks(hass, config_entry, contacts, async_add_entities))
    except Exception:
        _LOGGER.exception("Skipping WindowMonitor controls")

    @callback
    def async_add_binary_sensors(_):
        async_add_entities(_, True)

    miniserver.listeners.append(
        async_dispatcher_connect(
            hass,
            miniserver.async_signal_new_device("sensors"),
            async_add_binary_sensors,
        )
    )
    async_add_entities(entities)


def _setup_window_locks(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    contacts: list[WindowContact],
    async_add_entities: AddEntitiesCallback,
) -> list[LoxoneWindowLockSensor]:
    """
    Lock binary sensors for WindowMonitor contacts (#524).

    The structure file does not say which contacts have a lock input, so a
    lock entity is added the first time a contact reports a lock bit (8/16)
    in its monitor's ``windowStates``.  Contacts whose lock entity is already
    in the entity registry get it immediately, so a restart does not leave it
    unavailable until the first value.
    """
    registry = er.async_get(hass)
    created: set[str] = set()
    immediate: list[LoxoneWindowLockSensor] = []
    by_stream: dict[str, list[WindowContact]] = {}
    for contact in contacts:
        by_stream.setdefault(contact.feed.states_uuid, []).append(contact)
        if registry.async_get_entity_id("binary_sensor", DOMAIN, f"{contact.uuid}-lock"):
            created.add(contact.uuid)
            immediate.append(LoxoneWindowLockSensor(contact))

    @callback
    def _on_event(e: Event) -> None:
        new: list[LoxoneWindowLockSensor] = []
        for states_uuid, group in by_stream.items():
            if states_uuid not in e.data:
                continue
            values = group[0].feed.values(e.data[states_uuid])
            if not values:
                continue
            for contact in group:
                if contact.uuid in created or contact.index >= len(values):
                    continue
                if has_lock_info(values[contact.index]):
                    created.add(contact.uuid)
                    new.append(LoxoneWindowLockSensor(contact, initial=values))
        if new:
            async_add_entities(new)

    config_entry.async_on_unload(hass.bus.async_listen(EVENT, _on_event))
    return immediate


class LoxoneDigitalSensor(LoxoneEntity, BinarySensorEntity):
    """Representation of a binary Loxone device."""

    _attr_is_on: bool | None = None
    _attr_state: None = None
    _attr_available = False

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._attr_state = STATE_UNKNOWN
        self._attr_is_on = STATE_UNKNOWN
        self._from_loxone_config = False

        if (
            "type" in kwargs
            and "room" in kwargs
            and "cat" in kwargs
            and hasattr(self, "states")
        ):
            self._from_loxone_config = True
            if self.type == "smoke":
                # Optional since Miniserver 10.3: structure files without
                # the state must not crash the setup (a missing key then
                # simply never matches an event → the sensor stays unknown).
                self._state_uuid = self.states.get("areAlarmSignalsOff")
            elif self.type == "presence":
                self._state_uuid = self.states.get("active")
            elif "active" in self.states:
                self._state_uuid = self.uuidAction
        else:
            self._state_uuid = self.uuidAction

        self._state = STATE_UNKNOWN
        self._format = self._get_format(kwargs.get("details", {}).get("format", ""))
        self._parent_id = kwargs.get("parent_id", None)
        self._on_state = STATE_ON
        self._off_state = STATE_OFF
        self._attr_available = True
        if self.type in LOXONE_DEVICE_CLASS_MAP:
            self._attr_device_class = LOXONE_DEVICE_CLASS_MAP[self.type]
        else:
            self._attr_device_class = None

        device_uuid = self._parent_id or self.unique_id

        if self._from_loxone_config:
            self._attr_device_info = get_or_create_device(
                device_uuid, self.name, self.type, self.room
            )
        else:
            self._attr_device_info = get_or_create_device(
                device_uuid, self.name, self.type, ""
            )

        if self._from_loxone_config:
            self._attr_extra_state_attributes.update(
                {
                    "state_uuid": self._state_uuid,
                    "device_type": self.type,
                }
            )
        else:
            self._attr_extra_state_attributes.update(
                {
                    "device_type": self._attr_device_class,
                }
            )

    async def event_handler(self, e):
        if self._state_uuid in e.data:
            self._state = e.data[self._state_uuid]
            if self._state == 1.0:
                self._state = self._on_state
            else:
                self._state = self._off_state
            if not self._attr_available:
                self._attr_available = True
            self.async_schedule_update_ha_state()

    @final
    @property
    def state(self) -> Literal["on", "off"] | None:
        """Return the state of the binary sensor."""
        if (is_on := self.is_on) is None:
            return None
        return STATE_ON if is_on else STATE_OFF

    @property
    def is_on(self) -> bool | None:
        """Return true if sensor is on."""
        return self._state == self._on_state


class LoxoneCustomBinarySensor(LoxoneEntity, BinarySensorEntity):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._name = kwargs["name"]
        self._state = STATE_UNKNOWN
        self._on_state = STATE_ON
        self._off_state = STATE_OFF

        if "uuidAction" in kwargs:
            self.uuidAction = kwargs["uuidAction"]
        else:
            self.uuidAction = ""

    @property
    def is_on(self) -> bool | None:
        """Return true if sensor is on."""
        return self._state == self._on_state

    @property
    def state(self) -> Literal["on", "off"] | None:
        """Return the state of the binary sensor."""
        if (is_on := self.is_on) is None:
            return None
        return STATE_ON if is_on else STATE_OFF

    async def event_handler(self, e):
        if self.uuidAction in e.data:
            data = e.data[self.uuidAction]
            if data == 1.0:
                self._state = self._on_state
            else:
                self._state = self._off_state
            self.async_schedule_update_ha_state()

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._name
