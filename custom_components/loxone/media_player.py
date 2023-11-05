"""Support for Loxone Audio zone media player."""
from __future__ import annotations

import logging

from homeassistant.components.media_player import (MediaPlayerDeviceClass,
                                                   MediaPlayerEntity,
                                                   MediaPlayerEntityFeature,
                                                   MediaPlayerState)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from . import LoxoneEntity
from .const import DEFAULT_AUDIO_ZONE_V2_PLAY_STATE, DOMAIN, SENDDOMAIN
from .helpers import (get_all, get_cat_name_from_cat_uuid,
                      get_room_name_from_room_uuid)
from .miniserver import get_miniserver_from_hass

_LOGGER = logging.getLogger(__name__)

PARALLEL_UPDATES = 0
DEFAULT_FORCE_UPDATE = False

# This is the "optimistic" view of supported features and will be returned until the
# actual set of supported feature have been determined (will always be all or a subset
# of these).
SUPPORT_LOXONE_AUDIO_ZONE = (
    MediaPlayerEntityFeature.PAUSE
    | MediaPlayerEntityFeature.PLAY
    | MediaPlayerEntityFeature.NEXT_TRACK
    | MediaPlayerEntityFeature.PREVIOUS_TRACK
    | MediaPlayerEntityFeature.VOLUME_SET
    | MediaPlayerEntityFeature.VOLUME_STEP
)


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up Loxone Audio zones."""
    return True


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Load Loxone Audio zones based on a config entry."""
    miniserver = get_miniserver_from_hass(hass)
    loxconfig = miniserver.lox_config.json
    entites = []

    for audioZone in get_all(loxconfig, "AudioZoneV2"):
        audioZone.update(
            {
                "hass": hass,
                "typ": "AudioZoneV2",
                "room": get_room_name_from_room_uuid(
                    loxconfig, audioZone.get("room", "")
                ),
                "cat": get_cat_name_from_cat_uuid(loxconfig, audioZone.get("cat", "")),
            }
        )
        entites.append(LoxoneAudioZoneV2(**audioZone))

    async_add_entities(entites)


def play_state_to_media_player_state(play_state: int) -> MediaPlayerState:
    match play_state:
        case 0:
            return MediaPlayerState.IDLE
        case 1:
            return MediaPlayerState.PAUSED
        case 2:
            return MediaPlayerState.PLAYING
        case -1:
            return MediaPlayerState.OFF
        case _:
            _LOGGER.warning(f"Unknown playState:{play_state}")


class LoxoneAudioZoneV2(LoxoneEntity, MediaPlayerEntity):
    """Representation of a AudioZoneV2 Loxone device."""

    def __init__(self, **kwargs):
        _LOGGER.debug(f"Input AudioZoneV2: {kwargs}")
        LoxoneEntity.__init__(self, **kwargs)
        self.hass = kwargs["hass"]

        self._attr_device_class = MediaPlayerDeviceClass.SPEAKER
        self._state = play_state_to_media_player_state(DEFAULT_AUDIO_ZONE_V2_PLAY_STATE)
        self._volume = 0

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self.unique_id)},
            name=f"{DOMAIN} {self.name}",
            manufacturer="Loxone",
            suggested_area=self.room,
            model=self.typ,
        )

    async def event_handler(self, event):
        should_update = False

        if self.states["volume"] in event.data:
            self._volume = float(event.data[self.states["volume"]]) / 100
            should_update = True

        if self.states["playState"] in event.data:
            self._state = play_state_to_media_player_state(
                event.data[self.states["playState"]]
            )
            should_update = True

        if should_update:
            self.async_schedule_update_ha_state()

    # properties
    @property
    def state(self) -> MediaPlayerState:
        """Return the playback state."""
        return self._state

    @property
    def volume_level(self) -> float | None:
        """Volume level of the media player (0..1)."""
        return self._volume

    @property
    def supported_features(self) -> MediaPlayerEntityFeature:
        """Flag media player features that are supported."""
        return SUPPORT_LOXONE_AUDIO_ZONE

    # commands
    async def async_media_play(self) -> None:
        """Send play command to device."""
        self.hass.bus.async_fire(SENDDOMAIN, dict(uuid=self.uuidAction, value="play"))
        self.async_schedule_update_ha_state()

    async def async_media_pause(self) -> None:
        """Send pause command to device."""
        self.hass.bus.async_fire(SENDDOMAIN, dict(uuid=self.uuidAction, value="pause"))
        self.async_schedule_update_ha_state()

    async def async_media_stop(self) -> None:
        """Send stop command to device."""
        self.hass.bus.async_fire(SENDDOMAIN, dict(uuid=self.uuidAction, value="pause"))
        self.async_schedule_update_ha_state()

    async def async_media_next_track(self) -> None:
        """Send next track command to device."""
        self.hass.bus.async_fire(SENDDOMAIN, dict(uuid=self.uuidAction, value="next"))
        self.async_schedule_update_ha_state()

    async def async_media_previous_track(self) -> None:
        """Send previous track command to device."""
        self.hass.bus.async_fire(SENDDOMAIN, dict(uuid=self.uuidAction, value="prev"))
        self.async_schedule_update_ha_state()

    async def async_set_volume_level(self, volume: float) -> None:
        """Send new volume_level to device."""
        volume_int = int(volume * 100)
        self.hass.bus.async_fire(
            SENDDOMAIN, dict(uuid=self.uuidAction, value=f"volume/{volume_int}")
        )
        self.async_schedule_update_ha_state()

    async def async_volume_up(self) -> None:
        """Send volume UP to device."""
        self.hass.bus.async_fire(SENDDOMAIN, dict(uuid=self.uuidAction, value="volUp"))
        self.async_schedule_update_ha_state()

    async def async_volume_down(self) -> None:
        """Send volume DOWN to device."""
        self.hass.bus.async_fire(
            SENDDOMAIN, dict(uuid=self.uuidAction, value="volDown")
        )
        self.async_schedule_update_ha_state()
