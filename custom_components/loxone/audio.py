"""Existing entry lifecycle adapter for the portable native metadata owner."""
from __future__ import annotations

from typing import TYPE_CHECKING
from pyloxone_audio.metadata import AudioMetadataCoordinator as NativeMetadataCoordinator

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant


class AudioMetadataCoordinator(NativeMetadataCoordinator):
    """Keep HA scheduling in the existing config entry; library owns cleanup."""

    def async_start(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Use HA's existing background-task ownership without another setup."""
        super().async_start(lambda coroutine: entry.async_create_background_task(
            hass, coroutine, name=f"loxone audio metadata {entry.entry_id}"
        ))
