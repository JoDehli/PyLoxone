"""
Loxone Cover

For more details about this component, please refer to the documentation at
https://github.com/JoDehli/PyLoxone
"""

import logging
from typing import Any

from homeassistant.components.cover import (
    ATTR_POSITION,
    ATTR_TILT_POSITION,
    DEVICE_CLASS_AWNING,
    DEVICE_CLASS_BLIND,
    DEVICE_CLASS_CURTAIN,
    DEVICE_CLASS_DOOR,
    DEVICE_CLASS_GARAGE,
    DEVICE_CLASS_SHUTTER,
    DEVICE_CLASS_WINDOW,
    SUPPORT_CLOSE,
    SUPPORT_OPEN,
    CoverEntity,
)
from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.event import track_utc_time_change

from . import LoxoneEntity
from .const import (
    DOMAIN,
    SENDDOMAIN,
    SUPPORT_CLOSE_TILT,
    SUPPORT_OPEN_TILT,
    SUPPORT_SET_POSITION,
    SUPPORT_SET_TILT_POSITION,
    SUPPORT_STOP,
    SUPPORT_STOP_TILT,
)
from .helpers import (
    get_all_covers,
    get_cat_name_from_cat_uuid,
    get_room_name_from_room_uuid,
)
from .miniserver import get_miniserver_from_config_entry

_LOGGER = logging.getLogger(__name__)

NEW_COVERS = "covers"


async def async_setup_platform(hass, config, async_add_devices, discovery_info={}):
    """Set up the Loxone covers."""
    return True


async def async_setup_entry(hass, config_entry, async_add_entites):
    """Set Loxone covers."""
    miniserver = get_miniserver_from_config_entry(hass, config_entry)
    loxconfig = miniserver.lox_config.json
    covers = []

    for cover in get_all_covers(loxconfig):
        cover.update(
            {
                "hass": hass,
                "room": get_room_name_from_room_uuid(loxconfig, cover.get("room", "")),
                "cat": get_cat_name_from_cat_uuid(loxconfig, cover.get("cat", "")),
            }
        )

        if cover["type"] == "Gate":
            new_gate = LoxoneGate(**cover)
            covers.append(new_gate)
        elif cover["type"] == "Window":
            new_window = LoxoneWindow(**cover)
            covers.append(new_window)
        else:
            new_jalousie = LoxoneJalousie(**cover)
            covers.append(new_jalousie)

    @callback
    def async_add_covers(_):
        async_add_entites(_)

    miniserver.listeners.append(
        async_dispatcher_connect(
            hass, miniserver.async_signal_new_device(NEW_COVERS), async_add_entites
        )
    )
    async_add_entites(covers)

class LoxoneGate(LoxoneEntity, CoverEntity):
    """Loxone Gate"""

    def __init__(self, **kwargs):
        LoxoneEntity.__init__(self, **kwargs)
        self.hass = kwargs["hass"]
        self._position_uuid = kwargs["states"]["position"]
        self._state_uuid = kwargs["states"]["active"]
        self._position = None
        self._is_opening = False
        self._is_closing = False

        if self._position is None:
            self._closed = True
        else:
            self._closed = self.current_cover_position <= 0

    @property
    def supported_features(self):
        """Flag supported features."""
        return SUPPORT_OPEN | SUPPORT_CLOSE | SUPPORT_STOP

    @property
    def should_poll(self):
        """No polling needed for a demo cover."""
        return False

    @property
    def device_class(self):
        """Return the class of this device, from component DEVICE_CLASSES."""
        if self.animation == 0:
            return DEVICE_CLASS_GARAGE
        elif self.animation in [1, 2, 3, 4, 5]:
            return DEVICE_CLASS_DOOR
        return self.type

    @property
    def animation(self):
        return self.details["animation"]

    @property
    def current_cover_position(self):
        """Return the current position of the cover."""
        return self._position

    @property
    def is_closed(self):
        """Return if the cover is closed."""
        return self._closed

    @property
    def is_closing(self):
        """Return if the cover is closing."""
        return self._is_closing

    @property
    def is_opening(self):
        """Return if the cover is opening."""
        return self._is_opening

    def open_cover(self, **kwargs):
        """Open the cover."""
        if self._position == 100.0:
            return
        self.hass.bus.async_fire(SENDDOMAIN, dict(uuid=self.uuidAction, value="open"))
        self.schedule_update_ha_state()

    def close_cover(self, **kwargs):
        """Close the cover."""
        if self._position == 0:
            return
        self.hass.bus.async_fire(SENDDOMAIN, dict(uuid=self.uuidAction, value="close"))
        self.schedule_update_ha_state()

    def stop_cover(self, **kwargs):
        """Stop the cover."""
        if self.is_closing:
            self.hass.bus.async_fire(
                SENDDOMAIN, dict(uuid=self.uuidAction, value="open")
            )
            return

        if self.is_opening:
            self.hass.bus.async_fire(
                SENDDOMAIN, dict(uuid=self.uuidAction, value="close")
            )
            return

    async def event_handler(self, event):
        if self.states["position"] in event.data or self._state_uuid in event.data:
            if self.states["position"] in event.data:
                self._position = float(event.data[self.states["position"]]) * 100.0
                if self._position == 0:
                    self._closed = True
                else:
                    self._closed = False

            if self._state_uuid in event.data:
                self._is_closing = False
                self._is_opening = False

                if event.data[self._state_uuid] == -1:
                    self._is_opening = True
                elif event.data[self._state_uuid] == 1:
                    self._is_opening = True
            self.schedule_update_ha_state()

    @property
    def device_state_attributes(self):
        """Return device specific state attributes.

        Implemented by platform classes.
        """
        return {
            "uuid": self.uuidAction,
            "device_typ": self.type,
            "category": self.cat,
            "plattform": "loxone",
        }

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self.unique_id)},
            "name": self.name,
            "manufacturer": "Loxone",
            "model": "Gate",
            "type": self.type,
            "suggested_area": self.room
        }


class LoxoneWindow(LoxoneEntity, CoverEntity):

    # pylint: disable=no-self-use
    def __init__(self, **kwargs):
        LoxoneEntity.__init__(self, **kwargs)
        self.hass = kwargs["hass"]
        self._position = None
        self._closed = True
        self._direction = 0

    async def event_handler(self, e):
        if self.states["position"] in e.data or self.states["direction"] in e.data:

            if self.states["position"] in e.data:
                self._position = float(e.data[self.states["position"]]) * 100.0
                if self._position == 0:
                    self._closed = True
                else:
                    self._closed = False

            if self.states["direction"] in e.data:
                self._direction = e.data[self.states["direction"]]

            self.schedule_update_ha_state()

    @property
    def current_cover_position(self):
        """Return current position of cover.

        None is unknown, 0 is closed, 100 is fully open.
        """
        return self._position

    @property
    def device_state_attributes(self):
        """
        Return device specific state attributes.
        Implemented by platform classes.
        """
        device_att = {
            "uuid": self.uuidAction,
            "device_typ": self.type,
            "plattform": "loxone",
            "room": self.room,
            "category": self.cat,
        }
        return device_att

    @property
    def device_class(self):
        """Return the class of this device, from component DEVICE_CLASSES."""
        return DEVICE_CLASS_WINDOW

    @property
    def is_closing(self):
        """Return if the cover is closing."""
        if self._direction == -1:
            return True
        return False

    @property
    def is_opening(self):
        """Return if the cover is opening."""
        if self._direction == 1:
            return True
        return False

    @property
    def is_closed(self):
        return self._closed

    def open_cover(self, **kwargs: Any) -> None:
        self.hass.bus.async_fire(
            SENDDOMAIN, dict(uuid=self.uuidAction, value="fullopen")
        )

    def close_cover(self, **kwargs: Any) -> None:
        self.hass.bus.async_fire(
            SENDDOMAIN, dict(uuid=self.uuidAction, value="fullclose")
        )

    def stop_cover(self, **kwargs):
        """Stop the cover."""

        if self.is_closing:
            self.hass.bus.async_fire(
                SENDDOMAIN, dict(uuid=self.uuidAction, value="fullopen")
            )

        elif self.is_opening:
            self.hass.bus.async_fire(
                SENDDOMAIN, dict(uuid=self.uuidAction, value="fullclose")
            )

    def set_cover_position(self, **kwargs):
        """Return the current tilt position of the cover."""
        position = kwargs.get(ATTR_POSITION)
        self.hass.bus.async_fire(
            SENDDOMAIN,
            dict(uuid=self.uuidAction, value="moveToPosition/{}".format(position)),
        )

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self.unique_id)},
            "name": self.name,
            "manufacturer": "Loxone",
            "model": "Window",
             "suggested_area": self.room
        }


class LoxoneJalousie(LoxoneEntity, CoverEntity):
    """Loxone Jalousie"""

    # pylint: disable=no-self-use
    def __init__(self, **kwargs):
        LoxoneEntity.__init__(self, **kwargs)
        self.hass = kwargs["hass"]

        if "autoInfoText" not in self.states:
            self.states["autoInfoText"] = ""
        if "autoState" not in self.states:
            self.states["autoState"] = ""
        self._position = 0
        self._position_loxone = -1
        self._set_position = None
        self._set_tilt_position = None
        self._tilt_position = 0
        self._requested_closing = True
        self._unsub_listener_cover = None
        self._unsub_listener_cover_tilt = None
        self._is_opening = False
        self._is_closing = False
        self._animation = 0
        self._is_automatic = False
        self._auto_text = ""
        self._auto_state = 0

        if "isAutomatic" in self.details:
            self._is_automatic = self.details["isAutomatic"]
        if "animation" in self.details:
            self._animation = self.details["animation"]

        if self._position is None:
            self._closed = True
        else:
            self._closed = self.current_cover_position <= 0

    @property
    def name(self):
        return self._name

    @name.setter
    def name(self, n):
        self._name = n

    @property
    def supported_features(self):
        """Flag supported features."""
        supported_features = SUPPORT_OPEN | SUPPORT_CLOSE | SUPPORT_STOP

        if self.current_cover_position is not None:
            supported_features |= SUPPORT_SET_POSITION

        if self.current_cover_tilt_position is not None:
            supported_features |= (
                SUPPORT_OPEN_TILT
                | SUPPORT_CLOSE_TILT
                | SUPPORT_STOP_TILT
                | SUPPORT_SET_TILT_POSITION
            )
        return supported_features

    async def event_handler(self, e):
        if (
            self.states["position"] in e.data
            or self.states["shadePosition"] in e.data
            or self.states["up"] in e.data
            or self.states["down"] in e.data
            or self.states["autoInfoText"] in e.data
            or self.states["autoState"] in e.data
        ):

            if self.states["position"] in e.data:
                self._position_loxone = float(e.data[self.states["position"]]) * 100.0
                self._position = round(100.0 - self._position_loxone, 0)

                if self._position == 0:
                    self._closed = True
                else:
                    self._closed = False

            if self.states["shadePosition"] in e.data:
                if e.data[self.states["shadePosition"]] == 1:
                    self._tilt_position = 0
                else:
                    self._tilt_position = 100

            if self.states["up"] in e.data:
                self._is_opening = e.data[self.states["up"]]

            if self.states["down"] in e.data:
                self._is_closing = e.data[self.states["down"]]

            if self.states["autoInfoText"] in e.data:
                self._auto_text = e.data[self.states["autoInfoText"]]

            if self.states["autoState"] in e.data:
                self._auto_state = e.data[self.states["autoState"]]

            self.schedule_update_ha_state()

    @property
    def should_poll(self):
        """No polling needed for a demo cover."""
        return False

    @property
    def current_cover_position(self):
        """Return the current position of the cover."""
        return self._position

    @property
    def current_cover_tilt_position(self):
        """Return the current tilt position of the cover."""
        return self._tilt_position

    @property
    def is_closed(self):
        """Return if the cover is closed."""
        return self._closed

    @property
    def is_closing(self):
        """Return if the cover is closing."""
        return self._is_closing

    @property
    def is_opening(self):
        """Return if the cover is opening."""
        return self._is_opening

    @property
    def device_class(self):
        """Return the class of this device, from component DEVICE_CLASSES."""
        if self.animation in [0, 1]:
            return DEVICE_CLASS_BLIND
        elif self.animation in [2, 4, 5]:
            return DEVICE_CLASS_CURTAIN
        elif self.animation == 3:
            return DEVICE_CLASS_SHUTTER
        elif self.animation == 6:
            return DEVICE_CLASS_AWNING

    @property
    def animation(self):
        return self.details["animation"]

    @property
    def is_automatic(self):
        return self._is_automatic

    @property
    def auto(self):
        if self._is_automatic and self._auto_state:
            return STATE_ON
        else:
            return STATE_OFF

    @property
    def shade_postion_as_text(self):
        """Returns shade postionn as text"""
        if self.current_cover_tilt_position == 100 and self.current_cover_position < 10:
            return "shading on"
        else:
            return " "

    @property
    def device_state_attributes(self):
        """
        Return device specific state attributes.
        Implemented by platform classes.
        """
        device_att = {
            "uuid": self.uuidAction,
            "device_typ": self.type,
            "plattform": "loxone",
            "room": self.room,
            "category": self.cat,
            "current_position": self.current_cover_position,
            "current_shade_mode": self.shade_postion_as_text,
            "current_position_loxone_style": round(self._position_loxone, 0),
            "extra_data_template": [
                "${attributes.current_position} % open",
                "${attributes.current_shade_mode}",
            ],
        }

        if self._is_automatic:
            device_att.update(
                {"automatic_text": self._auto_text, "auto_state": self.auto}
            )

        return device_att

    def close_cover(self, **kwargs):
        """Close the cover."""
        if self._position == 0:
            return
        elif self._position is None:
            self._closed = True
            self.schedule_update_ha_state()
            return

        self.hass.bus.async_fire(
            SENDDOMAIN, dict(uuid=self.uuidAction, value="FullDown")
        )
        self.schedule_update_ha_state()

    def open_cover(self, **kwargs):
        """Open the cover."""
        if self._position == 100.0:
            return
        elif self._position is None:
            self._closed = False
            self.schedule_update_ha_state()
            return
        self.hass.bus.async_fire(SENDDOMAIN, dict(uuid=self.uuidAction, value="FullUp"))
        self.schedule_update_ha_state()

    def stop_cover(self, **kwargs):
        """Stop the cover."""

        if self.is_closing:
            self.hass.bus.async_fire(
                SENDDOMAIN, dict(uuid=self.uuidAction, value="FullUp")
            )

        elif self.is_opening:
            self.hass.bus.async_fire(
                SENDDOMAIN, dict(uuid=self.uuidAction, value="FullDown")
            )

        if self._unsub_listener_cover is not None:
            self._unsub_listener_cover()
            self._unsub_listener_cover = None
            self._set_position = None

    def close_cover_tilt(self, **kwargs):
        """Close the cover tilt."""
        if self._tilt_position in (0, None):
            return
        self.hass.bus.async_fire(
            SENDDOMAIN, dict(uuid=self.uuidAction, value="FullDown")
        )

    def open_cover_tilt(self, **kwargs):
        """Close the cover tilt."""

        if self._tilt_position in (100, None):
            return

        self.hass.bus.async_fire(SENDDOMAIN, dict(uuid=self.uuidAction, value="shade"))

    def set_cover_position(self, **kwargs):
        """Return the current tilt position of the cover."""
        position = kwargs.get(ATTR_POSITION)
        self._set_position = position
        if self._position == position:
            return
        self._requested_closing = position < self._position
        if position < self._position:
            self.close_cover()
        else:
            self.open_cover()
        self._listen_cover()

    def set_cover_tilt_position(self, **kwargs):
        """Move the cover tilt to a specific position."""
        tilt_position = kwargs.get(ATTR_TILT_POSITION)
        if tilt_position > 50:
            tilt_position = 100
        else:
            tilt_position = 0

        if tilt_position == 100:
            self.open_cover_tilt()
        else:
            self.close_cover_tilt()

    def _listen_cover(self):
        """Listen for changes in cover."""
        if self._unsub_listener_cover is None:
            self._unsub_listener_cover = track_utc_time_change(
                self.hass, self._time_changed_cover
            )

    def _time_changed_cover(self, _):
        """Track time changes."""
        if abs(self._position - self._set_position) < 5:
            self.stop_cover()
        elif self._requested_closing and self._position <= self._set_position:
            self.stop_cover()
        elif not self._requested_closing and self._position >= self._set_position:
            self.stop_cover()

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self.unique_id)},
            "name": self.name,
            "manufacturer": "Loxone",
            "model": "Jalousie",
            "type": self.type,
            "suggested_area": self.room
        }
