"""Loxone Alarm controls as alarm control panels."""

import logging

from homeassistant.components.alarm_control_panel import AlarmControlPanelEntity, AlarmControlPanelState
from homeassistant.components.alarm_control_panel.const import AlarmControlPanelEntityFeature, CodeFormat
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType

from . import LoxoneEntity
from .const import SECUREDSENDDOMAIN, SENDDOMAIN
from .helpers import add_room_and_cat_to_value_values, get_all, get_or_create_device
from .miniserver import get_miniserver_from_hass

_LOGGER = logging.getLogger(__name__)


def _state_uuid(states: dict, name: str) -> str | None:
    """Un-guarded ``states[name]`` indexing crashes the alarm platform when a
    structure file omits an attribute; return ``None`` instead."""
    return states.get(name)


def alarm_arm_value(arm_state: AlarmControlPanelState) -> str:
    """Command value that arms an Loxone alarm.

    ``delayedon/0`` ⇒ ARM_HOME, ``delayedon/1`` ⇒ ARM_AWAY.
    """
    if arm_state == AlarmControlPanelState.ARMED_HOME:
        return "delayedon/0"
    if arm_state == AlarmControlPanelState.ARMED_AWAY:
        return "delayedon/1"
    raise ValueError(f"{arm_state} is not an arm state")


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up Loxone Alarms from YAML is not supported (config entries only)."""


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Loxone Alarms."""
    miniserver = get_miniserver_from_hass(hass, config_entry)
    loxconfig = miniserver.lox_config.json
    entities = []
    for loxone_alarm in get_all(loxconfig, "Alarm"):
        loxone_alarm = add_room_and_cat_to_value_values(loxconfig, loxone_alarm)
        new_alarm = LoxoneAlarm(hass=hass, **loxone_alarm)
        entities.append(new_alarm)

    async_add_entities(entities, True)


class LoxoneAlarm(LoxoneEntity, AlarmControlPanelEntity):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._state = 0.0
        self._disabled_move = 0.0
        self._level = 0.0
        self._armed_delay = 0.0
        self._armed_delay_total_delay = 0.0
        self._armed_at = 0
        self._next_level_at = 0
        # Setup-time facts from the structure file: a secured alarm needs a
        # numeric arm/disarm code, an unsecured one needs none. They must not
        # depend on ``code_arm_required`` being read first.
        is_secured = bool(kwargs.get("isSecured"))
        self._attr_code_arm_required = is_secured
        self._attr_code_format = CodeFormat.NUMBER if is_secured else None
        self._attr_device_info = get_or_create_device(
            self.unique_id, self.name, "Alarm", self.room
        )

    @property
    def supported_features(self):
        return AlarmControlPanelEntityFeature.ARM_HOME | AlarmControlPanelEntityFeature.ARM_AWAY

    async def event_handler(self, e):
        request_update = False

        if (u := _state_uuid(self.states, "armed")) and u in e.data:
            self._state = e.data[u]
            request_update = True

        if (u := _state_uuid(self.states, "disabledMove")) and u in e.data:
            self._disabled_move = e.data[u]
            request_update = True

        if (u := _state_uuid(self.states, "armedAt")) and u in e.data:
            self._armed_at = e.data[u]
            request_update = True

        if (u := _state_uuid(self.states, "nextLevelAt")) and u in e.data:
            self._next_level_at = e.data[u]
            request_update = True

        if (u := _state_uuid(self.states, "armedDelay")) and u in e.data:
            self._armed_delay = e.data[u]
            request_update = True

        if (u := _state_uuid(self.states, "armedDelayTotal")) and u in e.data:
            self._armed_delay_total_delay = e.data[u]
            request_update = True

        if (u := _state_uuid(self.states, "level")) and u in e.data:
            self._level = e.data[u]
            request_update = True

        if request_update:
            self.async_schedule_update_ha_state()

    @property
    def armed_at(self):
        return self._armed_at

    @property
    def next_level_at(self):
        return self._next_level_at

    @property
    def armed_delay(self):
        return self._armed_delay

    @property
    def armed_delay_total_delay(self):
        return self._armed_delay_total_delay

    @property
    def disabled_move(self):
        return self._disabled_move

    @property
    def level(self):
        return self._level

    async def async_alarm_disarm(self, code=None):
        """Send disarm command."""
        if self.isSecured:
            self.hass.bus.async_fire(
                SECUREDSENDDOMAIN, dict(uuid=self.uuidAction, value="off", code=code)
            )
        else:
            self.hass.bus.async_fire(
                SENDDOMAIN, dict(uuid=self.uuidAction, value="off")
            )
        self.async_schedule_update_ha_state()

    async def async_alarm_arm_home(self, code=None):
        """Send arm home command."""
        value = alarm_arm_value(AlarmControlPanelState.ARMED_HOME)
        if self.isSecured:
            self.hass.bus.async_fire(
                SECUREDSENDDOMAIN,
                dict(uuid=self.uuidAction, value=value, code=code),
            )
        else:
            self.hass.bus.async_fire(
                SENDDOMAIN, dict(uuid=self.uuidAction, value=value)
            )
        self.async_schedule_update_ha_state()

    async def async_alarm_arm_away(self, code=None):
        """Send arm away command."""
        value = alarm_arm_value(AlarmControlPanelState.ARMED_AWAY)
        if self.isSecured:
            self.hass.bus.async_fire(
                SECUREDSENDDOMAIN,
                dict(uuid=self.uuidAction, value=value, code=code),
            )
        else:
            self.hass.bus.async_fire(
                SENDDOMAIN, dict(uuid=self.uuidAction, value=value)
            )
        self.async_schedule_update_ha_state()

    @property
    def alarm_state(self) -> AlarmControlPanelState | None:
        """Return the state of the device."""
        if self._level >= 1.0:
            return AlarmControlPanelState.TRIGGERED
        if self._armed_delay or self._armed_at:
            return AlarmControlPanelState.ARMING
        if self._state and self._disabled_move:
            return AlarmControlPanelState.ARMED_HOME
        if self._state:
            return AlarmControlPanelState.ARMED_AWAY
        return AlarmControlPanelState.DISARMED

    @property
    def extra_state_attributes(self):
        """Return the state attributes."""
        return {
            **self._attr_extra_state_attributes,
            "device_type": self.type,
            "level": self._level,
            "armed_at": self._armed_at,
            "next_level_at": self._next_level_at,
            "armed_delay": self._armed_delay,
            "armed_delay_total_delay": self._armed_delay_total_delay,
        }
