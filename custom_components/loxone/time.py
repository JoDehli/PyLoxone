"""
Loxone time entities.

Only control types of the ``controls`` package use this platform (e.g. the
start time of a PulseAt block).
"""

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .controls import async_setup_controls
from .miniserver import get_miniserver_from_hass


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Loxone time entities."""
    miniserver = get_miniserver_from_hass(hass, config_entry)
    loxconfig = miniserver.lox_config.json
    async_add_entities(async_setup_controls(Platform.TIME, hass, config_entry, loxconfig, async_add_entities))
