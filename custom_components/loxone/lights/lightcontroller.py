from collections import OrderedDict
from functools import cached_property

from homeassistant.components.light import (ATTR_BRIGHTNESS, ATTR_EFFECT,
                                            ColorMode, LightEntity,
                                            LightEntityFeature)
from homeassistant.const import STATE_UNKNOWN
from homeassistant.helpers.entity import DeviceInfo

from .. import LoxoneEntity
from ..const import DOMAIN, SENDDOMAIN, STATE_OFF
from ..helpers import get_or_create_device, hass_to_lox, lox2hass_mapped, lox_to_hass


class LoxoneLightControllerV2(LoxoneEntity, LightEntity):
    """Representation of a Light Controller V2."""

    _attr_supported_features = LightEntityFeature.EFFECT
    _attr_color_mode = ColorMode.ONOFF
    _attr_supported_color_modes = {ColorMode.ONOFF}

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._state = STATE_UNKNOWN
        self._active_moods = []
        self._moodlist = []
        self._additional_moodlist = []
        self._attr_brightness = None
        self._master_value = None
        self._master_value_uuid = None
        self._master_position_uuid = None
        self._master_min_uuid = None
        self._master_max_uuid = None
        self._master_min = STATE_UNKNOWN
        self._master_max = STATE_UNKNOWN
        self._async_add_devices = kwargs["async_add_devices"]

        self.kwargs = kwargs
        self._uuid_dict = {}

        self._sub_controls = OrderedDict({})
        for uuid, control in kwargs.get("subControls", {}).items():
            self._sub_controls[uuid] = {
                "name": control["name"],
                "type": control["type"],
            }
            if "masterValue" in uuid and control.get("type") in ["Dimmer", "EIBDimmer"]:
                self._master_value = control

        if self._master_value:
            self._master_value_uuid = self._master_value.get("uuidAction")
            self._master_position_uuid = self._master_value.get("states", {}).get(
                "position"
            )
            self._master_min_uuid = self._master_value.get("states", {}).get("min")
            self._master_max_uuid = self._master_value.get("states", {}).get("max")
            self._attr_color_mode = ColorMode.BRIGHTNESS
            self._attr_supported_color_modes = {ColorMode.BRIGHTNESS}

        self.type = "LightControllerV2"
        self._attr_device_info = get_or_create_device(
            self.unique_id, self.name, self.type, self.room
        )

    @property
    def device_class(self):
        """Return the class of this device, from component DEVICE_CLASSES."""
        return self.type

    @property
    def mood_list_uuid(self):
        return self.states["moodList"]

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
                SENDDOMAIN,
                dict(uuid=self.uuidAction, value="changeTo/{}".format(effect_ids[0])),
            )

            for _ in effect_ids[1:]:
                self.hass.bus.async_fire(
                    SENDDOMAIN,
                    dict(uuid=self.uuidAction, value="addMood/{}".format(_)),
                )

    async def async_turn_on(self, **kwargs) -> None:
        if ATTR_EFFECT in kwargs:
            await self.got_effect(**kwargs)
        elif ATTR_BRIGHTNESS in kwargs and self._master_value_uuid:
            self.hass.bus.async_fire(
                SENDDOMAIN,
                dict(
                    uuid=self._master_value_uuid,
                    value=round(hass_to_lox(kwargs[ATTR_BRIGHTNESS])),
                ),
            )
        elif kwargs == {}:
            if self.state == STATE_OFF:
                self.hass.bus.async_fire(
                    SENDDOMAIN, dict(uuid=self.uuidAction, value="changeTo/99")
                )
        self.async_schedule_update_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        self.hass.bus.async_fire(
            SENDDOMAIN, dict(uuid=self.uuidAction, value="changeTo/0")
        )
        self.async_schedule_update_ha_state()

    async def event_handler(self, event):
        request_update = False

        if self.uuidAction in event.data:
            self._state = event.data[self.uuidAction]
            request_update = True

        if self._master_min_uuid and self._master_min_uuid in event.data:
            self._master_min = event.data[self._master_min_uuid]
            request_update = True

        if self._master_max_uuid and self._master_max_uuid in event.data:
            self._master_max = event.data[self._master_max_uuid]
            request_update = True

        if self._master_position_uuid and self._master_position_uuid in event.data:
            if (
                self._master_min is not None
                and self._master_max is not None
                and self._master_min != "unknown"
                and self._master_max != "unknown"
            ):
                self._attr_brightness = lox2hass_mapped(
                    event.data[self._master_position_uuid],
                    self._master_min,
                    self._master_max,
                )
            else:
                self._attr_brightness = lox_to_hass(
                    event.data[self._master_position_uuid]
                )
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
            **self._attr_extra_state_attributes,
            "selected_scene": self.effect,
            "selected_scenes": [
                self.get_moodname_by_id(id) for id in self._active_moods
            ],
            "device_type": self.type,
            "subcontrols": self._sub_controls,
        }

    @cached_property
    def icon(self):
        """Return the sensor icon."""
        return "mdi:hubspot"
