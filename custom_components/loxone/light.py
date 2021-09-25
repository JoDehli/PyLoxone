import logging
from typing import Any

import homeassistant.util.color as color_util
from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP,
    ATTR_EFFECT,
    ATTR_HS_COLOR,
    SUPPORT_BRIGHTNESS,
    SUPPORT_COLOR,
    SUPPORT_COLOR_TEMP,
    SUPPORT_EFFECT,
    LightEntity,
    ToggleEntity,
)
from homeassistant.const import STATE_UNKNOWN

from . import LoxoneEntity
from .const import DOMAIN, SENDDOMAIN, STATE_OFF, STATE_ON
from .helpers import (
    get_all_dimmer,
    get_all_light_controller,
    get_cat_name_from_cat_uuid,
    get_room_name_from_room_uuid,
    hass_to_lox,
    lox2hass_mapped,
    lox_to_hass,
    to_hass_color_temp,
    to_loxone_color_temp,
)
from .miniserver import get_miniserver_from_config_entry

_LOGGER = logging.getLogger(__name__)
DEFAULT_NAME = "Loxone Light Controller V2"
DEFAULT_FORCE_UPDATE = False


async def async_setup_platform(hass, config, async_add_devices, discovery_info=None):
    """Set up Loxone Light Controller."""
    return True


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up Loxone Light Controller."""
    miniserver = get_miniserver_from_config_entry(hass, config_entry)
    generate_subcontrols = config_entry.options.get(
        "generate_lightcontroller_subcontrols", False
    )
    loxconfig = miniserver.lox_config.json
    entites = []
    all_light_controller_dimmers = []
    all_color_picker = []
    all_switches = []
    all_dimmers = get_all_dimmer(loxconfig)

    for light_controller in get_all_light_controller(loxconfig):
        light_controller.update(
            {
                "room": get_room_name_from_room_uuid(
                    loxconfig, light_controller.get("room", "")
                ),
                "cat": get_cat_name_from_cat_uuid(
                    loxconfig, light_controller.get("cat", "")
                ),
                "async_add_devices": async_add_entities,
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
            }
        )
        new_color_picker = LoxoneColorPickerV2(**color_picker)
        entites.append(new_color_picker)

    async_add_entities(entites)


class LoxonelightcontrollerV2(LoxoneEntity, LightEntity):
    """Representation of a Light Controller V2."""

    def __init__(self, **kwargs):
        LoxoneEntity.__init__(self, **kwargs)
        self._state = STATE_UNKNOWN
        self._active_moods = []
        self._moodlist = []
        self._additional_moodlist = []
        self._async_add_devices = kwargs["async_add_devices"]

        self._master_brightness = STATE_UNKNOWN
        self._master_color = STATE_UNKNOWN
        self._master_color_temp = STATE_UNKNOWN
        self._master_color_uuid = None

        self.kwargs = kwargs
        self._uuid_dict = {}

        self._features = None
        details = kwargs["details"]
        self.states["masterColor"] = details.get("masterColor", None)
        self.states["masterValue"] = details.get("masterValue", None)
        self._features = None

        if len(kwargs.get("subControls", {})) == 1:
            control = kwargs.get("subControls")[next(iter(kwargs.get("subControls")))]
            if control["type"] == "ColorPickerV2":
                if control["details"]["pickerType"] == "Lumitech":
                    self.states["masterColor"] = control.get("states", {}).get(
                        "color", None
                    )
                    self._features = (
                        SUPPORT_EFFECT
                        | SUPPORT_BRIGHTNESS
                        | SUPPORT_COLOR
                        | SUPPORT_COLOR_TEMP
                    )
                elif control["details"]["pickerType"] == "Rgb":
                    self.states["masterColor"] = control.get("states", {}).get(
                        "color", None
                    )
                    self._uuid_dict[self.states["masterColor"]] = control["uuidAction"]
                    self._features = (
                        SUPPORT_EFFECT
                        | SUPPORT_BRIGHTNESS
                        | SUPPORT_COLOR
                        | SUPPORT_COLOR_TEMP
                    )
                else:
                    _LOGGER.error(
                        "Type not implemented! {}".format(
                            control["details"]["pickerType"]
                        )
                    )
            elif control["type"] == "Dimmer":
                self.states["masterValue"] = control.get("states", {}).get(
                    "position", None
                )
                self._uuid_dict[self.states["masterValue"]] = control["uuidAction"]
                self._features = SUPPORT_EFFECT | SUPPORT_BRIGHTNESS
            elif control["type"] == "Switch":
                self._features = 0
            else:
                _LOGGER.error("Type not implemented! {}".format(control["type"]))
        else:
            sub_types = []
            for uuid, control in kwargs.get("subControls", {}).items():
                if control["type"] not in sub_types:
                    sub_types.append(control["type"])
                if uuid.find("masterValue") > -1:
                    self.states["masterValue"] = control.get("states", {}).get(
                        "position", None
                    )
                    self._uuid_dict[self.states["masterValue"]] = control["uuidAction"]

                if uuid.find("masterColor") > -1:
                    self.states["masterColor"] = control.get("states", {}).get(
                        "color", None
                    )
                    self.states["masterTemp"] = control.get("states", {}).get(
                        "color", None
                    )
                    self._uuid_dict[self.states["masterColor"]] = control["uuidAction"]

            if "ColorPickerV2" in sub_types and self.states["masterColor"] is None:
                for uuid, control in kwargs.get("subControls", {}).items():
                    if control.get("states", {}).get("color", None):
                        self.states["masterColor"] = control.get("states", {}).get(
                            "color"
                        )
                        self.states["masterTemp"] = control.get("states", {}).get(
                            "color"
                        )
                        self._uuid_dict[self.states["masterColor"]] = control[
                            "uuidAction"
                        ]

            if len(sub_types) == 1:
                if "Switch" in sub_types:
                    self._features = SUPPORT_EFFECT
                elif "ColorPickerV2" in sub_types:
                    self._features = (
                        SUPPORT_EFFECT
                        | SUPPORT_BRIGHTNESS
                        | SUPPORT_COLOR
                        | SUPPORT_COLOR_TEMP
                    )
                elif "Dimmer" in sub_types:
                    self._features = SUPPORT_EFFECT | SUPPORT_BRIGHTNESS
                else:
                    _LOGGER.error("Case not implemented! {}".format(sub_types))
            else:
                if "ColorPickerV2" in sub_types:
                    self._features = (
                        SUPPORT_EFFECT
                        | SUPPORT_BRIGHTNESS
                        | SUPPORT_COLOR
                        | SUPPORT_COLOR_TEMP
                    )

                elif "Dimmer" in sub_types:
                    self._features = SUPPORT_EFFECT | SUPPORT_BRIGHTNESS
                elif "Switch" in sub_types:
                    self._features = SUPPORT_EFFECT
                else:
                    _LOGGER.error("Case not implemented! {}".format(sub_types))
                self._features = (
                    SUPPORT_EFFECT
                    | SUPPORT_BRIGHTNESS
                    | SUPPORT_COLOR
                    | SUPPORT_COLOR_TEMP
                )

    @property
    def supported_features(self):
        return self._features

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self.unique_id)},
            "name": self.name,
            "manufacturer": "Loxone",
            "model": "LightControllerV2",
            "suggested_area": self.room
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

    def turn_on(self, **kwargs) -> None:
        if ATTR_EFFECT in kwargs:
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
                    SENDDOMAIN, dict(uuid=self.uuidAction, value="on")
                )

                for _ in effect_ids:
                    self.hass.bus.async_fire(
                        SENDDOMAIN,
                        dict(uuid=self.uuidAction, value="addMood/{}".format(_)),
                    )

        if ATTR_BRIGHTNESS in kwargs:
            if self.states.get("masterValue", None):
                self.hass.bus.async_fire(
                    SENDDOMAIN,
                    dict(
                        uuid=self._uuid_dict.get(
                            self.states.get("masterValue"), self.uuidAction
                        ),
                        value="{}".format(round(hass_to_lox(kwargs[ATTR_BRIGHTNESS]))),
                    ),
                )
            elif self.color_temp:
                self.hass.bus.async_fire(
                    SENDDOMAIN,
                    dict(
                        uuid=self.uuidAction,
                        value="temp({},{})".format(
                            round(hass_to_lox(kwargs[ATTR_BRIGHTNESS])),
                            int(to_loxone_color_temp(self.color_temp)),
                        ),
                    ),
                )
            elif self.hs_color:
                r, g, b = color_util.color_hs_to_RGB(self.hs_color[0], self.hs_color[1])
                h, s, v = color_util.color_RGB_to_hsv(r, g, b)
                self.hass.bus.async_fire(
                    SENDDOMAIN,
                    dict(
                        uuid=self._uuid_dict.get(
                            self.states.get("masterColor"), self.uuidAction
                        ),
                        value="hsv({},{},{})".format(
                            h, s, round(hass_to_lox(kwargs[ATTR_BRIGHTNESS]))
                        ),
                    ),
                )

        if ATTR_HS_COLOR in kwargs:
            r, g, b = color_util.color_hs_to_RGB(
                kwargs[ATTR_HS_COLOR][0], kwargs[ATTR_HS_COLOR][1]
            )
            h, s, v = color_util.color_RGB_to_hsv(r, g, b)
            if self.brightness:
                v = round(hass_to_lox(self.brightness))
            self.hass.bus.async_fire(
                SENDDOMAIN,
                dict(
                    uuid=self._uuid_dict.get(
                        self.states.get("masterColor"), self.uuidAction
                    ),
                    value="hsv({},{},{})".format(h, s, v),
                ),
            )

        if ATTR_COLOR_TEMP in kwargs:
            self.hass.bus.async_fire(
                SENDDOMAIN,
                dict(
                    uuid=self._uuid_dict.get(
                        self.states.get("masterColor"), self.uuidAction
                    ),
                    value="temp({},{})".format(
                        round(hass_to_lox(self.brightness)),
                        int(to_loxone_color_temp(kwargs[ATTR_COLOR_TEMP])),
                    ),
                ),
            )

        if kwargs == {}:
            self.hass.bus.async_fire(SENDDOMAIN, dict(uuid=self.uuidAction, value="on"))
        self.schedule_update_ha_state()

    @property
    def brightness(self):
        """Return the brightness of this light between 0..255."""
        if self._master_brightness is STATE_UNKNOWN:
            return None
        return self._master_brightness

    @property
    def color_temp(self):
        if self._master_color_temp is STATE_UNKNOWN:
            return None
        return self._master_color_temp

    @property
    def hs_color(self):
        if self._master_color is STATE_UNKNOWN or self._master_color is None:
            return None
        return color_util.color_RGB_to_hs(
            self._master_color[0], self._master_color[1], self._master_color[2]
        )

    def turn_off(self, **kwargs) -> None:
        self.hass.bus.async_fire(SENDDOMAIN, dict(uuid=self.uuidAction, value="off"))
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

        if event.data.get(self.states["masterColor"], None):
            color = event.data.get(self.states["masterColor"])
            if color.startswith("hsv"):
                color = color.replace("hsv", "")
                color = eval(color)
                self._master_color = color_util.color_hs_to_RGB(color[0], color[1])
                self._master_color_temp = None
                self._master_brightness = lox_to_hass(color[2])
                request_update = True

            elif color.startswith("temp"):
                color = color.replace("temp", "")
                color = eval(color)
                self._master_color_temp = to_hass_color_temp(color[1])
                self._master_brightness = lox_to_hass(color[0])
                self._master_color = None
                request_update = True

        if event.data.get(self.states["masterValue"], None):
            brightness = event.data.get(self.states["masterValue"])
            if isinstance(brightness, (int, float)):
                self._master_brightness = lox_to_hass(brightness)
                self._master_color = None
                self._master_color_temp = None
                request_update = True
            else:
                _LOGGER.error("Not implemented!!!")

        # if event.data.get(self._master
        # _color_uuid, None):
        #     color = event.data.get(self._master_color_uuid)
        #     if isinstance(color, (int, float)):
        #         self._master_brightness = to_hass_level(color)
        #         self._master_color = None
        #         self._master_color_temp = None
        #         request_update = True
        #
        #     if color.startswith('hsv'):
        #         color = color.replace('hsv', '')
        #         color = eval(color)
        #         self._master_color = color_util.color_hs_to_RGB(color[0], color[1])
        #         self._master_color_temp = None
        #         self._master_brightness = to_hass_level(color[2])
        #         request_update = True
        #
        #     elif color.startswith('temp'):
        #         color = color.replace('temp', '')
        #         color = eval(color)
        #         self._master_color_temp = to_hass_color_temp(color[1])
        #         self._master_brightness = to_hass_level(color[0])
        #         self._master_color = None
        #         request_update = True
        # elif event.data.get(self._master_brightness_uuid, None):
        #     brightness = event.data.get(self._master_brightness_uuid)
        #     if isinstance(brightness, (int, float)):
        #         self._master_brightness = to_hass_level(brightness)
        #         self._master_color = None
        #         self._master_color_temp = None
        #         request_update = True
        #     else:
        #         _LOGGER.error("Not implemented!!!")

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
        return {
            "uuid": self.uuidAction,
            "room": self.room,
            "category": self.cat,
            "selected_scene": self.effect,
            "device_typ": self.type,
            "plattform": "loxone",
        }

    @property
    def icon(self):
        """Return the sensor icon."""
        return "mdi:hubspot"


class LoxoneLight(LoxoneEntity, LightEntity, ToggleEntity):
    """Representation of a light."""

    def __init__(self, **kwargs):
        LoxoneEntity.__init__(self, **kwargs)
        self._state = STATE_UNKNOWN
        self._async_add_devices = kwargs["async_add_devices"]
        self.light_controller_id = kwargs.get("lightcontroller_id", None)

    @property
    def device_info(self):
        if self.light_controller_id:
            return {
                "identifiers": {(DOMAIN, self.light_controller_id)},
                "name": self.name,
                "manufacturer": "Loxone",
                "model": "LightControllerV2",
                "suggested_area": self.room,
                "type": self.type,
            }
        else:
            return {
                "identifiers": {(DOMAIN, self.unique_id)},
                "name": self.name,
                "manufacturer": "Loxone",
                "model": "Light",
                "suggested_area": self.room,
                "type": self.type,
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
        self.hass.bus.async_fire(SENDDOMAIN, dict(uuid=self.uuidAction, value="on"))
        self.schedule_update_ha_state()

    def turn_off(self, **kwargs: Any) -> None:
        self.hass.bus.async_fire(SENDDOMAIN, dict(uuid=self.uuidAction, value="off"))
        self.schedule_update_ha_state()

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
            "plattform": "loxone",
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


class LoxoneColorPickerV2(LoxoneEntity, LightEntity):
    def __init__(self, **kwargs):
        LoxoneEntity.__init__(self, **kwargs)
        self._async_add_devices = kwargs["async_add_devices"]
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
            self.hass.bus.async_fire(
                SENDDOMAIN,
                dict(
                    uuid=self.uuidAction,
                    value="temp({},{})".format(
                        round(hass_to_lox(kwargs[ATTR_BRIGHTNESS])),
                        int(to_loxone_color_temp(self._color_temp)),
                    ),
                ),
            )

        elif ATTR_COLOR_TEMP in kwargs:
            self.hass.bus.async_fire(
                SENDDOMAIN,
                dict(
                    uuid=self.uuidAction,
                    value="temp({},{})".format(
                        self._position,
                        int(to_loxone_color_temp(kwargs[ATTR_COLOR_TEMP])),
                    ),
                ),
            )
        elif ATTR_HS_COLOR in kwargs:
            r, g, b = color_util.color_hs_to_RGB(
                kwargs[ATTR_HS_COLOR][0], kwargs[ATTR_HS_COLOR][1]
            )
            h, s, v = color_util.color_RGB_to_hsv(r, g, b)
            self.hass.bus.async_fire(
                SENDDOMAIN,
                dict(uuid=self.uuidAction, value="hsv({},{},{})".format(h, s, v)),
            )
        else:
            self.hass.bus.async_fire(
                SENDDOMAIN, dict(uuid=self.uuidAction, value="setBrightness/1")
            )
        self.schedule_update_ha_state()

    def turn_off(self) -> None:
        self.hass.bus.async_fire(
            SENDDOMAIN, dict(uuid=self.uuidAction, value="setBrightness/0")
        )
        self.schedule_update_ha_state()

    @property
    def device_state_attributes(self):
        """Return device specific state attributes.

        Implemented by platform classes.
        """
        return {
            "uuid": self.uuidAction,
            "room": self.room,
            "category": self.cat,
            "device_typ": self.type,
            "plattform": "loxone",
        }

    async def event_handler(self, e):
        request_update = False
        if self.states["color"] in e.data:
            color = e.data[self.states["color"]]
            if color.startswith("hsv"):
                color = color.replace("hsv", "")
                color = eval(color)
                self._rgb_color = color_util.color_hs_to_RGB(color[0], color[1])
                self._position = color[2]
                request_update = True

            elif color.startswith("temp"):
                color = color.replace("temp", "")
                color = eval(color)
                self._color_temp = to_hass_color_temp(color[1])
                self._position = color[0]
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
    def device_info(self):
        if self.light_controller_id:
            return {
                "identifiers": {(DOMAIN, self.light_controller_id)},
                "name": self.name,
                "manufacturer": "Loxone",
                "type": self.type,
                "model": "LightControllerV2",
                "suggested_area": self.room,
            }
        else:
            return {
                "identifiers": {(DOMAIN, self.unique_id)},
                "name": self.name,
                "manufacturer": "Loxone",
                "model": "ColorPickerV2",
                "suggested_area": self.room,
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

    @property
    def device_info(self):
        if self.light_controller_id:
            return {
                "identifiers": {(DOMAIN, self.light_controller_id)},
                "name": self.name,
                "manufacturer": "Loxone",
                "model": "LightControllerV2",
                "suggested_area": self.room
            }
        else:
            return {
                "identifiers": {(DOMAIN, self.unique_id)},
                "name": self.name,
                "manufacturer": "Loxone",
                "model": "Dimmer",
                "suggested_area": self.room
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
        return self._position

    @property
    def icon(self):
        """Return the icon to use in the frontend, if any."""
        return None

    def turn_on(self, **kwargs) -> None:
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
        self.schedule_update_ha_state()

    def turn_off(self, **kwargs) -> None:
        self.hass.bus.async_fire(SENDDOMAIN, dict(uuid=self.uuidAction, value="Off"))
        self.schedule_update_ha_state()

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
            if self._min is not None and self._max is not None:
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
    def device_state_attributes(self):
        """Return device specific state attributes.

        Implemented by platform classes.
        """
        return {
            "uuid": self.uuidAction,
            "room": self.room,
            "category": self.cat,
            "device_typ": self.type,
            "plattform": "loxone",
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
