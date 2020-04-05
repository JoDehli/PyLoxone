"""
"""
import asyncio
import logging

from homeassistant.components.switch import SwitchDevice
from homeassistant.const import (
    CONF_VALUE_TEMPLATE)
from homeassistant.const import DEVICE_DEFAULT_NAME
from . import get_room_name_from_room_uuid, get_cat_name_from_cat_uuid, get_all_push_buttons
from . import LoxoneEntity

_LOGGER = logging.getLogger(__name__)

DOMAIN = 'loxone'
EVENT = "loxone_event"
SENDDOMAIN = "loxone_send"


async def async_setup_platform(hass, config, async_add_devices, discovery_info={}):
    value_template = config.get(CONF_VALUE_TEMPLATE)
    if value_template is not None:
        value_template.hass = hass

    config = hass.data[DOMAIN]
    loxconfig = config['loxconfig']
    devices = []
    for push_button in get_all_push_buttons(loxconfig):
        if push_button['type'] in ["Pushbutton", "Switch"]:
            push_button.update({'room': get_room_name_from_room_uuid(loxconfig, push_button.get('room', '')),
                                'cat': get_cat_name_from_cat_uuid(loxconfig, push_button.get('cat', ''))})
            new_push_button = LoxoneSwitch(**push_button)
            hass.bus.async_listen(EVENT, new_push_button.event_handler)
            devices.append(new_push_button)
        elif push_button['type'] == "TimedSwitch":
            push_button.update({'room': get_room_name_from_room_uuid(loxconfig, push_button.get('room', '')),
                                'cat': get_cat_name_from_cat_uuid(loxconfig, push_button.get('cat', ''))})
            new_push_button = LoxoneTimedSwitch(**push_button)
            hass.bus.async_listen(EVENT, new_push_button.event_handler)
            devices.append(new_push_button)

        elif push_button['type'] == "Intercom":
            if "subControls" in push_button:
                for sub_name in push_button['subControls']:
                    subcontol = push_button['subControls'][sub_name]
                    _ = subcontol
                    _.update({'name': "{} - {}".format(push_button['name'], subcontol['name'])})
                    _.update({'room': get_room_name_from_room_uuid(loxconfig,push_button.get('room',''))})
                    _.update({'cat': get_cat_name_from_cat_uuid(loxconfig, push_button.get('cat', ''))})
                    new_push_button = LoxoneIntercomSubControl(**_)
                    hass.bus.async_listen(EVENT, new_push_button.event_handler)
                    devices.append(new_push_button)
    async_add_devices(devices)
    return True


class LoxoneTimedSwitch(LoxoneEntity, SwitchDevice):
    """Representation of a loxone switch or pushbutton"""

    def __init__(self, **kwargs):
        LoxoneEntity.__init__(self, **kwargs)
        self._icon = None
        self._assumed = False
        self._state = False
        self._delay_remain = 0.0
        self._delay_time_total = 0.0

        if 'deactivationDelay' in self.states:
            self._deactivation_delay = self.states['deactivationDelay']
        else:
            self._deactivation_delay = ""

        if 'deactivationDelayTotal' in self.states:
            self._deactivation_delay_total = self.states['deactivationDelayTotal']
        else:
            self._deactivation_delay_total = ""

    @property
    def should_poll(self):
        """No polling needed for a demo switch."""
        return False

    @property
    def icon(self):
        """Return the icon to use for device if any."""
        return self._icon

    @property
    def assumed_state(self):
        """Return if the state is based on assumptions."""
        return self._assumed

    @property
    def is_on(self):
        """Return true if switch is on."""
        return self._state

    def turn_on(self, **kwargs):
        """Turn the switch on."""
        self.hass.bus.async_fire(SENDDOMAIN,
                                 dict(uuid=self.uuidAction, value="pulse"))
        self._state = True
        self.schedule_update_ha_state()

    def turn_off(self, **kwargs):
        """Turn the device off."""
        self.hass.bus.async_fire(SENDDOMAIN,
                                 dict(uuid=self.uuidAction, value="pulse"))
        self._state = False
        self.schedule_update_ha_state()

    async def event_handler(self, e):
        should_update = False
        if self._deactivation_delay in e.data:
            if e.data[self._deactivation_delay] == 0.0:
                self._state = False
            else:
                self._state = True

            self._delay_remain = int(e.data[self._deactivation_delay])
            should_update = True

        if self._deactivation_delay_total in e.data:
            self._delay_time_total = int(e.data[self._deactivation_delay_total])
            should_update = True

        if should_update:
            self.async_schedule_update_ha_state()

    @property
    def device_state_attributes(self):
        """Return device specific state attributes.

        Implemented by platform classes.
        """
        state_dict = {"uuid": self.uuidAction,
                      "room": self.room,
                      "category": self.cat,
                      "device_typ": self.type,
                      "plattform": "loxone"}

        if self._state == 0.0:
            state_dict.update({"delay_time_total": str(self._delay_time_total)})

        else:
            state_dict.update({"delay": str(self._delay_remain),
                               "delay_time_total": str(self._delay_time_total)
                               })
        return state_dict


class LoxoneSwitch(LoxoneEntity, SwitchDevice):
    """Representation of a loxone switch or pushbutton"""

    def __init__(self, **kwargs):
        LoxoneEntity.__init__(self, **kwargs)

        """Initialize the Loxone switch."""
        self._state = False
        self._icon = None
        self._assumed = False

    @property
    def should_poll(self):
        """No polling needed for a demo switch."""
        return False

    @property
    def icon(self):
        """Return the icon to use for device if any."""
        return self._icon

    @property
    def assumed_state(self):
        """Return if the state is based on assumptions."""
        return self._assumed

    @property
    def is_on(self):
        """Return true if switch is on."""
        return self._state

    def turn_on(self, **kwargs):
        """Turn the switch on."""
        if not self._state:
            self.hass.bus.async_fire(SENDDOMAIN,
                                     dict(uuid=self.uuidAction, value="pulse"))
            self._state = True
            self.schedule_update_ha_state()

    def turn_off(self, **kwargs):
        """Turn the device off."""
        if self._state:
            self.hass.bus.async_fire(SENDDOMAIN,
                                     dict(uuid=self.uuidAction, value="pulse"))
            self._state = False
            self.schedule_update_ha_state()

    async def event_handler(self, event):
        if self.uuidAction in event.data or self.states['active'] in event.data:
            if self.states['active'] in event.data:
                self._state = event.data[self.states['active']]
            self.async_schedule_update_ha_state()

    @property
    def device_state_attributes(self):
        """Return device specific state attributes.

        Implemented by platform classes.
        """
        return {"uuid": self.uuidAction, "state_uuid": self.states['active'], "room": self.room, "category": self.cat,
                "device_typ": self.type, "plattform": "loxone"}


class LoxoneIntercomSubControl(LoxoneSwitch):
    def __init__(self, **kwargs):
        LoxoneSwitch.__init__(self, **kwargs)

    def turn_on(self, **kwargs):
        """Turn the switch on."""
        self.hass.bus.async_fire(SENDDOMAIN,
                                 dict(uuid=self.uuidAction, value="on"))
        self._state = True
        self.schedule_update_ha_state()

    @property
    def device_state_attributes(self):
        """Return device specific state attributes.

        Implemented by platform classes.
        """
        return {"uuid": self.uuidAction, "state_uuid": self.states['active'], "room": self.room, "category": self.cat,
                "device_typ": self.type, "plattform": "loxone"}
