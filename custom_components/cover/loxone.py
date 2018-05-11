"""
Loxone cover component.
"""
import asyncio
import json
import logging

from homeassistant.components.cover import (
    CoverDevice, SUPPORT_OPEN, SUPPORT_CLOSE)
from homeassistant.const import (
    CONF_VALUE_TEMPLATE)

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
def async_setup_platform(hass, config, async_add_devices, discovery_info=None):
    """Set up the Demo covers."""
    value_template = config.get(CONF_VALUE_TEMPLATE)
    if value_template is not None:
        value_template.hass = hass

    if discovery_info is not None:
        config = discovery_info['config']
        loxconfig = discovery_info['loxconfig']
    else:
        config = hass.data[DOMAIN]
        loxconfig = config['loxconfig']

    devices = []

    for cover in get_all_covers(loxconfig):
        if cover['type'] == "Gate":
            pass
            # new_cover = LoxoneCover(hass, cover['name'],
            #                         cover['uuidAction'],
            #                         position_uuid=cover['states']['position'],
            #                         device_class="Gate")
        else:
            new_cover = LoxoneCover(hass, cover['name'],
                                    cover['uuidAction'],
                                    position_uuid=cover['states'][
                                        'position'],
                                    shade_uuid=cover['states'][
                                        'shadePosition'],
                                    down_uuid=cover['states']['down'],
                                    up_uuid=cover['states']['up'],
                                    device_class="Jalousie")

            devices.append(new_cover)
            hass.bus.async_listen(EVENT, new_cover.event_handler)

    async_add_devices(devices)


class LoxoneCover(CoverDevice):
    """Loxone Cover"""

    # pylint: disable=no-self-use
    def __init__(self, hass, name, uuid, position_uuid=None,
                 shade_uuid=None, down_uuid=None, up_uuid=None,
                 position=None, tilt_position=None, device_class=None,
                 supported_features=None):
        self.hass = hass
        self._name = name
        self._uuid = uuid
        self._position_uuid = position_uuid
        self._shade_uuid = shade_uuid
        self._down_uuid = down_uuid
        self._up_uuid = up_uuid
        self._position = position
        self._device_class = device_class
        self._supported_features = supported_features
        self._set_position = None
        self._set_tilt_position = None
        self._tilt_position = tilt_position
        self._requested_closing = True
        self._requested_closing_tilt = True
        self._unsub_listener_cover = None
        self._unsub_listener_cover_tilt = None
        self._is_opening = False
        self._is_closing = False
        if position is None:
            self._closed = True
        else:
            self._closed = self.current_cover_position <= 0

    @property
    def supported_features(self):
        """Flag supported features."""
        supported_features = SUPPORT_OPEN | SUPPORT_CLOSE | SUPPORT_STOP
        if self.current_cover_tilt_position is not None:
            supported_features |= (SUPPORT_OPEN_TILT | SUPPORT_CLOSE_TILT)
        return supported_features

    @asyncio.coroutine
    def event_handler(self, event):
        if self._position_uuid in event.data or self._shade_uuid in event.data \
                or self._up_uuid in event.data or self._down_uuid in event.data:
            if self._position_uuid in event.data:
                position = float(event.data[self._position_uuid]) * 100.
                self._position = round(100. - position, 0)
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
            return

        if self.is_opening:
            self.hass.bus.async_fire(SENDDOMAIN,
                                     dict(uuid=self._uuid, value="down"))
            return

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