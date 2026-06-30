"""
Loxone Selects

For more details about this component, please refer to the documentation at
https://github.com/JoDehli/PyLoxone
"""

import logging

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from . import LoxoneEntity
from .const import SENDDOMAIN
from .helpers import add_room_and_cat_to_value_values, get_all, get_or_create_device
from .miniserver import get_miniserver_from_hass

_LOGGER = logging.getLogger(__name__)

# Loxone Radio output value representing the "all off" state.
ALL_OFF_VALUE = 0
# Fallback label used when a Radio block enables the "all off" entry but does
# not provide a custom name for it.
ALL_OFF_DEFAULT_LABEL = "All off"


def _dedupe_label(label: str, used: set[str]) -> str:
    """Return a label that is unique within ``used`` and register it.

    Home Assistant requires the options of a select entity to be unique. Loxone
    does not enforce unique output names, so duplicates are disambiguated with a
    numeric suffix (e.g. ``Stand 1 (2)``).
    """
    candidate = label
    index = 2
    while candidate in used:
        candidate = f"{label} ({index})"
        index += 1
    used.add(candidate)
    return candidate


def build_option_maps(
    details: dict,
) -> tuple[list[str], dict[int, str], dict[str, int]]:
    """Build the option list and lookup maps for a Loxone Radio block.

    Returns a tuple of:
      * the ordered list of option labels,
      * a mapping of Loxone output number to option label,
      * a mapping of option label to Loxone output number.

    The "all off" entry (output number ``0``) is only included when the Radio
    block exposes the ``allOff`` detail.
    """
    outputs = details.get("outputs", {}) or {}
    used: set[str] = set()
    options: list[str] = []
    num_to_opt: dict[int, str] = {}
    opt_to_num: dict[str, int] = {}

    if "allOff" in details:
        label = details.get("allOff") or ALL_OFF_DEFAULT_LABEL
        label = _dedupe_label(label, used)
        options.append(label)
        num_to_opt[ALL_OFF_VALUE] = label
        opt_to_num[label] = ALL_OFF_VALUE

    for key in sorted(outputs.keys(), key=lambda k: int(k)):
        number = int(key)
        label = _dedupe_label(str(outputs[key]), used)
        options.append(label)
        num_to_opt[number] = label
        opt_to_num[label] = number

    return options, num_to_opt, opt_to_num


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up Loxone Select."""
    return True


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up entry."""
    miniserver = get_miniserver_from_hass(hass)
    loxconfig = miniserver.lox_config.json
    entities = []

    for select_entity in get_all(loxconfig, ["Radio"]):
        select_entity = add_room_and_cat_to_value_values(loxconfig, select_entity)
        new_select = LoxoneSelect(**select_entity)
        entities.append(new_select)

    async_add_entities(entities)


class LoxoneSelect(LoxoneEntity, SelectEntity):
    """Representation of a Loxone Radio block as a select entity."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        """Initialize the Loxone select."""
        self._icon = None
        self._locked = None

        (
            self._options,
            self._num_to_option,
            self._option_to_num,
        ) = build_option_maps(self.details)
        self._attr_current_option = None

        self.type = "Radio"
        self._attr_device_info = get_or_create_device(self.unique_id, self.name, self.type, self.room)

    @property
    def should_poll(self):
        """No polling needed for a Loxone select."""
        return False

    @property
    def icon(self):
        """Return the icon to use for device if any."""
        return self._icon

    @property
    def options(self) -> list[str]:
        """Return the list of available options."""
        return self._options

    @property
    def current_option(self) -> str | None:
        """Return the currently selected option."""
        return self._attr_current_option

    async def event_handler(self, e):
        if self.states["activeOutput"] in e.data:
            value = e.data[self.states["activeOutput"]]
            try:
                number = int(float(value))
            except (TypeError, ValueError):
                number = None
            self._attr_current_option = self._num_to_option.get(number)
            self.async_schedule_update_ha_state()

        if "jLocked" in self.states and self.states["jLocked"] in e.data:
            self._locked = bool(e.data[self.states["jLocked"]])
            self.async_schedule_update_ha_state()

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        number = self._option_to_num.get(option)
        if number is None:
            _LOGGER.warning("Unknown option '%s' for Loxone select %s", option, self.name)
            return
        self.hass.bus.async_fire(SENDDOMAIN, dict(uuid=self.uuidAction, value=str(number)))
        self.async_schedule_update_ha_state()

    @property
    def extra_state_attributes(self):
        """Return device specific state attributes."""
        return {
            **self._attr_extra_state_attributes,
            "state_uuid": self.states["activeOutput"],
            "device_type": self.type,
            "platform": "loxone",
            "locked": self._locked,
        }
