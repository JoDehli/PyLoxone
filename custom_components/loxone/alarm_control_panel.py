"""Interfaces with Alarm.com alarm control panels."""

import logging
import re

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.components.alarm_control_panel import (
    PLATFORM_SCHEMA, AlarmControlPanelEntity, AlarmControlPanelState)
from homeassistant.components.alarm_control_panel.const import (
    AlarmControlPanelEntityFeature, CodeFormat)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (CONF_CODE, CONF_NAME, CONF_PASSWORD,
                                 CONF_USERNAME)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from . import LoxoneEntity
from .const import DOMAIN, EVENT, SECUREDSENDDOMAIN, SENDDOMAIN
from .helpers import (add_room_and_cat_to_value_values, get_all,
                      get_or_create_device)
from .miniserver import get_miniserver_from_hass

DEFAULT_NAME = "Loxone Alarm"
DEFAULT_FORCE_UPDATE = False

_LOGGER = logging.getLogger(__name__)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_PASSWORD): cv.string,
        vol.Required(CONF_USERNAME): cv.string,
        vol.Optional(CONF_CODE): cv.positive_int,
        vol.Optional(CONF_NAME, default=DEFAULT_NAME): cv.string,
    }
)


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up Loxone Alarms."""
    return True


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Loxone Alarms."""
    miniserver = get_miniserver_from_hass(hass)
    loxconfig = miniserver.lox_config.json
    entities = []
    for loxone_alarm in get_all(loxconfig, "Alarm"):
        loxone_alarm = add_room_and_cat_to_value_values(loxconfig, loxone_alarm)
        loxone_alarm.update({"code": None})
        new_alarm = LoxoneAlarm(**loxone_alarm)
        hass.bus.async_listen(EVENT, new_alarm.event_handler)
        entities.append(new_alarm)

    async_add_entities(entities, True)
    return True


class LoxoneAlarm(LoxoneEntity, AlarmControlPanelEntity):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._state = 0.0
        self._disabled_move = 0.0
        self._level = 0.0
        self._armed_delay = 0.0
        self._armed_delay_total_delay = 0.0
        self._armed_at = 0
        self._next_level_at = 0
        self._code = str(kwargs["code"]) if kwargs["code"] else None
        self._attr_device_info = get_or_create_device(
            self.unique_id, self.name, "Alarm", self.room
        )

    @property
    def supported_features(self):
        return (
            AlarmControlPanelEntityFeature.ARM_HOME
            | AlarmControlPanelEntityFeature.ARM_AWAY
        )

    @property
    def code_arm_required(self):
        """Whether the code is required for arm actions."""
        self._code = "required"
        if self.isSecured:
            self._code = "required"
        else:
            self._code = None
        return self.isSecured

    async def event_handler(self, e):
        request_update = False
        if self.states["armed"] in e.data:
            self._state = e.data[self.states["armed"]]
            request_update = True

        if self.states["disabledMove"] in e.data:
            self._disabled_move = e.data[self.states["disabledMove"]]
            request_update = True

        if self.states["armedAt"] in e.data:
            self._armed_at = e.data[self.states["armedAt"]]
            request_update = True

        if self.states["nextLevelAt"] in e.data:
            self._next_level_at = e.data[self.states["nextLevelAt"]]
            request_update = True

        if self.states["armedDelay"] in e.data:
            self._armed_delay = e.data[self.states["armedDelay"]]
            request_update = True

        if self.states["armedDelayTotal"] in e.data:
            self._armed_delay_total_delay = e.data[self.states["armedDelayTotal"]]
            request_update = True

        if self.states["level"] in e.data:
            self._level = e.data[self.states["level"]]
            request_update = True

        if request_update:
            self.async_schedule_update_ha_state()

    @property
    def armed_at(self):
        return self._armed_at

    @property
    def next_level_at(self):
        return self._next_level_at

    @property
    def armed_delay(self):
        return self._armed_delay

    @property
    def armed_delay_total_delay(self):
        return self._armed_delay_total_delay

    @property
    def disabled_move(self):
        return self._disabled_move

    @property
    def level(self):
        return self._level

    @property
    def hidden(self) -> bool:
        """Return True if the entity should be hidden from UIs."""
        return False

    @property
    def icon(self):
        """Return the icon to use in the frontend, if any."""
        return None

    def alarm_disarm(self, code=None):
        pass

    def alarm_arm_home(self, code=None):
        pass

    def alarm_arm_away(self, code=None):
        pass

    async def async_alarm_disarm(self, code=None):
        """Send disarm command."""
        if self.isSecured:
            self.hass.bus.async_fire(
                SECUREDSENDDOMAIN, dict(uuid=self.uuidAction, value="off", code=code)
            )
        else:
            self.hass.bus.async_fire(
                SENDDOMAIN, dict(uuid=self.uuidAction, value="off")
            )
        self.async_schedule_update_ha_state()

    async def async_alarm_arm_home(self, code=None):
        """Send arm home command."""
        if self.isSecured:
            self.hass.bus.async_fire(
                SECUREDSENDDOMAIN,
                dict(uuid=self.uuidAction, value="delayedon/0", code=code),
            )
        else:
            self.hass.bus.async_fire(
                SENDDOMAIN, dict(uuid=self.uuidAction, value="delayedon/0")
            )
        self.async_schedule_update_ha_state()

    async def async_alarm_arm_away(self, code=None):
        """Send arm away command."""
        if self.isSecured:
            self.hass.bus.async_fire(
                SECUREDSENDDOMAIN,
                dict(uuid=self.uuidAction, value="delayedon/1", code=code),
            )
        else:
            self.hass.bus.async_fire(
                SENDDOMAIN, dict(uuid=self.uuidAction, value="delayedon/1")
            )
        self.async_schedule_update_ha_state()

    @property
    def alarm_state(self) -> AlarmControlPanelState | None:
        """Return the state of the device."""
        if self._level >= 1.0:
            return AlarmControlPanelState.TRIGGERED
        if self._armed_delay or self._armed_at:
            return AlarmControlPanelState.ARMING
        if self._state and self._disabled_move:
            return AlarmControlPanelState.ARMED_HOME
        if self._state:
            return AlarmControlPanelState.ARMED_AWAY
        return AlarmControlPanelState.DISARMED


    @property
    def extra_state_attributes(self):
        """Return the state attributes."""
        return {
            "uuid": self.uuidAction,
            "room": self.room,
            "category": self.cat,
            "device_type": self.type,
            "level": self._level,
            "armed_at": self._armed_at,
            "next_level_at": self._next_level_at,
            "armed_delay": self._armed_delay,
            "armed_delay_total_delay": self._armed_delay_total_delay,
            "platform": "loxone",
        }

    def _validate_code(self, code):
        """Validate given code."""
        check = self._code is None or code == self._code
        if not check:
            _LOGGER.warning("Wrong code entered")
        return check

    @property
    def code_format(self):
        """Return one or more digits/characters."""
        if self._code is None:
            return None
        if isinstance(self._code, str) and re.search("^\\d+$", self._code):
            return CodeFormat.NUMBER
        return CodeFormat.TEXT
