"""
Loxone Switches

For more details about this component, please refer to the documentation at
https://github.com/JoDehli/PyLoxone
"""

import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNKNOWN
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from . import LoxoneEntity
from .const import DOMAIN, SENDDOMAIN
from .helpers import (get_all, get_cat_name_from_cat_uuid,
                      get_room_name_from_room_uuid)
from .miniserver import get_miniserver_from_hass

_LOGGER = logging.getLogger(__name__)

async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up Loxone Switch."""
    return True

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up entry."""
    miniserver = get_miniserver_from_hass(hass)
    loxconfig = miniserver.lox_config.json
    entities = []

    for switch_entity in get_all(
        loxconfig, ["Switch", "TimedSwitch", "Intercom"]
    ):
        switch_entity.update(
            {
                "room": get_room_name_from_room_uuid(
                    loxconfig, switch_entity.get("room", "")
                ),
                "cat": get_cat_name_from_cat_uuid(
                    loxconfig, switch_entity.get("cat", "")
                ),
                "config_entry": config_entry,
            }
        )
        if switch_entity["type"] in ["Switch"]:
            entities.append(LoxoneSwitch(**switch_entity))
        elif switch_entity["type"] == "TimedSwitch":
            entities.append(LoxoneTimedSwitch(**switch_entity))
        elif switch_entity["type"] == "Intercom":
            if "subControls" in switch_entity:
                for sub_name, subcontrol in switch_entity["subControls"].items():
                    subcontrol.update({
                        "name": f"{switch_entity['name']} - {subcontrol['name']}",
                        "room": get_room_name_from_room_uuid(
                            loxconfig, switch_entity.get("room", "")
                        ),
                        "cat": get_cat_name_from_cat_uuid(
                            loxconfig, switch_entity.get("cat", "")
                        ),
                        "config_entry": config_entry,
                    })
                    entities.append(LoxoneIntercomSubControl(**subcontrol))

    async_add_entities(entities)

class LoxoneTimedSwitch(LoxoneEntity, SwitchEntity):
    """Representation of a Loxone timed switch."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._attr_icon = None
        self._assumed = False
        self._attr_is_on = STATE_UNKNOWN
        self._delay_remain = 0.0
        self._delay_time_total = 0.0

        self._deactivation_delay = self.states.get("deactivationDelay", "")
        self._deactivation_delay_total = self.states.get("deactivationDelayTotal", "")

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self.unique_id)},
            name=f"{DOMAIN} {self.name}",
            manufacturer="Loxone",
            suggested_area=self.room,
            model=self.type,
        )

    @property
    def should_poll(self):
        """No polling needed for this switch."""
        return False

    @property
    def icon(self):
        """Return the icon to use for device if any."""
        return self._attr_icon

    @property
    def assumed_state(self):
        """Return if the state is based on assumptions."""
        return self._assumed

    @property
    def is_on(self):
        """Return true if switch is on."""
        return self._attr_is_on

    def turn_on(self, **kwargs):
        """Turn the switch on."""
        self.hass.bus.fire(SENDDOMAIN, dict(uuid=self.uuidAction, value="pulse"))
        self._attr_is_on = True
        self.schedule_update_ha_state()

    def turn_off(self, **kwargs):
        """Turn the device off."""
        self.hass.bus.fire(SENDDOMAIN, dict(uuid=self.uuidAction, value="off"))
        self._attr_is_on = False
        self.schedule_update_ha_state()

    async def event_handler(self, e):
        should_update = False
        if self._deactivation_delay in e.data:
            self._attr_is_on = e.data[self._deactivation_delay] != 0.0
            self._delay_remain = int(e.data[self._deactivation_delay])
            should_update = True

        if self._deactivation_delay_total in e.data:
            self._delay_time_total = int(e.data[self._deactivation_delay_total])
            should_update = True

        if should_update:
            self.async_schedule_update_ha_state()

    @property
    def extra_state_attributes(self):
        """Return device specific state attributes."""
        return {
            "uuid": self.uuidAction,
            "room": self.room,
            "category": self.cat,
            "device_typ": self.type,
            "platform": "loxone",
            "delay": str(self._delay_remain) if self._attr_is_on else None,
            "delay_time_total": str(self._delay_time_total),
        }

class LoxoneSwitch(LoxoneEntity, SwitchEntity):
    """Representation of a Loxone switch."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._attr_is_on = STATE_UNKNOWN
        self._attr_icon = None
        self._assumed = False

    @property
    def should_poll(self):
        """No polling needed for this switch."""
        return False

    @property
    def icon(self):
        """Return the icon to use for device if any."""
        return self._attr_icon

    @property
    def assumed_state(self):
        """Return if the state is based on assumptions."""
        return self._assumed

    @property
    def is_on(self):
        """Return true if switch is on."""
        return self._attr_is_on

    def turn_on(self, **kwargs):
        """Turn the switch on."""
        if not self._attr_is_on:
            value = "On"
            self.hass.bus.fire(SENDDOMAIN, dict(uuid=self.uuidAction, value=value))
            self._attr_is_on = True
            self.schedule_update_ha_state()

    def turn_off(self, **kwargs):
        """Turn the device off."""
        if self._attr_is_on:
            value = "Off"
            self.hass.bus.fire(SENDDOMAIN, dict(uuid=self.uuidAction, value=value))
            self._attr_is_on = False
            self.schedule_update_ha_state()

    async def event_handler(self, event):
        if self.uuidAction in event.data or self.states["active"] in event.data:
            self._attr_is_on = event.data.get(self.states["active"], self._attr_is_on)
            self.async_schedule_update_ha_state()

    @property
    def extra_state_attributes(self):
        """Return device specific state attributes."""
        return {
            "uuid": self.uuidAction,
            "state_uuid": self.states["active"],
            "room": self.room,
            "category": self.cat,
            "device_typ": self.type,
            "platform": "loxone",
        }

    @property
    def device_info(self):
        """Return device information."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.unique_id)},
            name=self.name,
            manufacturer="Loxone",
            model=self.type,
            suggested_area=self.room,
        )

class LoxoneIntercomSubControl(LoxoneSwitch):
    """Representation of a Loxone intercom sub-control switch."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def turn_on(self, **kwargs):
        """Turn the switch on."""
        self.hass.bus.fire(SENDDOMAIN, dict(uuid=self.uuidAction, value="on"))
        self._attr_is_on = True
        self.schedule_update_ha_state()

    @property
    def extra_state_attributes(self):
        """Return device specific state attributes."""
        return {
            "uuid": self.uuidAction,
            "state_uuid": self.states["active"],
            "room": self.room,
            "category": self.cat,
            "device_typ": self.type,
            "platform": "loxone",
        }

    @property
    def device_info(self):
        """Return device information."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.unique_id)},
            name=self.name,
            manufacturer="Loxone",
            model=self.type,
            suggested_area=self.room,
        )
