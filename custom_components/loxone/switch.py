"""
"""
import logging

import voluptuous as vol
from homeassistant.components.switch import SwitchDevice
from homeassistant.const import (
    CONF_VALUE_TEMPLATE)

from . import LoxoneEntity
from . import get_room_name_from_room_uuid, get_cat_name_from_cat_uuid, get_all_switch_entities

_LOGGER = logging.getLogger(__name__)

DOMAIN = 'loxone'
EVENT = "loxone_event"
SENDDOMAIN = "loxone_send"

from homeassistant.helpers.entity_component import EntityComponent
from homeassistant.components import (
    input_number,
)

from homeassistant.components.input_number import (
    SERVICE_DECREMENT,
    SERVICE_INCREMENT,
    SERVICE_SET_VALUE,
)


async def async_setup_platform(hass, config, async_add_devices, discovery_info={}):
    value_template = config.get(CONF_VALUE_TEMPLATE)
    if value_template is not None:
        value_template.hass = hass

    config = hass.data[DOMAIN]
    loxconfig = config['loxconfig']
    devices = []
    entities = []

    for switch_entity in get_all_switch_entities(loxconfig):
        if switch_entity['type'] in ["Pushbutton", "Switch"]:
            switch_entity.update({'room': get_room_name_from_room_uuid(loxconfig, switch_entity.get('room', '')),
                                  'cat': get_cat_name_from_cat_uuid(loxconfig, switch_entity.get('cat', ''))})
            new_push_button = LoxoneSwitch(**switch_entity)
            hass.bus.async_listen(EVENT, new_push_button.event_handler)
            devices.append(new_push_button)

        elif switch_entity['type'] == "TimedSwitch":
            switch_entity.update({'room': get_room_name_from_room_uuid(loxconfig, switch_entity.get('room', '')),
                                  'cat': get_cat_name_from_cat_uuid(loxconfig, switch_entity.get('cat', ''))})
            new_push_button = LoxoneTimedSwitch(**switch_entity)
            hass.bus.async_listen(EVENT, new_push_button.event_handler)
            devices.append(new_push_button)

        elif switch_entity['type'] == "Intercom":
            if "subControls" in switch_entity:
                for sub_name in switch_entity['subControls']:
                    subcontol = switch_entity['subControls'][sub_name]
                    _ = subcontol
                    _.update({'name': "{} - {}".format(switch_entity['name'], subcontol['name'])})
                    _.update({'room': get_room_name_from_room_uuid(loxconfig, switch_entity.get('room', ''))})
                    _.update({'cat': get_cat_name_from_cat_uuid(loxconfig, switch_entity.get('cat', ''))})
                    new_push_button = LoxoneIntercomSubControl(**_)
                    hass.bus.async_listen(EVENT, new_push_button.event_handler)
                    devices.append(new_push_button)
        elif switch_entity['type'] in ['LeftRightAnalog', 'UpDownAnalog', 'Slider']:
            # https://github.com/vinteo/hass-opensprinkler/blob/23fa23a628f3826310e8ade77d1dbe519b301bf7/opensprinkler.py#L52
            switch_entity.update({'uuidAction': switch_entity['uuidAction'],
                                  'name': switch_entity['name'],
                                  'initial': switch_entity['details']['min'],
                                  'min': switch_entity['details']['min'],
                                  'max': switch_entity['details']['max'],
                                  'step': switch_entity['details']['step'],
                                  'cat': get_cat_name_from_cat_uuid(loxconfig, switch_entity.get('cat', '')),
                                  'room': get_room_name_from_room_uuid(loxconfig, switch_entity.get('room', ''))
                                  })

            if switch_entity['type'] == 'UpDownAnalog':
                switch_entity.update({'mode': 'box'})
            else:
                switch_entity.update({'mode': 'slider'})

            new_loxone_input_select = LoxoneInputSelect(**switch_entity)
            hass.bus.async_listen(EVENT, new_loxone_input_select.event_handler)
            entities.append(new_loxone_input_select)

    component = EntityComponent(_LOGGER, 'input_number', hass)
    component.async_register_entity_service(SERVICE_INCREMENT, {}, "async_increment")
    component.async_register_entity_service(SERVICE_DECREMENT, {}, "async_decrement")
    component.async_register_entity_service(
        SERVICE_SET_VALUE,
        {vol.Required('value'): vol.Coerce(float)},
        "async_set_value",
    )
    await component.async_add_entities(entities)

    async_add_devices(devices)
    return True


class LoxoneInputSelect(LoxoneEntity, input_number.InputNumber):
    def __init__(self, **kwargs):
        LoxoneEntity.__init__(self, **kwargs)
        input_number.InputNumber.__init__(self, config=kwargs)

    async def event_handler(self, e):
        if self.uuidAction in e.data:
            self._current_value = e.data[self.uuidAction]
            self.async_schedule_update_ha_state()

    async def async_set_value(self, value):
        """Set new value."""
        num_value = float(value)
        if num_value < self._minimum or num_value > self._maximum:
            _LOGGER.warning(
                "Invalid value: %s (range %s - %s)",
                num_value,
                self._minimum,
                self._maximum,
            )
            return
        self.hass.bus.async_fire(SENDDOMAIN,
                                 dict(uuid=self.uuidAction, value=num_value))
        self.async_schedule_update_ha_state()

    async def async_increment(self):
        """Increment value."""
        new_value = self._current_value + self._step
        if new_value > self._maximum:
            _LOGGER.warning(
                "Invalid value: %s (range %s - %s)",
                new_value,
                self._minimum,
                self._maximum,
            )
            return
        self._current_value = new_value
        self.hass.bus.async_fire(SENDDOMAIN,
                                 dict(uuid=self.uuidAction, value=new_value))
        self.async_schedule_update_ha_state()

    async def async_decrement(self):
        """Decrement value."""
        new_value = self._current_value - self._step
        if new_value < self._minimum:
            _LOGGER.warning(
                "Invalid value: %s (range %s - %s)",
                new_value,
                self._minimum,
                self._maximum,
            )
            return
        self._current_value = new_value
        self.hass.bus.async_fire(SENDDOMAIN,
                                 dict(uuid=self.uuidAction, value=new_value))
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
        return state_dict


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
            if self.type == "Pushbutton":
                self.hass.bus.async_fire(SENDDOMAIN,
                                         dict(uuid=self.uuidAction, value="pulse"))
            else:
                self.hass.bus.async_fire(SENDDOMAIN,
                                         dict(uuid=self.uuidAction, value="On"))
            self._state = True
            self.schedule_update_ha_state()

    def turn_off(self, **kwargs):
        """Turn the device off."""
        if self._state:
            if self.type == "Pushbutton":
                self.hass.bus.async_fire(SENDDOMAIN,
                                         dict(uuid=self.uuidAction, value="pulse"))
            else:
                self.hass.bus.async_fire(SENDDOMAIN,
                                         dict(uuid=self.uuidAction, value="Off"))
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
