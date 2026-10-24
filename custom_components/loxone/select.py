"""
Loxone Selects

For more details about this component, please refer to the documentation at
https://github.com/JoDehli/PyLoxone
"""

import logging

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from . import LoxoneEntity
from .const import SENDDOMAIN
from .helpers import (add_room_and_cat_to_value_values, get_all, get_or_create_device,
                      parse_control_lock)
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
) -> tuple[list[str], dict[int, str], dict[str, int], int | None]:
    """Build the option list and lookup maps for a Loxone Radio block.

    Returns a tuple of:
      * the ordered list of option labels,
      * a mapping of Loxone output number to option label,
      * a mapping of option label to Loxone output number,
      * the output number of the "all off" entry, or None if not present.

    The "all off" entry (output number ``0``) is only included when the Radio
    block exposes the ``allOff`` detail.
    """
    outputs = details.get("outputs", {}) or {}
    used: set[str] = set()
    options: list[str] = []
    num_to_opt: dict[int, str] = {}
    opt_to_num: dict[str, int] = {}
    all_off_num = None
    if "allOff" in details:
        label = details.get("allOff") or ALL_OFF_DEFAULT_LABEL
        label = _dedupe_label(label, used)
        options.append(label)
        num_to_opt[ALL_OFF_VALUE] = label
        opt_to_num[label] = ALL_OFF_VALUE
        all_off_num = ALL_OFF_VALUE

    for key in sorted(outputs.keys(), key=lambda k: int(k)):
        number = int(key)
        label = _dedupe_label(str(outputs[key]), used)
        options.append(label)
        num_to_opt[number] = label
        opt_to_num[label] = number

    return options, num_to_opt, opt_to_num, all_off_num


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
    miniserver = get_miniserver_from_hass(hass, config_entry)
    loxconfig = miniserver.lox_config.json
    entities = []

    for select_entity in get_all(loxconfig, ["Radio"]):
        select_entity = add_room_and_cat_to_value_values(loxconfig, select_entity)
        try:
            # PS-19: a Radio without any outputs yields options == [],
            # which Home Assistant rejects - skip it with a log instead of
            # failing the whole platform.
            options, _, _, _ = build_option_maps(select_entity.get("details") or {})
            if not options:
                _LOGGER.warning(
                    "Skipping Radio control %s: it has no outputs, a select needs at least one option",
                    select_entity.get("name", select_entity.get("uuidAction", "?")),
                )
                continue
            entities.append(LoxoneSelect(**select_entity))
        except Exception:
            _LOGGER.exception("Skipping Radio control %s", select_entity.get("name", "?"))

    async_add_entities(entities)


class LoxoneSelect(LoxoneEntity, SelectEntity):
    """Representation of a Loxone Radio block as a select entity."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        """Initialize the Loxone select."""
        self._icon = None
        self._locked = None

        (
            self._attr_options,
            self._num_to_option,
            self._option_to_num,
            self._all_off_num
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

    async def event_handler(self, e):
        request_update = False

        active_uuid = self.states.get("activeOutput")
        if active_uuid and active_uuid in e.data:
            value = e.data[active_uuid]
            try:
                number = int(float(value))
            except (TypeError, ValueError):
                number = None
            self._attr_current_option = self._num_to_option.get(number)
            request_update = True

        if "jLocked" in self.states and self.states["jLocked"] in e.data:
            # The lock state is a JSON text like {"locked": 0, "reason": ...}
            # where 0 means not locked: bool() of the text read every
            # non-empty value as locked.
            self._locked = bool(parse_control_lock(e.data[self.states["jLocked"]])[0])
            request_update = True

        # One write per event: activeOutput and jLocked can arrive together.
        if request_update:
            self.async_schedule_update_ha_state()

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        # PS-19: enforce the Loxone lock; HA renders the raised error to the
        # caller of the select service.
        if self._locked:
            raise HomeAssistantError(
                f"Loxone Radio block {self.name} is locked and ignores selections"
            )
        number = self._option_to_num.get(option)
        if number is None:
            _LOGGER.warning("Unknown option '%s' for Loxone select %s", option, self.name)
            return
        if number == self._all_off_num:
            self.hass.bus.async_fire(SENDDOMAIN, dict(uuid=self.uuidAction, value="reset"))
        else:
            self.hass.bus.async_fire(SENDDOMAIN, dict(uuid=self.uuidAction, value=str(number)))
        self.async_schedule_update_ha_state()

    @property
    def extra_state_attributes(self):
        """Return device specific state attributes."""
        return {
            **self._attr_extra_state_attributes,
            "state_uuid": self.states.get("activeOutput"),
            "device_type": self.type,
            "platform": "loxone",
            "locked": self._locked,
        }
