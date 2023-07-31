import logging
from abc import ABC
from typing import Any

import homeassistant.util.color as color_util
from homeassistant.components.light import (ATTR_BRIGHTNESS, ATTR_COLOR_TEMP,
                                            ATTR_EFFECT, ATTR_HS_COLOR,
                                            COLOR_MODE_COLOR_TEMP,
                                            COLOR_MODE_HS, SUPPORT_BRIGHTNESS,
                                            SUPPORT_COLOR, SUPPORT_COLOR_TEMP,
                                            SUPPORT_EFFECT, LightEntity,
                                            ToggleEntity)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from . import LoxoneEntity, get_miniserver_from_hass
from .const import DOMAIN, SENDDOMAIN, STATE_OFF, STATE_ON
from .helpers import (get_all, get_cat_name_from_cat_uuid,
                      get_room_name_from_room_uuid, hass_to_lox,
                      lox2hass_mapped, lox_to_hass, to_hass_color_temp,
                      to_loxone_color_temp)

_LOGGER = logging.getLogger(__name__)
DEFAULT_NAME = "Loxone Light Controller V2"
DEFAULT_FORCE_UPDATE = False


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """
    For now, we do nothing. Function is only to get rid of the error message of missing async_setup_platform
    """
    return True


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Loxone Light Controller."""
    miniserver = get_miniserver_from_hass(hass)
    generate_subcontrols = config_entry.options.get(
        "generate_lightcontroller_subcontrols", False
    )
    loxconfig = miniserver.structure
    entites = []
    all_light_controller_dimmers = []
    all_color_picker = []
    all_switches = []
    all_dimmers = get_all(loxconfig, ["Dimmer", "EIBDimmer"])

    for light_controller in get_all(loxconfig, "LightControllerV2"):
        light_controller.update(
            {
                "room": get_room_name_from_room_uuid(
                    loxconfig, light_controller.get("room", "")
                ),
                "cat": get_cat_name_from_cat_uuid(
                    loxconfig, light_controller.get("cat", "")
                ),
                "async_add_devices": async_add_entities,
                "config_entry": config_entry,
            }
        )
        new_light_controller = LoxonelightcontrollerV2(**light_controller)
        if "subControls" in light_controller:
            if generate_subcontrols:
                for sub_controll in light_controller["subControls"]:
                    if (
                        sub_controll.find("masterValue") > -1
                        or sub_controll.find("masterColor") > 1
                    ):
                        continue
                    if (
                        light_controller["subControls"][sub_controll]["type"]
                        == "Dimmer"
                    ):
                        light_controller["subControls"][sub_controll][
                            "room"
                        ] = light_controller.get("room", "")
                        light_controller["subControls"][sub_controll][
                            "cat"
                        ] = light_controller.get("cat", "")
                        light_controller["subControls"][sub_controll][
                            "lightcontroller_id"
                        ] = new_light_controller.unique_id
                        all_light_controller_dimmers.append(
                            light_controller["subControls"][sub_controll]
                        )

                    elif (
                        light_controller["subControls"][sub_controll]["type"]
                        == "Switch"
                    ):
                        light_controller["subControls"][sub_controll][
                            "room"
                        ] = light_controller.get("room", "")
                        light_controller["subControls"][sub_controll][
                            "cat"
                        ] = light_controller.get("cat", "")
                        light_controller["subControls"][sub_controll][
                            "lightcontroller_id"
                        ] = new_light_controller.unique_id
                        all_switches.append(
                            light_controller["subControls"][sub_controll]
                        )

                    elif (
                        light_controller["subControls"][sub_controll]["type"]
                        == "ColorPickerV2"
                    ):
                        light_controller["subControls"][sub_controll][
                            "room"
                        ] = light_controller.get("room", "")
                        light_controller["subControls"][sub_controll][
                            "cat"
                        ] = light_controller.get("cat", "")
                        light_controller["subControls"][sub_controll][
                            "lightcontroller_id"
                        ] = new_light_controller.unique_id
                        all_color_picker.append(
                            light_controller["subControls"][sub_controll]
                        )

        entites.append(new_light_controller)

    _ = all_dimmers + all_light_controller_dimmers

    for dimmer in _:
        if dimmer in all_light_controller_dimmers:
            dimmer.update(
                {
                    "room": get_room_name_from_room_uuid(
                        loxconfig, light_controller.get("room", "")
                    ),
                    "cat": get_cat_name_from_cat_uuid(
                        loxconfig, light_controller.get("cat", "")
                    ),
                    "async_add_devices": async_add_entities,
                    "config_entry": config_entry,
                }
            )
        else:
            dimmer.update(
                {
                    "room": get_room_name_from_room_uuid(
                        loxconfig, dimmer.get("room", "")
                    ),
                    "cat": get_cat_name_from_cat_uuid(loxconfig, dimmer.get("cat", "")),
                    "async_add_devices": async_add_entities,
                    "config_entry": config_entry,
                }
            )

        new_dimmer = LoxoneDimmer(**dimmer)
        entites.append(new_dimmer)

    for switch in all_switches:
        switch.update(
            {
                "room": get_room_name_from_room_uuid(
                    loxconfig, light_controller.get("room", "")
                ),
                "cat": get_cat_name_from_cat_uuid(
                    loxconfig, light_controller.get("cat", "")
                ),
                "async_add_devices": async_add_entities,
                "config_entry": config_entry,
            }
        )
        new_switch = LoxoneLight(**switch)
        entites.append(new_switch)

    for color_picker in all_color_picker:
        color_picker.update(
            {
                "room": get_room_name_from_room_uuid(
                    loxconfig, light_controller.get("room", "")
                ),
                "cat": get_cat_name_from_cat_uuid(
                    loxconfig, light_controller.get("cat", "")
                ),
                "async_add_devices": async_add_entities,
                "config_entry": config_entry,
            }
        )
        new_color_picker = LoxoneColorPickerV2(**color_picker)
        entites.append(new_color_picker)

    async_add_entities(entites)


class LoxonelightcontrollerV2(LoxoneEntity, LightEntity):
    """Representation of a Light Controller V2."""

    def turn_on(self, **kwargs: Any) -> None:
        pass

    def turn_off(self, **kwargs: Any) -> None:
        pass

    def __init__(self, **kwargs):
        LoxoneEntity.__init__(self, **kwargs)
        self._state = STATE_UNKNOWN
        self._active_moods = []
        self._moodlist = []
        self._additional_moodlist = []
        self._async_add_devices = kwargs["async_add_devices"]

        self.kwargs = kwargs
        self._uuid_dict = {}

        self._features = SUPPORT_EFFECT
        from collections import OrderedDict

        self._sub_controls = OrderedDict({})
        for uuid, control in kwargs.get("subControls", {}).items():
            self._sub_controls[uuid] = {
                "name": control["name"],
                "type": control["type"],
            }

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self.unique_id)},
            name=f"{DOMAIN} {self.name}",
            manufacturer="Loxone",
            suggested_area=self.room,
            model="LightControllerV2"
        )

    @property
    def supported_features(self):
        return self._features

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
                if mood["id"] == _id:
                    return mood["name"]
        return _id

    def get_id_by_moodname(self, _name):
        for mood in self._moodlist:
            if "id" in mood and "name" in mood:
                if mood["name"] == _name:
                    return mood["id"]
        return _name

    @property
    def effect_list(self):
        """Return the moods of light controller."""
        moods = []
        for mood in self._moodlist:
            if "name" in mood:
                moods.append(mood["name"])
        return moods

    @property
    def effect(self):
        """Return the current effect."""
        if len(self._active_moods) == 1:
            return self.get_moodname_by_id(self._active_moods[0])
        return None

    async def got_effect(self, **kwargs):
        effects = kwargs["effect"].split(",")
        if len(effects) == 1:
            mood_id = self.get_id_by_moodname(kwargs["effect"])
            if mood_id != kwargs["effect"]:
                self.hass.bus.async_fire(
                    SENDDOMAIN,
                    dict(uuid=self.uuidAction, value="changeTo/{}".format(mood_id)),
                )
            else:
                self.hass.bus.async_fire(
                    SENDDOMAIN, dict(uuid=self.uuidAction, value="plus")
                )
        else:
            effect_ids = []
            for _ in effects:
                mood_id = self.get_id_by_moodname(_.strip())
                if mood_id != _:
                    effect_ids.append(mood_id)

            self.hass.bus.async_fire(
                SENDDOMAIN, dict(uuid=self.uuidAction, value="plus")
            )

            for _ in effect_ids:
                self.hass.bus.async_fire(
                    SENDDOMAIN,
                    dict(uuid=self.uuidAction, value="addMood/{}".format(_)),
                )

    async def async_turn_on(self, **kwargs) -> None:
        if ATTR_EFFECT in kwargs:
            await self.got_effect(**kwargs)
        elif kwargs == {}:
            if self.state == STATE_OFF:
                self.hass.bus.async_fire(
                    SENDDOMAIN, dict(uuid=self.uuidAction, value="plus")
                )
        self.async_schedule_update_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        self.hass.bus.async_fire(SENDDOMAIN, dict(uuid=self.uuidAction, value="off"))
        self.async_schedule_update_ha_state()

    async def event_handler(self, event):
        request_update = False

        if self.uuidAction in event.data:
            self._state = event.data[self.uuidAction]
            request_update = True

        if self.states["activeMoods"] in event.data:
            self._active_moods = eval(event.data[self.states["activeMoods"]])
            request_update = True

        if self.states["moodList"] in event.data:
            event.data[self.states["moodList"]] = event.data[
                self.states["moodList"]
            ].replace("true", "True")
            event.data[self.states["moodList"]] = event.data[
                self.states["moodList"]
            ].replace("false", "False")
            self._moodlist = eval(event.data[self.states["moodList"]])
            request_update = True

        if self.states["additionalMoods"] in event.data:
            self._additional_moodlist = eval(event.data[self.states["additionalMoods"]])
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
    def extra_state_attributes(self):
        """Return device specific state attributes.

        Implemented by platform classes.
        """
        return {
            "uuid": self.uuidAction,
            "room": self.room,
            "category": self.cat,
            "selected_scene": self.effect,
            "device_typ": self.type,
            "platform": "loxone",
            "subcontrols": self._sub_controls,
        }

    @property
    def icon(self):
        """Return the sensor icon."""
        return "mdi:hubspot"


class LoxoneLight(LoxoneEntity, LightEntity, ToggleEntity, ABC):
    """Representation of a light."""

    def __init__(self, **kwargs):
        LoxoneEntity.__init__(self, **kwargs)
        self._state = STATE_UNKNOWN
        self._async_add_devices = kwargs["async_add_devices"]
        self.light_controller_id = kwargs.get("lightcontroller_id", None)
        if self.light_controller_id:
            self._attr_device_info = DeviceInfo(
                identifiers={(DOMAIN, self.light_controller_id)},
                name=f"{DOMAIN} {self.name}",
                manufacturer="Loxone",
                suggested_area=self.room,
                model="LightControllerV2"
            )
        else:
            self._attr_device_info = DeviceInfo(
                identifiers={(DOMAIN, self.unique_id)},
                name=f"{DOMAIN} {self.name}",
                manufacturer="Loxone",
                suggested_area=self.room,
                model="Light"
            )

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

    async def async_turn_on(self, **kwargs: Any) -> None:
        self.hass.bus.async_fire(SENDDOMAIN, dict(uuid=self.uuidAction, value="on"))
        self.async_schedule_update_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self.hass.bus.async_fire(SENDDOMAIN, dict(uuid=self.uuidAction, value="off"))
        self.async_schedule_update_ha_state()

    @property
    def state_attributes(self):
        """Return device specific state attributes.

        Implemented by platform classes.
        """
        return {
            "uuid": self.uuidAction,
            "room": self.room,
            "category": self.cat,
            "device_typ": self.type,
            "platform": "loxone",
        }

    @property
    def supported_features(self):
        """Flag supported features."""
        return 0

    async def event_handler(self, event):
        request_update = False
        if "active" in self.states:
            if self.states["active"] in event.data:
                self._state = event.data[self.states["active"]]
                request_update = True

        if request_update:
            self.async_schedule_update_ha_state()


class LoxoneColorPickerV2(LoxoneEntity, LightEntity, ABC):
    def __init__(self, **kwargs):
        LoxoneEntity.__init__(self, **kwargs)
        self._async_add_devices = kwargs["async_add_devices"]
        self._position = 0
        self._color_temp = 0
        self._rgb_color = color_util.color_hs_to_RGB(0, 0)
        self.light_controller_id = kwargs.get("lightcontroller_id", None)
        if self.light_controller_id:
            self._attr_device_info = DeviceInfo(
                identifiers={(DOMAIN, self.light_controller_id)},
                name=f"{DOMAIN} {self.name}",
                manufacturer="Loxone",
                suggested_area=self.room,
                model="LightControllerV2"
            )
        else:
            self._attr_device_info = DeviceInfo(
                identifiers={(DOMAIN, self.unique_id)},
                name=f"{DOMAIN} {self.name}",
                manufacturer="Loxone",
                suggested_area=self.room,
                model="ColorPickerV2"
            )

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

    async def async_turn_on(self, **kwargs) -> None:
        color_temp = None
        rgb = None
        brightness = None
        if ATTR_COLOR_TEMP in kwargs:
            color_temp = int(to_loxone_color_temp(kwargs[ATTR_COLOR_TEMP]))
        elif ATTR_HS_COLOR in kwargs:
            r, g, b = color_util.color_hs_to_RGB(
                kwargs[ATTR_HS_COLOR][0], kwargs[ATTR_HS_COLOR][1]
            )
            rgb = (r, g, b)
        if ATTR_BRIGHTNESS in kwargs:
            brightness = round(hass_to_lox(kwargs[ATTR_BRIGHTNESS]))

        if not brightness:
            brightness = round(hass_to_lox(self.brightness))

        if color_temp:
            self.hass.bus.async_fire(
                SENDDOMAIN,
                dict(
                    uuid=self.uuidAction,
                    value="temp({},{})".format(brightness, color_temp),
                ),
            )
        elif rgb:
            h, s, v = color_util.color_RGB_to_hsv(rgb[0], rgb[1], rgb[2])
            self.hass.bus.async_fire(
                SENDDOMAIN,
                dict(
                    uuid=self.uuidAction, value="hsv({},{},{})".format(h, s, brightness)
                ),
            )
        elif brightness:
            if self._attr_color_mode == COLOR_MODE_HS:
                r, g, b = color_util.color_hs_to_RGB(self.hs_color[0], self.hs_color[1])
                h, s, v = color_util.color_RGB_to_hsv(r, g, b)
                self.hass.bus.async_fire(
                    SENDDOMAIN,
                    dict(
                        uuid=self.uuidAction,
                        value="hsv({},{},{})".format(h, s, brightness),
                    ),
                )
            else:
                self.hass.bus.async_fire(
                    SENDDOMAIN,
                    dict(
                        uuid=self.uuidAction,
                        value="temp({},{})".format(
                            brightness, int(to_loxone_color_temp(self._color_temp))
                        ),
                    ),
                )
        else:
            self.hass.bus.async_fire(
                SENDDOMAIN, dict(uuid=self.uuidAction, value="setBrightness/2")
            )
        self.async_schedule_update_ha_state()

    async def async_turn_off(self) -> None:
        self.hass.bus.async_fire(
            SENDDOMAIN, dict(uuid=self.uuidAction, value="setBrightness/0")
        )
        self.async_schedule_update_ha_state()

    @property
    def extra_state_attributes(self):
        """Return device specific state attributes.

        Implemented by platform classes.
        """
        return {
            "uuid": self.uuidAction,
            "room": self.room,
            "category": self.cat,
            "device_typ": self.type,
            "platform": "loxone",
        }

    async def event_handler(self, e):
        request_update = False
        if self.states["color"] in e.data:
            color = e.data[self.states["color"]]
            if color.startswith("hsv"):
                color = color.replace("hsv", "")
                color = eval(color)
                self._color_temp = 0
                self._rgb_color = color_util.color_hs_to_RGB(color[0], color[1])
                self._position = color[2]
                self._attr_color_mode = COLOR_MODE_HS
                request_update = True

            elif color.startswith("temp"):
                color = color.replace("temp", "")
                color = eval(color)
                self._rgb_color = color_util.color_hs_to_RGB(0, 0)
                self._color_temp = to_hass_color_temp(color[1])
                self._position = color[0]
                self._attr_color_mode = COLOR_MODE_COLOR_TEMP
                request_update = True

        if request_update:
            self.async_schedule_update_ha_state()

    @property
    def brightness(self):
        """Return the brightness of the group lights."""
        return lox_to_hass(self._position)

    @property
    def hs_color(self):
        return color_util.color_RGB_to_hs(
            self._rgb_color[0], self._rgb_color[1], self._rgb_color[2]
        )

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
    def icon(self):
        """Return the sensor icon."""
        return "mdi:eyedropper-variant"


class LoxoneDimmer(LoxoneEntity, LightEntity, ABC):
    """Representation of a Dimmer."""

    def __init__(self, **kwargs):
        LoxoneEntity.__init__(self, **kwargs)
        """Initialize the sensor."""
        self._state = STATE_UNKNOWN
        self._position = 0.0
        self._min_uuid = kwargs.get("states", {}).get("min", None)
        self._max_uuid = kwargs.get("states", {}).get("max", None)
        self._step_uuid = kwargs.get("states", {}).get("step", None)
        self._min = STATE_UNKNOWN
        self._max = STATE_UNKNOWN
        self._step = 1
        self._async_add_devices = kwargs["async_add_devices"]
        self.light_controller_id = kwargs.get("lightcontroller_id", None)

        if self.light_controller_id:
            self._attr_device_info = DeviceInfo(
                identifiers={(DOMAIN, self.light_controller_id)},
                name=f"{DOMAIN} {self.name}",
                manufacturer="Loxone",
                suggested_area=self.room,
                model="LightControllerV2"
            )
        else:
            self._attr_device_info = DeviceInfo(
                identifiers={(DOMAIN, self.unique_id)},
                name=f"{DOMAIN} {self.name}",
                manufacturer="Loxone",
                suggested_area=self.room,
                model="Dimmer"
            )

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
        return self._position

    @property
    def icon(self):
        """Return the icon to use in the frontend, if any."""
        return None

    async def async_turn_on(self, **kwargs) -> None:
        if ATTR_BRIGHTNESS in kwargs:
            self.hass.bus.async_fire(
                SENDDOMAIN,
                dict(
                    uuid=self.uuidAction,
                    value=round(hass_to_lox(kwargs[ATTR_BRIGHTNESS])),
                ),
            )
        else:
            self.hass.bus.async_fire(SENDDOMAIN, dict(uuid=self.uuidAction, value="On"))
        self.async_schedule_update_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        self.hass.bus.async_fire(SENDDOMAIN, dict(uuid=self.uuidAction, value="Off"))
        self.async_schedule_update_ha_state()

    async def event_handler(self, e):
        request_update = False
        if self._min_uuid in e.data:
            self._min = e.data[self._min_uuid]
            request_update = True

        if self._max_uuid in e.data:
            self._max = e.data[self._max_uuid]
            request_update = True

        if self._step_uuid in e.data:
            self._step = e.data[self._step_uuid]
            request_update = True

        if self.states["position"] in e.data and isinstance(
            e.data[self.states["position"]], (int, float)
        ):
            if (
                self._min is not None
                and self._max is not None
                and self._min != "unknown"
                and self._max != "unknown"
            ):
                self._position = lox2hass_mapped(
                    e.data[self.states["position"]], self._min, self._max
                )
            else:
                self._position = lox_to_hass(e.data[self.states["position"]])
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
    def extra_state_attributes(self):
        """Return device specific state attributes.

        Implemented by platform classes.
        """
        return {
            "uuid": self.uuidAction,
            "room": self.room,
            "category": self.cat,
            "device_typ": self.type,
            "platform": "loxone",
            "max": self._max,
            "min": self._min,
        }

    @property
    def supported_features(self):
        return SUPPORT_BRIGHTNESS

    @property
    def icon(self):
        """Return the sensor icon."""
        return "mdi:brightness-6"
