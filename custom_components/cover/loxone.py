"""
Loxone cover component.
"""
import asyncio
import logging

from homeassistant.components.cover import (
    CoverDevice, SUPPORT_OPEN, SUPPORT_CLOSE, ATTR_POSITION)
from homeassistant.const import (
    CONF_VALUE_TEMPLATE)
from homeassistant.helpers.event import track_utc_time_change

_LOGGER = logging.getLogger(__name__)

DOMAIN = 'loxone'
EVENT = "loxone_event"
SENDDOMAIN = "loxone_send"

SUPPORT_OPEN = 1
SUPPORT_CLOSE = 2
SUPPORT_SET_POSITION = 4
SUPPORT_STOP = 8
SUPPORT_OPEN_TILT = 16
SUPPORT_CLOSE_TILT = 32
SUPPORT_STOP_TILT = 64
SUPPORT_SET_TILT_POSITION = 128


def get_all_covers(json_data):
    controls = []
    for c in json_data['controls'].keys():
        if json_data['controls'][c]['type'] in ["Jalousie", "Gate"]:
            controls.append(json_data['controls'][c])
    return controls


@asyncio.coroutine
def async_setup_platform(hass, config, async_add_devices, discovery_info={}):
    """Set up the Demo covers."""
    value_template = config.get(CONF_VALUE_TEMPLATE)
    if value_template is not None:
        value_template.hass = hass

    config = hass.data[DOMAIN]
    loxconfig = config['loxconfig']

    devices = []

    for cover in get_all_covers(loxconfig):
        if cover['type'] == "Gate":
            new_gate = LoxoneGate(hass, cover['name'],
                                  cover['uuidAction'],
                                  position_uuid=cover['states']['position'],
                                  state_uuid=cover['states']['active'],
                                  device_class="Gate",
                                  complete_data=cover)
            devices.append(new_gate)
            hass.bus.async_listen(EVENT, new_gate.event_handler)
        else:
            new_jalousie = LoxoneJalousie(hass, cover['name'],
                                          cover['uuidAction'],
                                          position_uuid=cover['states'][
                                              'position'],
                                          shade_uuid=cover['states'][
                                              'shadePosition'],
                                          down_uuid=cover['states']['down'],
                                          up_uuid=cover['states']['up'],
                                          device_class="Jalousie",
                                          complete_data=cover)

            devices.append(new_jalousie)
            hass.bus.async_listen(EVENT, new_jalousie.event_handler)

    async_add_devices(devices)


class LoxoneGate(CoverDevice):
    """Loxone Jalousie"""

    def __init__(self, hass, name, uuid, position_uuid=None, state_uuid=None,
                 device_class=None, complete_data=None):
        self.hass = hass
        self._name = name
        self._uuid = uuid
        self._position_uuid = position_uuid
        self._state_uuid = state_uuid
        self._device_class = device_class
        self._complete_data = complete_data
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
    def name(self):
        """Return the name of the cover."""
        return self._name

    @property
    def should_poll(self):
        """No polling needed for a demo cover."""
        return False

    @property
    def device_class(self):
        """Return the class of this device, from component DEVICE_CLASSES."""
        return self._device_class

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
        if self._position == 100.:
            return
        self.hass.bus.async_fire(SENDDOMAIN,
                                 dict(uuid=self._uuid, value="open"))
        self.schedule_update_ha_state()

    def close_cover(self, **kwargs):
        """Close the cover."""
        if self._position == 0:
            return
        self.hass.bus.async_fire(SENDDOMAIN,
                                 dict(uuid=self._uuid, value="close"))
        self.schedule_update_ha_state()

    def stop_cover(self, **kwargs):
        """Stop the cover."""
        if self.is_closing:
            self.hass.bus.async_fire(SENDDOMAIN,
                                     dict(uuid=self._uuid, value="open"))
            return

        if self.is_opening:
            self.hass.bus.async_fire(SENDDOMAIN,
                                     dict(uuid=self._uuid, value="close"))
            return

    @asyncio.coroutine
    def event_handler(self, event):
        if self._position_uuid in event.data or self._state_uuid in event.data:
            if self._position_uuid in event.data:
                self._position = float(event.data[self._position_uuid]) * 100.
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
        return {"uuid": self._uuid, "device_typ": "gate",
                "plattform": "loxone"}


class LoxoneJalousie(CoverDevice):
    """Loxone Jalousie"""

    # pylint: disable=no-self-use
    def __init__(self, hass, name, uuid, position_uuid=None,
                 shade_uuid=None, down_uuid=None, up_uuid=None,
                 device_class=None, complete_data=None):
        self.hass = hass
        self._name = name
        self._uuid = uuid
        self._position_uuid = position_uuid
        self._shade_uuid = shade_uuid
        self._down_uuid = down_uuid
        self._up_uuid = up_uuid
        self._device_class = device_class
        self._position = None
        self._position_loxone = -1
        self._set_position = None
        self._set_tilt_position = None
        self._tilt_position = None
        self._requested_closing = True
        self._unsub_listener_cover = None
        self._unsub_listener_cover_tilt = None
        self._is_opening = False
        self._is_closing = False
        self._complete_data = complete_data
        self._supported_features = None
        if self._position is None:
            self._closed = True
        else:
            self._closed = self.current_cover_position <= 0

    @property
    def supported_features(self):
        """Flag supported features."""
        supported_features = SUPPORT_OPEN | SUPPORT_CLOSE | SUPPORT_STOP \
                             | SUPPORT_SET_POSITION
        if self.current_cover_tilt_position is not None:
            supported_features |= (SUPPORT_OPEN_TILT | SUPPORT_CLOSE_TILT)
        return supported_features

    @asyncio.coroutine
    def event_handler(self, event):
        if self._position_uuid in event.data or \
                self._shade_uuid in event.data or \
                self._up_uuid in event.data or \
                self._down_uuid in event.data:
            if self._position_uuid in event.data:
                self._position_loxone = float(
                    event.data[self._position_uuid]) * 100.
                self._position = round(100. - self._position_loxone, 0)

                if self._position == 0:
                    self._closed = True
                else:
                    self._closed = False

            if self._shade_uuid in event.data:
                if event.data[self._shade_uuid] == 1:
                    self._tilt_position = 0
                else:
                    self._tilt_position = 100

            if self._up_uuid in event.data:
                self._is_opening = event.data[self._up_uuid]

            if self._down_uuid in event.data:
                self._is_closing = event.data[self._down_uuid]

            self.schedule_update_ha_state()

    @property
    def name(self):
        """Return the name of the cover."""
        return self._name

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
        return self._device_class

    @property
    def shade_postion_as_text(self):
        """Returns shade postionn as text"""
        if self.current_cover_tilt_position == 100 and \
                self.current_cover_position < 10:
            return "shading on"
        else:
            return " "

    @property
    def device_state_attributes(self):
        """
        Return device specific state attributes.
        Implemented by platform classes.
        """
        return {"uuid": self._uuid, "device_typ": "jalousie",
                "plattform": "loxone",
                "current_position": self.current_cover_position,
                "current_shade_mode": self.shade_postion_as_text,
                "current_position_loxone_style": round(self._position_loxone, 0),
                "extra_data_template": [
                    "${attributes.current_position} % open",
                    "${attributes.current_shade_mode}"
                ]}

    def close_cover(self, **kwargs):
        """Close the cover."""
        if self._position == 0:
            return
        elif self._position is None:
            self._closed = True
            self.schedule_update_ha_state()
            return

        self.hass.bus.async_fire(SENDDOMAIN,
                                 dict(uuid=self._uuid, value="FullDown"))
        self.schedule_update_ha_state()

    def open_cover(self, **kwargs):
        """Open the cover."""
        if self._position == 100.:
            return
        elif self._position is None:
            self._closed = False
            self.schedule_update_ha_state()
            return
        self.hass.bus.async_fire(SENDDOMAIN,
                                 dict(uuid=self._uuid, value="FullUp"))
        self.schedule_update_ha_state()

    def stop_cover(self, **kwargs):
        """Stop the cover."""

        if self.is_closing:
            self.hass.bus.async_fire(SENDDOMAIN,
                                     dict(uuid=self._uuid, value="up"))

        elif self.is_opening:
            self.hass.bus.async_fire(SENDDOMAIN,
                                     dict(uuid=self._uuid, value="down"))

        if self._unsub_listener_cover is not None:
            self._unsub_listener_cover()
            self._unsub_listener_cover = None
            self._set_position = None

    def close_cover_tilt(self, **kwargs):
        """Close the cover tilt."""
        if self._tilt_position in (0, None):
            return
        self.hass.bus.async_fire(SENDDOMAIN,
                                 dict(uuid=self._uuid, value="FullDown"))

    def open_cover_tilt(self, **kwargs):
        """Close the cover tilt."""

        if self._tilt_position in (100, None):
            return

        self.hass.bus.async_fire(SENDDOMAIN,
                                 dict(uuid=self._uuid, value="shade"))

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

    def _listen_cover(self):
        """Listen for changes in cover."""
        if self._unsub_listener_cover is None:
            self._unsub_listener_cover = track_utc_time_change(
                self.hass, self._time_changed_cover)

    def _time_changed_cover(self, now):
        """Track time changes."""
        if abs(self._position - self._set_position) < 5:
            self.stop_cover()
        elif self._requested_closing and self._position <= self._set_position:
            self.stop_cover()
        elif not self._requested_closing and self._position >= self._set_position:
            self.stop_cover()
