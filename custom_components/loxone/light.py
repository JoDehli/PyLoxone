import asyncio
import logging
from typing import Any
from . import LoxoneEntity

import homeassistant.util.color as color_util
import numpy as np
from homeassistant.components.light import (
    SUPPORT_EFFECT,
    SUPPORT_BRIGHTNESS,
    SUPPORT_COLOR,
    SUPPORT_COLOR_TEMP,
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP,
    ATTR_HS_COLOR,
    LightEntity,
    ToggleEntity
)
from homeassistant.const import (
    CONF_VALUE_TEMPLATE)

from . import get_room_name_from_room_uuid, \
    get_cat_name_from_cat_uuid, \
    get_all_light_controller, \
    get_all_dimmer

_LOGGER = logging.getLogger(__name__)

DEFAULT_NAME = 'Loxone Light Controller V2'
DEFAULT_FORCE_UPDATE = False

CONF_UUID = "uuid"
EVENT = "loxone_event"
DOMAIN = 'loxone'
SENDDOMAIN = "loxone_send"

STATE_ON = "on"
STATE_OFF = "off"


def to_hass_level(level):
    """Convert the given Loxone (0.0-100.0) light level to HASS (0-255)."""
    return int((level * 255) / 100)


def to_loxone_level(level):
    """Convert the given HASS light level (0-255) to Loxone (0.0-100.0)."""
    return float((level * 100) / 255)


def to_hass_color_temp(temp):
    """Linear interpolation between Loxone values from 2700 to 6500"""
    return np.interp(temp, [2700, 6500], [500, 153])


def to_loxone_color_temp(temp):
    """Linear interpolation between HASS values from 153 to 500"""
    return np.interp(temp, [153, 500], [6500, 2700])


async def async_setup_platform(hass, config, async_add_devices,
                               discovery_info=None):
    """Set up Loxone Light Controller."""
    return True


async def async_setup_entry(hass, config_entry, async_add_devices):
    """Set up Loxone Light Controller."""
    loxconfig = hass.data[DOMAIN]['loxconfig']
    identify = loxconfig['msInfo']['serialNr']

    devices = []
    all_dimmers = []
    all_light_controller_dimmers = []
    all_color_picker = []
    all_switches = []
    all_dimmers = get_all_dimmer(loxconfig)

    for light_controller in get_all_light_controller(loxconfig):
        light_controller.update({'room': get_room_name_from_room_uuid(loxconfig, light_controller.get('room', '')),
                                 'cat': get_cat_name_from_cat_uuid(loxconfig, light_controller.get('cat', '')),
                                 'async_add_devices': async_add_devices
                                 })
        new_light_controller = LoxonelightcontrollerV2(**light_controller)
        # from homeassistant.helpers import config_validation as cv, device_registry as dr
        # device_registry = await dr.async_get_registry(hass)
        #
        # device_registry.async_get_or_create(
        #     config_entry_id=config_entry.entry_id,
        #     identifiers={(DOMAIN, new_light_controller.unique_id)},
        #     name=new_light_controller.name,
        #     manufacturer="Loxone",
        #     model="LightControllerV2",
        #     via_device=(DOMAIN, identify)
        # )

        if 'subControls' in light_controller:
            if len(light_controller['subControls']) > 0:
                for sub_controll in light_controller['subControls']:
                    if light_controller['subControls'][sub_controll]['type'] == "Dimmer":
                        light_controller['subControls'][sub_controll]['room'] = light_controller.get('room', '')
                        light_controller['subControls'][sub_controll]['cat'] = light_controller.get('cat', '')
                        light_controller['subControls'][sub_controll][
                            'lightcontroller_id'] = new_light_controller.unique_id
                        all_light_controller_dimmers.append(light_controller['subControls'][sub_controll])

                    elif light_controller['subControls'][sub_controll]['type'] == "Switch":
                        light_controller['subControls'][sub_controll]['room'] = light_controller.get('room', '')
                        light_controller['subControls'][sub_controll]['cat'] = light_controller.get('cat', '')
                        light_controller['subControls'][sub_controll][
                            'lightcontroller_id'] = new_light_controller.unique_id
                        all_switches.append(light_controller['subControls'][sub_controll])

                    elif light_controller['subControls'][sub_controll]['type'] == "ColorPickerV2":
                        light_controller['subControls'][sub_controll]['room'] = light_controller.get('room', '')
                        light_controller['subControls'][sub_controll]['cat'] = light_controller.get('cat', '')
                        light_controller['subControls'][sub_controll][
                            'lightcontroller_id'] = new_light_controller.unique_id
                        all_color_picker.append(light_controller['subControls'][sub_controll])

        hass.bus.async_listen(EVENT, new_light_controller.event_handler)
        devices.append(new_light_controller)

    _ = all_dimmers + all_light_controller_dimmers

    for dimmer in _:
        if dimmer in all_light_controller_dimmers:
            dimmer.update({'room': get_room_name_from_room_uuid(loxconfig, light_controller.get('room', '')),
                           'cat': get_cat_name_from_cat_uuid(loxconfig, light_controller.get('cat', '')),
                           'async_add_devices': async_add_devices
                           })
        else:
            dimmer.update({'room': get_room_name_from_room_uuid(loxconfig, dimmer.get('room', '')),
                           'cat': get_cat_name_from_cat_uuid(loxconfig, dimmer.get('cat', '')),
                           'async_add_devices': async_add_devices
                           })

        new_dimmer = LoxoneDimmer(**dimmer)
        hass.bus.async_listen(EVENT, new_dimmer.event_handler)
        devices.append(new_dimmer)

    for switch in all_switches:
        switch.update({'room': get_room_name_from_room_uuid(loxconfig, light_controller.get('room', '')),
                       'cat': get_cat_name_from_cat_uuid(loxconfig, light_controller.get('cat', '')),
                       'async_add_devices': async_add_devices
                       })
        new_switch = LoxoneLight(**switch)
        hass.bus.async_listen(EVENT, new_switch.event_handler)
        devices.append(new_switch)

    for color_picker in all_color_picker:
        color_picker.update({'room': get_room_name_from_room_uuid(loxconfig, light_controller.get('room', '')),
                             'cat': get_cat_name_from_cat_uuid(loxconfig, light_controller.get('cat', '')),
                             'async_add_devices': async_add_devices
                             })
        new_color_picker = LoxoneColorPickerV2(**color_picker)
        hass.bus.async_listen(EVENT, new_color_picker.event_handler)
        devices.append(new_color_picker)

    async_add_devices(devices, True)

    # from homeassistant.helpers import config_validation as cv, device_registry as dr
    # device_registry = await dr.async_get_registry(hass)

    return True


class LoxonelightcontrollerV2(LoxoneEntity, LightEntity):
    """Representation of a Light Controller V2."""

    def __init__(self, **kwargs):
        LoxoneEntity.__init__(self, **kwargs)
        """Initialize the sensor."""
        self._state = 0.0
        self._active_moods = []
        self._moodlist = []
        self._additional_moodlist = []
        self._async_add_devices = kwargs['async_add_devices']

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self.unique_id)},
            "name": self.name,
            "manufacturer": "Loxone",
            "model": "LightControllerV2",
        }

    @property
    def device_class(self):
        """Return the class of this device, from component DEVICE_CLASSES."""
        return self.type

    @property
    def mood_list_uuid(self):
        return self.states["moodList"]

    @property
    def hidden(self) -> bool:
        """Return True if the entity should be hidden from UIs."""
        return False

    @property
    def icon(self):
        """Return the icon to use in the frontend, if any."""
        return None

    def get_moodname_by_id(self, _id):
        for mood in self._moodlist:
            if "id" in mood and "name" in mood:
                if mood['id'] == _id:
                    return mood['name']
        return _id

    def get_id_by_moodname(self, _name):
        for mood in self._moodlist:
            if "id" in mood and "name" in mood:
                if mood['name'] == _name:
                    return mood['id']
        return _name

    @property
    def effect_list(self):
        """Return the moods of light controller."""
        moods = []
        for mood in self._moodlist:
            if "name" in mood:
                moods.append(mood['name'])
        return moods

    @property
    def effect(self):
        """Return the current effect."""
        if len(self._active_moods) == 1:
            return self.get_moodname_by_id(self._active_moods[0])
        return None

    def turn_on(self, **kwargs) -> None:
        if 'effect' in kwargs:
            effects = kwargs['effect'].split(",")
            if len(effects) == 1:
                mood_id = self.get_id_by_moodname(kwargs['effect'])
                if mood_id != kwargs['effect']:
                    self.hass.bus.async_fire(SENDDOMAIN,
                                             dict(uuid=self.uuidAction, value="changeTo/{}".format(mood_id)))
                else:
                    self.hass.bus.async_fire(SENDDOMAIN,
                                             dict(uuid=self.uuidAction, value="plus"))
            else:
                effect_ids = []
                for _ in effects:
                    mood_id = self.get_id_by_moodname(_.strip())
                    if mood_id != _:
                        effect_ids.append(mood_id)

                self.hass.bus.async_fire(SENDDOMAIN,
                                         dict(uuid=self.uuidAction, value="on"))

                for _ in effect_ids:
                    self.hass.bus.async_fire(SENDDOMAIN, dict(uuid=self.uuidAction, value="addMood/{}".format(_)))

        else:
            self.hass.bus.async_fire(SENDDOMAIN,
                                     dict(uuid=self.uuidAction, value="on"))
        self.schedule_update_ha_state()

    def turn_off(self, **kwargs) -> None:
        self.hass.bus.async_fire(SENDDOMAIN,
                                 dict(uuid=self.uuidAction, value="off"))
        self.schedule_update_ha_state()

    async def event_handler(self, event):
        request_update = False
        if self.uuidAction in event.data:
            self._state = event.data[self.uuidAction]
            request_update = True

        if self.states["activeMoods"] in event.data:
            self._active_moods = eval(event.data[self.states["activeMoods"]])
            request_update = True

        if self.states["moodList"] in event.data:
            event.data[self.states["moodList"]] = event.data[self.states["moodList"]].replace("true", "True")
            event.data[self.states["moodList"]] = event.data[self.states["moodList"]].replace("false", "False")
            self._moodlist = eval(event.data[self.states["moodList"]])
            request_update = True

        if self.states["additionalMoods"] in event.data:
            self._additional_moodlist = eval(event.data[self.states['additionalMoods']])
            request_update = True

        if request_update:
            self.async_schedule_update_ha_state()

    @property
    def state(self):
        """Return the state of the entity."""
        return STATE_ON if self.is_on else STATE_OFF

    @property
    def is_on(self) -> bool:
        if self._active_moods != [778]:
            return True
        else:
            return False

    @property
    def device_state_attributes(self):
        """Return device specific state attributes.

        Implemented by platform classes.
        """
        return {"uuid": self.uuidAction, "room": self.room,
                "category": self.cat,
                "selected_scene": self.effect,
                "device_typ": self.type, "plattform": "loxone"}

    @property
    def supported_features(self):
        return SUPPORT_EFFECT

    @property
    def icon(self):
        """Return the sensor icon."""
        return "mdi:hubspot"


class LoxoneLight(LoxoneEntity, ToggleEntity):
    """Representation of a light."""

    def __init__(self, **kwargs):
        LoxoneEntity.__init__(self, **kwargs)
        self._state = 0.0
        self._async_add_devices = kwargs['async_add_devices']
        self.light_controller_id = kwargs.get("lightcontroller_id", None)

    @property
    def device_info(self):
        if self.light_controller_id:
            return {
                "identifiers": {(DOMAIN, self.light_controller_id)},
                "name": self.name,
                "manufacturer": "Loxone",
                "model": "LightControllerV2",
                "type": self.type
            }
        else:
            return {
                "identifiers": {(DOMAIN, self.unique_id)},
                "name": self.name,
                "manufacturer": "Loxone",
                "model": "Light",
                "type": self.type
            }

    @property
    def state(self):
        """Return the state of the entity."""
        return STATE_ON if self._state == 1.0 else STATE_OFF

    @property
    def is_on(self) -> bool:
        if self.state == STATE_ON:
            return True
        else:
            return False

    def turn_on(self, **kwargs: Any) -> None:
        self.hass.bus.async_fire(SENDDOMAIN,
                                 dict(uuid=self.uuidAction, value="on"))
        self.schedule_update_ha_state()

    def turn_off(self, **kwargs: Any) -> None:
        self.hass.bus.async_fire(SENDDOMAIN,
                                 dict(uuid=self.uuidAction, value="off"))
        self.schedule_update_ha_state()

    @property
    def state_attributes(self):
        """Return device specific state attributes.

        Implemented by platform classes.
        """
        return {"uuid": self.uuidAction, "room": self.room,
                "category": self.cat,
                "device_typ": self.type, "plattform": "loxone"}

    @property
    def supported_features(self):
        """Flag supported features."""
        return 0

    async def event_handler(self, event):
        request_update = False
        if 'active' in self.states:
            if self.states['active'] in event.data:
                self._state = event.data[self.states['active']]
                request_update = True

        if request_update:
            self.async_schedule_update_ha_state()


class LoxoneColorPickerV2(LoxoneEntity, LightEntity):

    def __init__(self, **kwargs):
        LoxoneEntity.__init__(self, **kwargs)
        self._async_add_devices = kwargs['async_add_devices']
        self._position = 0
        self._color_temp = 0
        self._rgb_color = color_util.color_hs_to_RGB(0, 0)
        self.light_controller_id = kwargs.get("lightcontroller_id", None)

    @property
    def device_info(self):
        if self.light_controller_id:
            return {
                "identifiers": {(DOMAIN, self.light_controller_id)},
                "name": self.name,
                "manufacturer": "Loxone",
                "model": "LightControllerV2",
            }
        else:
            return {
                "identifiers": {(DOMAIN, self.unique_id)},
                "name": self.name,
                "manufacturer": "Loxone",
                "model": "Dimmer",
            }

    @property
    def device_class(self):
        """Return the class of this device, from component DEVICE_CLASSES."""
        return self.type

    @property
    def state(self):
        """Return the state of the entity."""
        return STATE_ON if self.is_on else STATE_OFF

    @property
    def is_on(self) -> bool:
        return self._position > 0

    def turn_on(self, **kwargs) -> None:
        if ATTR_BRIGHTNESS in kwargs:
            self.hass.bus.async_fire(SENDDOMAIN,
                                     dict(uuid=self.uuidAction,
                                          value='temp({},{})'.format(int(to_loxone_level(kwargs[ATTR_BRIGHTNESS])),
                                                                     int(to_loxone_color_temp(self._color_temp)))))

        elif ATTR_COLOR_TEMP in kwargs:
            self.hass.bus.async_fire(SENDDOMAIN,
                                     dict(uuid=self.uuidAction, value='temp({},{})'.format(self._position,
                                                                                           int(to_loxone_color_temp(
                                                                                               kwargs[
                                                                                                   ATTR_COLOR_TEMP]))
                                                                                           )))
        elif ATTR_HS_COLOR in kwargs:
            r, g, b = color_util.color_hs_to_RGB(kwargs[ATTR_HS_COLOR][0], kwargs[ATTR_HS_COLOR][1])
            h, s, v = color_util.color_RGB_to_hsv(r, g, b)
            self.hass.bus.async_fire(SENDDOMAIN,
                                     dict(uuid=self.uuidAction, value='hsv({},{},{})'.format(h, s, v)))
        else:
            self.hass.bus.async_fire(SENDDOMAIN, dict(uuid=self.uuidAction, value="setBrightness/1"))
        self.schedule_update_ha_state()

    def turn_off(self) -> None:
        self.hass.bus.async_fire(SENDDOMAIN, dict(uuid=self.uuidAction, value="setBrightness/0"))
        self.schedule_update_ha_state()

    @property
    def device_state_attributes(self):
        """Return device specific state attributes.

        Implemented by platform classes.
        """
        return {"uuid": self.uuidAction,
                "room": self.room,
                "category": self.cat,
                "device_typ": self.type,
                "plattform": "loxone"}

    async def event_handler(self, e):
        request_update = False
        if self.states['color'] in e.data:
            color = e.data[self.states['color']]
            if color.startswith('hsv'):
                color = color.replace('hsv', '')
                color = eval(color)
                self._rgb_color = color_util.color_hs_to_RGB(color[0], color[1])
                self._position = color[2]
                request_update = True

            elif color.startswith('temp'):
                color = color.replace('temp', '')
                color = eval(color)
                self._color_temp = to_hass_color_temp(color[1])
                self._position = color[0]
                request_update = True

        if request_update:
            self.async_schedule_update_ha_state()

    @property
    def brightness(self):
        """Return the brightness of the group lights."""
        return to_hass_level(self._position)

    @property
    def hs_color(self):
        return color_util.color_RGB_to_hs(self._rgb_color[0], self._rgb_color[1], self._rgb_color[2])

    @property
    def color_temp(self):
        return self._color_temp

    @property
    def min_mireds(self):
        return 153

    @property
    def max_mireds(self):
        return 500

    @property
    def white_value(self):
        return None

    @property
    def supported_features(self):
        return SUPPORT_BRIGHTNESS | SUPPORT_COLOR | SUPPORT_COLOR_TEMP

    @property
    def device_info(self):
        if self.light_controller_id:
            return {
                "identifiers": {(DOMAIN, self.light_controller_id)},
                "name": self.name,
                "manufacturer": "Loxone",
                "type": self.type,
                "model": "LightControllerV2",
            }
        else:
            return {
                "identifiers": {(DOMAIN, self.unique_id)},
                "name": self.name,
                "manufacturer": "Loxone",
                "model": "ColorPickerV2",
            }

    @property
    def icon(self):
        """Return the sensor icon."""
        return "mdi:eyedropper-variant"


class LoxoneDimmer(LoxoneEntity, LightEntity):
    """Representation of a Dimmer."""

    def __init__(self, **kwargs):
        LoxoneEntity.__init__(self, **kwargs)
        """Initialize the sensor."""
        self._state = False
        self._position = 0.0
        self._min = 0.0
        self._max = 100.0
        self._async_add_devices = kwargs['async_add_devices']
        self.light_controller_id = kwargs.get("lightcontroller_id", None)

    @property
    def device_info(self):
        if self.light_controller_id:
            return {
                "identifiers": {(DOMAIN, self.light_controller_id)},
                "name": self.name,
                "manufacturer": "Loxone",
                "model": "LightControllerV2",
            }
        else:
            return {
                "identifiers": {(DOMAIN, self.unique_id)},
                "name": self.name,
                "manufacturer": "Loxone",
                "model": "Dimmer",
            }

    @property
    def device_class(self):
        """Return the class of this device, from component DEVICE_CLASSES."""
        return self.type

    @property
    def hidden(self) -> bool:
        """Return True if the entity should be hidden from UIs."""
        return False

    @property
    def brightness(self):
        """Return the brightness of the group lights."""
        return to_hass_level(self._position)

    @property
    def icon(self):
        """Return the icon to use in the frontend, if any."""
        return None

    def turn_on(self, **kwargs) -> None:
        if ATTR_BRIGHTNESS in kwargs:
            self.hass.bus.async_fire(SENDDOMAIN,
                                     dict(uuid=self.uuidAction, value=to_loxone_level(kwargs[ATTR_BRIGHTNESS])))
        else:
            self.hass.bus.async_fire(SENDDOMAIN, dict(uuid=self.uuidAction, value="on"))
        self.schedule_update_ha_state()

    def turn_off(self, **kwargs) -> None:
        self.hass.bus.async_fire(SENDDOMAIN, dict(uuid=self.uuidAction, value="off"))
        self.schedule_update_ha_state()

    async def event_handler(self, e):
        request_update = False
        if self.states['position'] in e.data:
            self._position = e.data[self.states['position']]
            request_update = True

        if request_update:
            self.async_schedule_update_ha_state()

    @property
    def state(self):
        """Return the state of the entity."""
        return STATE_ON if self.is_on else STATE_OFF

    @property
    def is_on(self) -> bool:
        return self._position > 0

    @property
    def device_state_attributes(self):
        """Return device specific state attributes.

        Implemented by platform classes.
        """
        return {"uuid": self.uuidAction, "room": self.room,
                "category": self.cat,
                "device_typ": self.type, "plattform": "loxone"}

    @property
    def supported_features(self):
        return SUPPORT_BRIGHTNESS

    @property
    def icon(self):
        """Return the sensor icon."""
        return "mdi:brightness-6"