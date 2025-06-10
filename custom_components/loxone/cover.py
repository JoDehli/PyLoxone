"""
Loxone Cover

For more details about this component, please refer to the documentation at
https://github.com/JoDehli/PyLoxone
"""

import logging
import random
from typing import Any

from homeassistant.components.cover import (ATTR_POSITION, ATTR_TILT_POSITION,
                                            CoverDeviceClass, CoverEntity,
                                            CoverEntityFeature)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_platform
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from . import LoxoneEntity
from .const import (SENDDOMAIN, SERVICE_DISABLE_SUN_AUTOMATION,
                    SERVICE_ENABLE_SUN_AUTOMATION, SERVICE_QUICK_SHADE,
                    SUPPORT_QUICK_SHADE, SUPPORT_SUN_AUTOMATION)
from .helpers import (add_room_and_cat_to_value_values, get_all,
                      get_or_create_device, map_range)
from .miniserver import get_miniserver_from_hass

_LOGGER = logging.getLogger(__name__)

NEW_COVERS = "covers"


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up the Loxone covers."""
    return True


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set Loxone covers."""
    miniserver = get_miniserver_from_hass(hass)
    loxconfig = miniserver.lox_config.json
    entities = []

    for cover in get_all(loxconfig, ["Jalousie", "Gate", "Window"]):
        cover = add_room_and_cat_to_value_values(loxconfig, cover)
        cover.update(
            {
                "hass": hass,
            }
        )
        if cover["type"] == "Gate":
            new_gate = LoxoneGate(**cover)
            entities.append(new_gate)
        elif cover["type"] == "Window":
            new_window = LoxoneWindow(**cover)
            entities.append(new_window)
        else:
            new_jalousie = LoxoneJalousie(**cover)
            entities.append(new_jalousie)

    @callback
    def async_add_covers(_):
        async_add_entities(_)

    miniserver.listeners.append(
        async_dispatcher_connect(
            hass, miniserver.async_signal_new_device(NEW_COVERS), async_add_entities
        )
    )
    async_add_entities(entities)

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_ENABLE_SUN_AUTOMATION, {}, "enable_sun_automation"
    )

    platform.async_register_entity_service(
        SERVICE_DISABLE_SUN_AUTOMATION,
        {},
        "disable_sun_automation",
    )

    platform.async_register_entity_service(
        SERVICE_QUICK_SHADE,
        {},
        "quick_shade",
    )


class LoxoneGate(LoxoneEntity, CoverEntity):
    """Loxone Gate"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.hass = kwargs["hass"]
        self._position_uuid = kwargs["states"]["position"]
        self._state_uuid = kwargs["states"]["active"]
        self._position = None
        self._is_opening = False
        self._is_closing = False
        self.type = "Gate"
        self._attr_device_info = get_or_create_device(
            self.unique_id, self.name, self.type, self.room
        )

        if self._position is None:
            self._closed = True
        else:
            self._closed = self.current_cover_position <= 0

    @property
    def supported_features(self):
        """Flag supported features."""
        return (
            CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE | CoverEntityFeature.STOP
        )

    @property
    def should_poll(self):
        """No polling needed for a demo cover."""
        return False

    @property
    def device_class(self):
        """Return the class of this device, from component DEVICE_CLASSES."""
        if self.animation == 0:
            return CoverDeviceClass.GARAGE
        elif self.animation in [1, 2, 3]:
            return CoverDeviceClass.GATE
        elif self.animation in [4, 5]:
            return CoverDeviceClass.DOOR
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
        self.hass.bus.fire(SENDDOMAIN, dict(uuid=self.uuidAction, value="open"))
        self.schedule_update_ha_state()

    def close_cover(self, **kwargs):
        """Close the cover."""
        if self._position == 0:
            return
        self.hass.bus.fire(SENDDOMAIN, dict(uuid=self.uuidAction, value="close"))
        self.schedule_update_ha_state()

    def stop_cover(self, **kwargs):
        """Stop the cover."""
        if self.is_closing:
            self.hass.bus.fire(SENDDOMAIN, dict(uuid=self.uuidAction, value="open"))
            return

        if self.is_opening:
            self.hass.bus.fire(SENDDOMAIN, dict(uuid=self.uuidAction, value="close"))
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
                    self._is_closing = True
                elif event.data[self._state_uuid] == 1:
                    self._is_opening = True
            self.schedule_update_ha_state()

    @property
    def extra_state_attributes(self):
        """Return device specific state attributes.

        Implemented by platform classes.
        """
        return {
            "uuid": self.uuidAction,
            "device_type": self.type,
            "category": self.cat,
            "platform": "loxone",
        }


class LoxoneWindow(LoxoneEntity, CoverEntity):
    # pylint: disable=no-self-use
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.hass = kwargs["hass"]
        self._position = None
        self._closed = True
        self._direction = 0

        self.type = "Window"
        self._attr_device_info = get_or_create_device(
            self.unique_id, self.name, self.type, self.room
        )

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
    def extra_state_attributes(self):
        """
        Return device specific state attributes.
        Implemented by platform classes.
        """
        device_att = {
            "uuid": self.uuidAction,
            "device_type": self.type,
            "platform": "loxone",
            "room": self.room,
            "category": self.cat,
        }
        return device_att

    @property
    def device_class(self):
        """Return the class of this device, from component DEVICE_CLASSES."""
        return CoverDeviceClass.WINDOW

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
        self.hass.bus.fire(SENDDOMAIN, dict(uuid=self.uuidAction, value="fullopen"))

    def close_cover(self, **kwargs: Any) -> None:
        self.hass.bus.fire(SENDDOMAIN, dict(uuid=self.uuidAction, value="fullclose"))

    def stop_cover(self, **kwargs):
        """Stop the cover."""

        if self.is_closing:
            self.hass.bus.fire(SENDDOMAIN, dict(uuid=self.uuidAction, value="fullopen"))

        elif self.is_opening:
            self.hass.bus.fire(
                SENDDOMAIN, dict(uuid=self.uuidAction, value="fullclose")
            )

    def set_cover_position(self, **kwargs):
        """Return the current tilt position of the cover."""
        position = kwargs.get(ATTR_POSITION)
        self.hass.bus.fire(
            SENDDOMAIN,
            dict(uuid=self.uuidAction, value="moveToPosition/{}".format(position)),
        )


class LoxoneJalousie(LoxoneEntity, CoverEntity):
    """Loxone Jalousie"""

    # pylint: disable=no-self-use
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.hass = kwargs["hass"]

        if "autoInfoText" not in self.states:
            self.states["autoInfoText"] = ""
        if "autoState" not in self.states:
            self.states["autoState"] = ""
        self._position = 0
        self._position_loxone = -1
        self._tilt_position_loxone = 1
        self._set_position = None
        self._set_tilt_position = None
        self._tilt_position = None
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

        self.type = "Jalousie"
        self._attr_device_info = get_or_create_device(
            self.unique_id, self.name, self.type, self.room
        )

    @property
    def supported_features(self):
        """Flag supported features."""
        supported_features = (
            CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE | CoverEntityFeature.STOP
        )

        if self.current_cover_position is not None:
            supported_features |= CoverEntityFeature.SET_POSITION

        if (
            self.current_cover_tilt_position is not None
            and self.device_class == CoverDeviceClass.BLIND
        ):
            supported_features |= (
                CoverEntityFeature.OPEN_TILT
                | CoverEntityFeature.CLOSE_TILT
                | CoverEntityFeature.SET_TILT_POSITION
                | SUPPORT_QUICK_SHADE
            )

        if self._is_automatic:
            supported_features |= SUPPORT_SUN_AUTOMATION

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
                self._position = map_range(self._position_loxone, 0, 100, 100, 0)

                if self._position == 0:
                    self._closed = True
                else:
                    self._closed = False

            if self.states["shadePosition"] in e.data:
                self._tilt_position_loxone = (
                    float(e.data[self.states["shadePosition"]]) * 100.0
                )
                self._tilt_position = map_range(
                    self._tilt_position_loxone, 0, 100, 100, 0
                )

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
        if self.device_class == CoverDeviceClass.BLIND:
            return self._tilt_position
        return None

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
    def device_class(self) -> CoverDeviceClass | None:
        """Return the class of this device, from component DEVICE_CLASSES."""
        if self.animation == 0:
            return CoverDeviceClass.BLIND
        if self.animation == 1:
            return CoverDeviceClass.SHUTTER
        elif self.animation in [2, 4, 5]:
            return CoverDeviceClass.CURTAIN
        elif self.animation == 3:
            return (
                CoverDeviceClass.SHUTTER
            )  # not supported in newer versions (Schlotterer Retrolux)
        elif self.animation == 6:
            return CoverDeviceClass.AWNING
        return None

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
    def is_sun_automation_enabled(self) -> bool | None:
        """Return if sun automation is enabled"""
        return self.auto

    @property
    def shade_postion_as_text(self):
        """Returns shade postionn as text"""
        if self.current_cover_tilt_position == 100 and self.current_cover_position < 10:
            return "shading on"
        else:
            return " "

    @property
    def extra_state_attributes(self):
        """
        Return device specific state attributes.
        Implemented by platform classes.
        """
        device_att = {
            "uuid": self.uuidAction,
            "device_type": self.type,
            "platform": "loxone",
            "room": self.room,
            "category": self.cat,
            "current_position": self.current_cover_position,
            "current_shade_mode": self.shade_postion_as_text,
            "current_position_loxone_style": round(self._position_loxone, 0),
        }

        if self._is_automatic:
            device_att.update(
                {
                    "automatic_text": self._auto_text,
                    "auto_state": self.auto,
                    "is_sun_automation_enabled": self.is_sun_automation_enabled,
                }
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

        self.hass.bus.fire(SENDDOMAIN, dict(uuid=self.uuidAction, value="FullDown"))
        self.schedule_update_ha_state()

    def open_cover(self, **kwargs):
        """Open the cover."""
        if self._position == 100.0:
            return
        elif self._position is None:
            self._closed = False
            self.schedule_update_ha_state()
            return
        self.hass.bus.fire(SENDDOMAIN, dict(uuid=self.uuidAction, value="FullUp"))
        self.schedule_update_ha_state()

    def stop_cover(self, **kwargs):
        """Stop the cover."""
        self.hass.bus.fire(SENDDOMAIN, dict(uuid=self.uuidAction, value="stop"))

    def set_cover_position(self, **kwargs):
        """Return the current tilt position of the cover."""
        position = kwargs.get(ATTR_POSITION)
        mapped_pos = map_range(position, 0, 100, 100, 0)
        self.hass.bus.fire(
            SENDDOMAIN, dict(uuid=self.uuidAction, value=f"manualPosition/{mapped_pos}")
        )

    def open_cover_tilt(self, **kwargs):
        """Close the cover tilt."""
        position = 0.0 + random.uniform(0.000000001, 0.00900000)
        self.hass.bus.fire(
            SENDDOMAIN, dict(uuid=self.uuidAction, value=f"manualLamelle/{position}")
        )

    def stop_cover_tilt(self, **kwargs):
        """Stop the cover."""
        self.hass.bus.fire(SENDDOMAIN, dict(uuid=self.uuidAction, value="stop"))

    def close_cover_tilt(self, **kwargs):
        """Close the cover tilt."""
        position = 100.0 + random.uniform(0.000000001, 0.00900000)
        self.hass.bus.fire(
            SENDDOMAIN, dict(uuid=self.uuidAction, value=f"manualLamelle/{position}")
        )

    def set_cover_tilt_position(self, **kwargs):
        """Move the cover tilt to a specific position."""
        tilt_position = kwargs.get(ATTR_TILT_POSITION)
        mapped_pos = map_range(tilt_position, 0, 100, 100, 0)
        position = mapped_pos + random.uniform(0.000000001, 0.00900000)
        self.hass.bus.fire(
            SENDDOMAIN, dict(uuid=self.uuidAction, value=f"manualLamelle/{position}")
        )

    def enable_sun_automation(self, **kwargs):
        """Set sun automation."""
        self.hass.bus.fire(SENDDOMAIN, dict(uuid=self.uuidAction, value="auto"))

    def disable_sun_automation(self, **kwargs):
        """Set sun automation."""
        self.hass.bus.fire(SENDDOMAIN, dict(uuid=self.uuidAction, value="NoAuto"))

    def quick_shade(self, **kwargs: Any) -> None:
        """Set sun automation."""
        self.hass.bus.fire(SENDDOMAIN, dict(uuid=self.uuidAction, value="shade"))
