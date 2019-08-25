import asyncio
import logging

from homeassistant.components.light import (
    SUPPORT_EFFECT,
    Light
)
from homeassistant.const import (
    CONF_VALUE_TEMPLATE)

from . import get_room_name_from_room_uuid, get_cat_name_from_cat_uuid, get_all_light_controller

_LOGGER = logging.getLogger(__name__)

DEFAULT_NAME = 'Loxone Light Controller V2'
DEFAULT_FORCE_UPDATE = False

CONF_UUID = "uuid"
EVENT = "loxone_event"
DOMAIN = 'loxone'
SENDDOMAIN = "loxone_send"

STATE_ON = "on"
STATE_OFF = "off"


@asyncio.coroutine
def async_setup_platform(hass, config, async_add_devices,
                         discovery_info=None):
    """Set up Loxone Light Controller."""
    if discovery_info is None:
        return

    value_template = config.get(CONF_VALUE_TEMPLATE)
    if value_template is not None:
        value_template.hass = hass

    config = hass.data[DOMAIN]
    loxconfig = config['loxconfig']
    devices = []
    for light_controller in get_all_light_controller(loxconfig):
        new_light_controller = LoxonelightcontrollerV2(name=light_controller['name'],
                                                       uuid=light_controller['uuidAction'],
                                                       sensortyp="lightcontrollerv2",
                                                       room=get_room_name_from_room_uuid(loxconfig,
                                                                                         light_controller['room']),
                                                       cat=get_cat_name_from_cat_uuid(loxconfig,
                                                                                      light_controller['cat']),
                                                       complete_data=light_controller,
                                                       async_add_devices=async_add_devices)

        hass.bus.async_listen(EVENT, new_light_controller.event_handler)
        devices.append(new_light_controller)

    async_add_devices(devices)
    return True


class LoxonelightcontrollerV2(Light):
    """Representation of a Sensor."""

    def __init__(self, name, uuid, sensortyp, room="", cat="",
                 complete_data=None, async_add_devices=None):
        """Initialize the sensor."""
        self._state = 0.0
        self._name = name
        self._uuid = uuid
        self._room = room
        self._cat = cat
        self._sensortyp = sensortyp
        self._data = complete_data
        self._action_uuid = uuid
        self._active_mood_uuid = ""
        self._moodlist_uuid = ""
        self._favorite_mood_uuid = ""
        self._additional_mood_uuid = ""
        self._active_moods = []
        self._moodlist = []
        self._additional_moodlist = []
        self._async_add_devices = async_add_devices

        if "states" in self._data:
            states = self._data['states']
            if "activeMoods" in states:
                self._active_mood_uuid = states["activeMoods"]

            if "moodList" in states:
                self._moodlist_uuid = states["moodList"]

            if "favoriteMoods" in states:
                self._favorite_mood_uuid = states["favoriteMoods"]

            if "additionalMoods" in states:
                self._additional_mood_uuid = states["additionalMoods"]

    @property
    def name(self):
        return self._name

    @property
    def uuid(self):
        return self._uuid

    @property
    def device_class(self):
        """Return the class of this device, from component DEVICE_CLASSES."""
        return self._sensortyp

    @property
    def mood_list_uuid(self):
        return self._moodlist_uuid

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

    def async_turn_on(self, **kwargs) -> None:

        if 'effect' in kwargs:
            effects = kwargs['effect'].split(",")
            if len(effects) == 1:
                mood_id = self.get_id_by_moodname(kwargs['effect'])
                if mood_id != kwargs['effect']:
                    self.hass.bus.async_fire(SENDDOMAIN,
                                             dict(uuid=self._uuid, value="changeTo/{}".format(mood_id)))
                else:
                    self.hass.bus.async_fire(SENDDOMAIN,
                                             dict(uuid=self._uuid, value="plus"))
            else:
                effect_ids = []
                for _ in effects:
                    mood_id = self.get_id_by_moodname(_)
                    if mood_id != _:
                        effect_ids.append(mood_id)

                self.hass.bus.async_fire(SENDDOMAIN,
                                         dict(uuid=self._uuid, value="off"))

                for _ in effect_ids:
                    self.hass.bus.async_fire(SENDDOMAIN, dict(uuid=self._uuid, value="addMood/{}".format(_)))

        else:
            self.hass.bus.async_fire(SENDDOMAIN,
                                     dict(uuid=self._uuid, value="plus"))
        self.schedule_update_ha_state()

    def turn_off(self, **kwargs) -> None:
        self.hass.bus.async_fire(SENDDOMAIN,
                                 dict(uuid=self._uuid, value="off"))
        self.schedule_update_ha_state()

    @property
    def name(self):
        """Return the name of the device if any."""
        return self._name

    @asyncio.coroutine
    def event_handler(self, event):
        request_update = False
        if self._uuid in event.data:
            self._state = event.data[self._uuid]
            request_update = True

        if self._active_mood_uuid in event.data:
            self._active_moods = eval(event.data[self._active_mood_uuid])
            request_update = True

        if self._moodlist_uuid in event.data:
            event.data[self._moodlist_uuid] = event.data[self._moodlist_uuid].replace("true", "True")
            event.data[self._moodlist_uuid] = event.data[self._moodlist_uuid].replace("false", "False")
            self._moodlist = eval(event.data[self._moodlist_uuid])
            request_update = True

        if self._additional_mood_uuid in event.data:
            self._additional_moodlist = eval(event.data[self._additional_mood_uuid])
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
        return {"uuid": self._uuid, "room": self._room,
                "category": self._cat,
                "selected_scene": self.effect,
                "device_typ": "lightcontrollerv2", "plattform": "loxone"}

    @property
    def supported_features(self):
        return SUPPORT_EFFECT
