import logging
from collections import OrderedDict
from functools import cached_property

from homeassistant.components.light import (ATTR_BRIGHTNESS, ATTR_EFFECT,
                                            ColorMode, LightEntity,
                                            LightEntityFeature)
from homeassistant.const import STATE_UNKNOWN
from homeassistant.helpers.entity import DeviceInfo

from .. import LoxoneEntity
from ..const import DOMAIN, SENDDOMAIN
from ..helpers import (get_or_create_device, hass_to_lox, lox2hass_mapped,
                       lox_to_hass, parse_lox_json)

_LOGGER = logging.getLogger(__name__)

# Mood ids that mean "off": 0 is spec-defined, 778 is the static "Aus" mood
# on the installation this was observed on. Not in the structure file.
OFF_MOOD_IDS = (0, 778)

# Per-circuit subcontrol states that carry the circuit state in manual
# mode ("Stimmung Manuell"): a plain Switch circuit reports "active",
# Dimmer/EIBDimmer circuits report "position" (0-100).
CIRCUIT_STATE_KINDS = ("active", "position")


class LoxoneLightControllerV2(LoxoneEntity, LightEntity):
    """Representation of a Light Controller V2."""

    _attr_supported_features = LightEntityFeature.EFFECT
    _attr_color_mode = ColorMode.ONOFF
    _attr_supported_color_modes = {ColorMode.ONOFF}
    _attr_is_on: bool | None = None
    _attr_state: None = None
    _attr_available = False

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._attr_state = STATE_UNKNOWN
        self._attr_is_on = STATE_UNKNOWN
        self._active_moods = []
        self._moodlist = []
        self._additional_moodlist = []
        self._attr_brightness = None
        self._master_value = None
        self._master_value_uuid = None
        self._master_position_uuid = None
        self._master_min_uuid = None
        self._master_max_uuid = None
        self._master_min = STATE_UNKNOWN
        self._master_max = STATE_UNKNOWN
        self._master_position_loxone = None
        # state uuid -> "active"/"position" for every per-circuit
        # subcontrol (the master value is handled separately), plus the
        # last value seen for each. These decide is_on in manual mode
        # for controllers without a master (#536).
        self._circuit_state_uuids = {}
        self._circuit_states = {}

        self._async_add_devices = kwargs["async_add_devices"]

        self.kwargs = kwargs
        self._uuid_dict = {}

        self._sub_controls = OrderedDict({})
        for uuid, control in kwargs.get("subControls", {}).items():
            self._sub_controls[uuid] = {
                "name": control["name"],
                "type": control["type"],
            }
            if "masterValue" in uuid and control.get("type") in ["Dimmer", "EIBDimmer"]:
                self._master_value = control
            elif "masterValue" not in uuid:
                for kind in CIRCUIT_STATE_KINDS:
                    state_uuid = (control.get("states") or {}).get(kind)
                    if state_uuid:
                        self._circuit_state_uuids[state_uuid] = kind

        if self._master_value:
            self._master_value_uuid = self._master_value.get("uuidAction")
            self._master_position_uuid = self._master_value.get("states", {}).get(
                "position"
            )
            self._master_min_uuid = self._master_value.get("states", {}).get("min")
            self._master_max_uuid = self._master_value.get("states", {}).get("max")
            self._attr_color_mode = ColorMode.BRIGHTNESS
            self._attr_supported_color_modes = {ColorMode.BRIGHTNESS}

        self.type = "LightControllerV2"
        self._attr_device_info = get_or_create_device(
            self.unique_id, self.name, self.type, self.room
        )

    @property
    def device_class(self):
        """Return the class of this device, from component DEVICE_CLASSES."""
        return self.type

    @property
    def mood_list_uuid(self):
        return self.states.get("moodList")

    def get_moodname_by_id(self, _id):
        for mood in self._moodlist:
            if "id" in mood and "name" in mood:
                if mood["id"] == _id:
                    return mood["name"]
        return _id

    def get_id_by_moodname(self, _name):
        for mood in self._moodlist:
            if "id" in mood and "name" in mood:
                if mood["name"] == _name:
                    return mood["id"]
        return _name

    @property
    def effect_list(self):
        """Return the moods of light controller."""
        moods = []
        for mood in self._moodlist:
            if "name" in mood:
                moods.append(mood["name"])
        return moods

    @property
    def effect(self):
        """Return the current effect."""
        if len(self._active_moods) == 1:
            return self.get_moodname_by_id(self._active_moods[0])
        return None

    async def got_effect(self, **kwargs):
        effects = kwargs["effect"].split(",")
        if len(effects) == 1:
            mood_id = self.get_id_by_moodname(kwargs["effect"])
            if mood_id != kwargs["effect"]:
                self.hass.bus.async_fire(
                    SENDDOMAIN,
                    dict(uuid=self.uuidAction, value="changeTo/{}".format(mood_id)),
                )
            else:
                self.hass.bus.async_fire(
                    SENDDOMAIN, dict(uuid=self.uuidAction, value="plus")
                )
        else:
            effect_ids = []
            for _ in effects:
                mood_id = self.get_id_by_moodname(_.strip())
                if mood_id != _:
                    effect_ids.append(mood_id)

            self.hass.bus.async_fire(
                SENDDOMAIN,
                dict(uuid=self.uuidAction, value="changeTo/{}".format(effect_ids[0])),
            )

            for _ in effect_ids[1:]:
                self.hass.bus.async_fire(
                    SENDDOMAIN,
                    dict(uuid=self.uuidAction, value="addMood/{}".format(_)),
                )

    async def async_turn_on(self, **kwargs) -> None:
        if ATTR_EFFECT in kwargs:
            await self.got_effect(**kwargs)
        elif ATTR_BRIGHTNESS in kwargs and self._master_value_uuid:
            self.hass.bus.async_fire(
                SENDDOMAIN,
                dict(
                    uuid=self._master_value_uuid,
                    value=round(hass_to_lox(kwargs[ATTR_BRIGHTNESS])),
                ),
            )
        elif kwargs == {}:
            if self._attr_is_on is not True:
                # Plain turn-on activates the first mood that is not an off
                # mood; without any such mood, plus (spec: next mood).
                first_mood_id = next(
                    (
                        mood["id"]
                        for mood in self._moodlist
                        if isinstance(mood, dict)
                        and "id" in mood
                        and mood["id"] not in OFF_MOOD_IDS
                    ),
                    None,
                )
                if first_mood_id is not None:
                    self.hass.bus.async_fire(
                        SENDDOMAIN,
                        dict(
                            uuid=self.uuidAction,
                            value="changeTo/{}".format(first_mood_id),
                        ),
                    )
                else:
                    self.hass.bus.async_fire(
                        SENDDOMAIN, dict(uuid=self.uuidAction, value="plus")
                    )
            else:
                # Already on: no command - a plain turn-on must not steal
                # the running mood or brightness.
                _LOGGER.debug(
                    "Light %s is already on; ignoring plain turn_on", self.name
                )
        self.async_schedule_update_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        self.hass.bus.async_fire(
            SENDDOMAIN, dict(uuid=self.uuidAction, value="changeTo/0")
        )
        self.async_schedule_update_ha_state()

    def _parse_json_state(self, state: str, data: dict):
        """Parse a JSON mood state; log and return None if it is invalid."""
        try:
            return parse_lox_json(data[self.states[state]])
        except (TypeError, ValueError):
            _LOGGER.warning(
                "Ignoring invalid %s of %s: %r", state, self.name, data[self.states[state]]
            )
            return None

    def _update_is_on(self) -> None:
        """Derive is_on from the mood state, the circuits and the master value.

        Spec: mood id 0 is always off. Observed on this installation: 778
        is the static "Aus" mood. An empty activeMoods list is NOT off -
        it is the manual mood ("Stimmung Manuell"), also entered when a
        push button wired to the controller's input switches a circuit
        (JoDehli/PyLoxone#536).
        """
        if any(mood_id not in OFF_MOOD_IDS for mood_id in self._active_moods):
            self._attr_is_on = True
        elif self._active_moods:
            self._attr_is_on = False
        else:
            self._attr_is_on = self._manual_mode_is_on()

    def _manual_mode_is_on(self) -> bool:
        """Return is_on for the manual mood (empty activeMoods).

        The circuits keep their state in manual mode - only the mood list
        is cleared. As soon as a per-circuit subcontrol state has been
        seen (Switch "active", Dimmer "position" - #536), those decide.
        A controller moved directly over the master reports the master
        value instead. Without a master dimmer and without any circuit
        state, <= 0.9.24 reported on, which is the historically correct
        fallback (manual mood means the circuits were touched).
        """
        if self._circuit_states:
            return self._any_circuit_on()
        if self._master_position_uuid:
            return (self._master_position_loxone or 0) > 0
        return True

    def _any_circuit_on(self) -> bool:
        """Return True if any tracked circuit state is lit."""
        for state_uuid, value in self._circuit_states.items():
            kind = self._circuit_state_uuids.get(state_uuid, "active")
            if kind == "position":
                try:
                    if float(value) > 0:
                        return True
                except (TypeError, ValueError):
                    continue
            elif value:
                return True
        return False

    async def event_handler(self, event):
        request_update = False

        if self.uuidAction in event.data:
            self._attr_state = event.data[self.uuidAction]
            request_update = True

        if self._master_min_uuid and self._master_min_uuid in event.data:
            self._master_min = event.data[self._master_min_uuid]
            request_update = True

        if self._master_max_uuid and self._master_max_uuid in event.data:
            self._master_max = event.data[self._master_max_uuid]
            request_update = True

        if self._master_position_uuid and self._master_position_uuid in event.data:
            self._master_position_loxone = event.data[self._master_position_uuid]
            if (
                self._master_min is not None
                and self._master_max is not None
                and self._master_min != "unknown"
                and self._master_max != "unknown"
            ):
                self._attr_brightness = lox2hass_mapped(
                    event.data[self._master_position_uuid],
                    self._master_min,
                    self._master_max,
                )
            else:
                self._attr_brightness = lox_to_hass(
                    event.data[self._master_position_uuid]
                )
            request_update = True

        # Per-circuit subcontrol states (Switch "active", Dimmer
        # "position") - they decide is_on in manual mode (#536). The
        # Miniserver updates are enabled globally
        # (jdev/sps/enablebinstatusupdate), so these state uuids arrive
        # on the bus like the master position does.
        for state_uuid in self._circuit_state_uuids:
            if state_uuid in event.data:
                self._circuit_states[state_uuid] = event.data[state_uuid]
                request_update = True

        # The mood states are JSON (spec: Structure File, LightControllerV2).
        # They used to be ``eval``'d, which ran Miniserver data as Python
        # code, and the "true"->"True" rewrite also renamed moods whose
        # name contains "true" / "false".
        active_moods_uuid = self.states.get("activeMoods")
        if active_moods_uuid and active_moods_uuid in event.data:
            active_moods = self._parse_json_state("activeMoods", event.data)
            if active_moods is not None:
                self._active_moods = active_moods
                request_update = True

        moodlist_uuid = self.states.get("moodList")
        if moodlist_uuid and moodlist_uuid in event.data:
            moodlist = self._parse_json_state("moodList", event.data)
            if moodlist is not None:
                self._moodlist = moodlist
                request_update = True

        additional_uuid = self.states.get("additionalMoods")
        if additional_uuid and additional_uuid in event.data:
            additional = self._parse_json_state("additionalMoods", event.data)
            if additional is not None:
                self._additional_moodlist = additional
                request_update = True

        if self.uuidAction in event.data:
            # The spec lists no simple value state for this block - the
            # light state lives in the JSON mood states. Unexpected event
            # for the own uuid; keep it observable but do not write it
            # into _attr_state (verify empirically).
            _LOGGER.debug(
                "LightControllerV2 %s: unexpected own-uuid event %r",
                self.name,
                event.data[self.uuidAction],
            )

        if request_update:
            self._update_is_on()
            if not self._attr_available:
                attr_is_on_is_not_unknown = self._attr_is_on == True or self._attr_is_on == False
                both_master_values_are_not_unknown = self._master_min != STATE_UNKNOWN and self._master_max != STATE_UNKNOWN
                if attr_is_on_is_not_unknown or both_master_values_are_not_unknown:
                    self._attr_available = True
            self.async_schedule_update_ha_state()


    @property
    def extra_state_attributes(self):
        """Return device specific state attributes.

        Implemented by platform classes.
        """
        return {
            **self._attr_extra_state_attributes,
            "selected_scene": self.effect,
            "selected_scenes": [
                self.get_moodname_by_id(id) for id in self._active_moods
            ],
            "device_type": self.type,
            "subcontrols": self._sub_controls,
        }

    @cached_property
    def icon(self):
        """Return the sensor icon."""
        return "mdi:hubspot"
