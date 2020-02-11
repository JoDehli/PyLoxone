"""Interfaces with Alarm.com alarm control panels."""
import asyncio
import logging
import re
import voluptuous as vol

import homeassistant.components.alarm_control_panel as alarm
from homeassistant.components.alarm_control_panel import PLATFORM_SCHEMA
from homeassistant.components.alarm_control_panel.const import (
    SUPPORT_ALARM_ARM_AWAY,
    SUPPORT_ALARM_ARM_HOME,
    SUPPORT_ALARM_ARM_NIGHT
)
from homeassistant.const import (
    CONF_CODE,
    CONF_NAME,
    CONF_PASSWORD,
    CONF_USERNAME,
    STATE_ALARM_ARMED_AWAY,
    STATE_ALARM_DISARMED,
)

import homeassistant.helpers.config_validation as cv

from . import get_all_alarm, get_room_name_from_room_uuid, get_cat_name_from_cat_uuid

CONF_UUID = "uuid"
EVENT = "loxone_event"
DOMAIN = 'loxone'
SENDDOMAIN = "loxone_send"
SECUREDSENDDOMAIN = "loxone_send_secured"

DEFAULT_NAME = 'Loxone Alarm'
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


async def async_setup_platform(hass, config, async_add_devices, discovery_info=None):
    """Set up Loxone Alarms."""
    if discovery_info is None:
        return

    config = hass.data[DOMAIN]
    loxconfig = config['loxconfig']
    devices = []

    for loxone_alarm in get_all_alarm(loxconfig):
        new_alarm = LoxoneAlarm(name=loxone_alarm['name'],
                                uuid=loxone_alarm['uuidAction'],
                                sensortyp="alarm",
                                room=get_room_name_from_room_uuid(loxconfig,
                                                                  loxone_alarm.get('room', '')),
                                cat=get_cat_name_from_cat_uuid(loxconfig,
                                                               loxone_alarm.get('cat', '')),
                                complete_data=loxone_alarm, code="None")

        hass.bus.async_listen(EVENT, new_alarm.event_handler)
        devices.append(new_alarm)
    async_add_devices(devices)
    return True


class LoxoneAlarm(alarm.AlarmControlPanel):

    def __init__(self, name, uuid, sensortyp, room="", cat="",
                 complete_data=None, code=None):
        self._state = 0.0
        self._name = name
        self._uuid = uuid
        self._room = room
        self._cat = cat
        self._sensortyp = sensortyp
        self._data = complete_data
        self._armed_uuid = ""
        self._armed_delay_uuid = ""
        self._armed_delay_total_delay_uuid = ""
        self._armed_delay = 0.0
        self._armed_delay_total_delay = 0.0
        self._secured = False
        self._code = str(code) if code else None

        if "isSecured" in self._data:
            self._secured = self._data['isSecured']

        if "states" in self._data:
            states = self._data['states']
            if "armed" in states:
                self._armed_uuid = states["armed"]

            if "armedDelay" in states:
                self._armed_delay_uuid = states["armedDelay"]

            if "armedDelay" in states:
                self._armed_delay_total_delay_uuid = states["armedDelayTotal"]

    @property
    def supported_features(self):
        return SUPPORT_ALARM_ARM_HOME | SUPPORT_ALARM_ARM_AWAY | SUPPORT_ALARM_ARM_NIGHT

    @property
    def code_arm_required(self):
        """Whether the code is required for arm actions."""
        self._code = "required"
        if self._secured:
            self._code = "required"
        else:
            self._code = None
        return self._secured

    async def event_handler(self, event):
        request_update = False
        if self._armed_uuid in event.data:
            self._state = event.data[self._armed_uuid]
            request_update = True

        if self._armed_delay_uuid in event.data:
            self._armed_delay = event.data[self._armed_delay_uuid]
            request_update = True

        if self._armed_delay_total_delay_uuid in event.data:
            self._armed_delay_total_delay = event.data[self._armed_delay_total_delay_uuid]
            request_update = True

        if request_update:
            self.async_schedule_update_ha_state()

    @property
    def armed_delay(self):
        return self._armed_delay

    @property
    def armed_delay_total_delay(self):
        return self._armed_delay_total_delay

    @property
    def name(self):
        return self._name

    @property
    def uuid(self):
        return self._uuid

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

    def alarm_arm_night(self, code=None):
        pass

    async def async_alarm_disarm(self, code=None):
        """Send disarm command."""
        if self._secured:
            self.hass.bus.async_fire(SECUREDSENDDOMAIN,
                                     dict(uuid=self._uuid, value="off", code=code))
        else:
            self.hass.bus.async_fire(SENDDOMAIN,
                                     dict(uuid=self._uuid, value="off"))
        self.schedule_update_ha_state()

    async def async_alarm_arm_home(self, code=None):
        """Send arm hom command."""
        if self._secured:
            self.hass.bus.async_fire(SECUREDSENDDOMAIN,
                                     dict(uuid=self._uuid, value="on", code=code))
        else:
            self.hass.bus.async_fire(SENDDOMAIN,
                                     dict(uuid=self._uuid, value="on"))
        self.schedule_update_ha_state()

    async def async_alarm_arm_away(self, code=None):
        """Send arm away command."""
        if self._secured:
            self.hass.bus.async_fire(SECUREDSENDDOMAIN,
                                     dict(uuid=self._uuid, value="on", code=code))
        else:
            self.hass.bus.async_fire(SENDDOMAIN,
                                     dict(uuid=self._uuid, value="on"))
        self.schedule_update_ha_state()

    def async_alarm_night_away(self, code=None):
        """Send arm away command."""
        if self._secured:
            self.hass.bus.async_fire(SECUREDSENDDOMAIN,
                                     dict(uuid=self._uuid, value="on", code=code))
        else:
            self.hass.bus.async_fire(SENDDOMAIN,
                                     dict(uuid=self._uuid, value="on"))
        self.schedule_update_ha_state()

    def alarm_trigger(self, code=None):
        """Send alarm trigger command.

        This method must be run in the event loop and returns a coroutine.
        """
        if self._secured:
            self.hass.bus.async_fire(SECUREDSENDDOMAIN,
                                     dict(uuid=self._uuid, value="on", code=code))
        else:
            self.hass.bus.async_fire(SENDDOMAIN,
                                     dict(uuid=self._uuid, value="on"))
        self.schedule_update_ha_state()

    def alarm_arm_custom_bypass(self, code=None):
        pass

    @property
    def state(self):
        """Return the state of the entity."""
        return STATE_ALARM_ARMED_AWAY if self._state else STATE_ALARM_DISARMED

    @property
    def device_state_attributes(self):
        """Return the state attributes."""
        return {"uuid": self._uuid, "room": self._room,
                "category": self._cat,
                "device_typ": "alarm",
                "armed_delay": self._armed_delay,
                "armed_delay_total_delay": self._armed_delay_total_delay,
                "plattform": "loxone"}

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
            return alarm.FORMAT_NUMBER
        return alarm.FORMAT_TEXT
