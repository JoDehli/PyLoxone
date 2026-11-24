"""AlarmClock (structure file spec V17).

States used: ``isEnabled``, ``isAlarmActive``, ``confirmationNeeded``,
``entryList`` (JSON object of entries), ``currentEntry``, ``nextEntry``,
``nextEntryTime`` (seconds since 2009), ``ringingTime``, ``snoozeTime``,
``ringDuration``, ``prepareDuration``, ``snoozeDuration`` and
``wakeAlarmSoundSettings`` (JSON: sound, volume, isSloping).

Commands used: ``snooze``, ``dismiss``, ``setRingDuration/{s}``,
``setPrepDuration/{s}``, ``setSnoozeDuration/{s}`` (minimum 60),
``entryList/put/{id}/{name}/{alarmTime}/{isActive}/{modes|daily}``,
``setWakeAlarmSound/{id}``, ``setWakeAlarmVolume/{n}``,
``setWakeAlarmSlopingOn/{0|1}``.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from homeassistant.components.number import NumberEntity
from homeassistant.components.select import SelectEntity
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.components.switch import SwitchEntity
from homeassistant.const import PERCENTAGE, Platform, UnitOfTime
from homeassistant.core import callback

from ..const import EVENT
from . import SetupContext, register
from .base import (
    ControlBinarySensor,
    ControlButton,
    ControlEntity,
    ControlNumber,
    ControlStateSensor,
    EntityCategory,
    NumberMode,
    StateSpec,
    from_loxone_time,
    parse_json,
    seconds_of_day,
    state_entities,
    to_int,
)


def _entries(raw: Any) -> dict[str, dict]:
    entries = parse_json(raw, {})
    if not isinstance(entries, dict):
        return {}
    return {str(key): value for key, value in entries.items() if isinstance(value, dict)}


def put_command(entry_id: str, entry: dict, *, active: bool) -> str:
    """``entryList/put`` re-sending the entry with a new ``isActive``.

    Entries with the ``nightLight`` property carry ``daily`` (0 / 1),
    all others the list of operating modes.
    """
    name = quote(str(entry.get("name", "")), safe="")
    alarm_time = to_int(entry.get("alarmTime")) or 0
    if "nightLight" in entry and entry.get("nightLight"):
        last = "1" if entry.get("daily") else "0"
    else:
        last = ",".join(str(mode) for mode in entry.get("modes") or [])
    return f"entryList/put/{entry_id}/{name}/{alarm_time}/{1 if active else 0}/{last}"


class NextAlarmSensor(ControlEntity, SensorEntity):
    """Date of the next alarm with the entry's name."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:alarm"

    def __init__(self, control: dict) -> None:
        super().__init__(control, watch=("nextEntryTime", "nextEntry", "entryList", "currentEntry"))
        self._attr_native_value = None
        self._entries: dict[str, dict] = {}
        self._next: int | None = None
        self._current: int | None = None

    def _handle_states(self, changes: dict[str, Any]) -> None:
        if "nextEntryTime" in changes:
            self._attr_native_value = from_loxone_time(changes["nextEntryTime"])
        if "entryList" in changes:
            self._entries = _entries(changes["entryList"])
        if "nextEntry" in changes:
            self._next = to_int(changes["nextEntry"])
        if "currentEntry" in changes:
            self._current = to_int(changes["currentEntry"])

    def _name(self, entry_id: int | None) -> str | None:
        if entry_id is None or entry_id < 0:
            return None
        return self._entries.get(str(entry_id), {}).get("name")

    def _extra_attributes(self) -> dict[str, Any]:
        return {"next_entry": self._name(self._next), "current_entry": self._name(self._current)}


class AlarmEntrySwitch(ControlEntity, SwitchEntity):
    """Activates / deactivates one alarm entry."""

    _attr_icon = "mdi:alarm-check"

    def __init__(self, control: dict, entry_id: str, entry: dict) -> None:
        self.entry_id = entry_id
        super().__init__(
            control, key=f"entry-{entry_id}", suffix=entry.get("name") or f"Alarm {entry_id}", watch=("entryList",)
        )
        self._entry: dict = {}
        self._update(entry)

    def _update(self, entry: dict) -> None:
        self._entry = entry
        self._attr_is_on = bool(entry.get("isActive"))

    def _handle_states(self, changes: dict[str, Any]) -> None:
        entry = _entries(changes["entryList"]).get(self.entry_id)
        if entry is None:
            self._attr_available = False
        else:
            self._attr_available = True
            self._update(entry)

    async def async_turn_on(self, **kwargs: Any) -> None:
        self.send(put_command(self.entry_id, self._entry, active=True))

    async def async_turn_off(self, **kwargs: Any) -> None:
        self.send(put_command(self.entry_id, self._entry, active=False))

    def _extra_attributes(self) -> dict[str, Any]:
        entry = self._entry
        return {
            "alarm_time": seconds_of_day(entry.get("alarmTime")),
            "modes": entry.get("modes"),
            "night_light": entry.get("nightLight"),
            "daily": entry.get("daily"),
        }


class _WakeSoundEntity(ControlEntity):
    """Base for the entities of ``wakeAlarmSoundSettings``."""

    def __init__(self, control: dict, key: str, suffix: str, icon: str) -> None:
        super().__init__(control, key=key, suffix=suffix, watch=("wakeAlarmSoundSettings",), icon=icon)
        self._settings: dict = {}

    def _handle_states(self, changes: dict[str, Any]) -> None:
        settings = parse_json(changes["wakeAlarmSoundSettings"], {})
        self._settings = settings if isinstance(settings, dict) else {}
        self._apply()

    def _apply(self) -> None:
        raise NotImplementedError


class WakeSoundSelect(_WakeSoundEntity, SelectEntity):
    def __init__(self, control: dict, sounds: list[dict]) -> None:
        super().__init__(control, "wake-sound", "Wake Sound", "mdi:music-note")
        self._by_id = {str(s.get("id")): str(s.get("name")) for s in sounds}
        self._by_name = {name: _id for _id, name in self._by_id.items()}
        self._attr_options = list(self._by_id.values())
        self._attr_current_option = None

    def _apply(self) -> None:
        sound = self._settings.get("sound")
        self._attr_current_option = self._by_id.get(str(sound)) if sound is not None else None

    async def async_select_option(self, option: str) -> None:
        self.send(f"setWakeAlarmSound/{self._by_name[option]}")


class WakeVolumeNumber(_WakeSoundEntity, NumberEntity):
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_mode = NumberMode.SLIDER

    def __init__(self, control: dict) -> None:
        super().__init__(control, "wake-volume", "Wake Volume", "mdi:volume-high")
        self._attr_native_value = None

    def _apply(self) -> None:
        self._attr_native_value = self._settings.get("volume")

    async def async_set_native_value(self, value: float) -> None:
        self.send(f"setWakeAlarmVolume/{int(value)}")


class WakeSlopingSwitch(_WakeSoundEntity, SwitchEntity):
    def __init__(self, control: dict) -> None:
        super().__init__(control, "wake-sloping", "Wake Volume Rising", "mdi:volume-plus")
        self._attr_is_on = None

    def _apply(self) -> None:
        sloping = self._settings.get("isSloping")
        self._attr_is_on = None if sloping is None else bool(sloping)

    async def async_turn_on(self, **kwargs: Any) -> None:
        self.send("setWakeAlarmSlopingOn/1")

    async def async_turn_off(self, **kwargs: Any) -> None:
        self.send("setWakeAlarmSlopingOn/0")


def _has(control: dict, name: str) -> bool:
    return bool((control.get("states") or {}).get(name))


@register(Platform.SENSOR, "AlarmClock")
def _sensors(_ctx: SetupContext, control: dict) -> list:
    seconds = {"unit": UnitOfTime.SECONDS, "device_class": SensorDeviceClass.DURATION}
    specs = (
        StateSpec(key="ringingTime", suffix="Ringing Remaining", icon="mdi:alarm-bell", **seconds),
        StateSpec(key="snoozeTime", suffix="Snooze Remaining", icon="mdi:alarm-snooze", **seconds),
    )
    entities: list = [NextAlarmSensor(control)] if _has(control, "nextEntryTime") else []
    return entities + state_entities(control, specs, ControlStateSensor)


@register(Platform.BINARY_SENSOR, "AlarmClock")
def _binary_sensors(_ctx: SetupContext, control: dict) -> list:
    specs = (
        StateSpec(key="isEnabled", suffix="Enabled", icon="mdi:alarm-check"),
        StateSpec(key="isAlarmActive", suffix="Ringing", icon="mdi:alarm-bell"),
        StateSpec(key="confirmationNeeded", suffix="Confirmation Needed", icon="mdi:alarm-light"),
    )
    return state_entities(control, specs, ControlBinarySensor)


@register(Platform.BUTTON, "AlarmClock")
def _buttons(_ctx: SetupContext, control: dict) -> list:
    return [
        ControlButton(control, "snooze", "Snooze", icon="mdi:alarm-snooze"),
        ControlButton(control, "dismiss", "Dismiss", icon="mdi:alarm-off"),
    ]


@register(Platform.NUMBER, "AlarmClock")
def _numbers(_ctx: SetupContext, control: dict) -> list:
    durations = (
        ("ringDuration", "Ring Duration", "setRingDuration/{value}", 0),
        ("prepareDuration", "Prepare Duration", "setPrepDuration/{value}", 0),
        ("snoozeDuration", "Snooze Duration", "setSnoozeDuration/{value}", 60),
    )
    entities: list = [
        ControlNumber(
            control,
            key=state,
            suffix=suffix,
            command=command,
            state=state,
            minimum=minimum,
            maximum=3600,
            step=1,
            unit=UnitOfTime.SECONDS,
            mode=NumberMode.BOX,
            entity_category=EntityCategory.CONFIG,
        )
        for state, suffix, command, minimum in durations
        if _has(control, state)
    ]
    if _has(control, "wakeAlarmSoundSettings"):
        entities.append(WakeVolumeNumber(control))
    return entities


@register(Platform.SELECT, "AlarmClock")
def _selects(_ctx: SetupContext, control: dict) -> list:
    sounds = [s for s in (control.get("details") or {}).get("wakeAlarmSounds") or [] if isinstance(s, dict)]
    if not sounds or not _has(control, "wakeAlarmSoundSettings"):
        return []
    return [WakeSoundSelect(control, sounds)]


@register(Platform.SWITCH, "AlarmClock")
def _switches(ctx: SetupContext, control: dict) -> list:
    entities: list = [WakeSlopingSwitch(control)] if _has(control, "wakeAlarmSoundSettings") else []
    entry_uuid = (control.get("states") or {}).get("entryList")
    if not entry_uuid:
        return entities
    known: set[str] = set()

    # Entries are only known from the entryList state: add them as they appear.
    @callback
    def _discover(event) -> None:
        if entry_uuid not in event.data:
            return
        new = [
            AlarmEntrySwitch(control, entry_id, entry)
            for entry_id, entry in _entries(event.data[entry_uuid]).items()
            if entry_id not in known
        ]
        if new:
            known.update(entity.entry_id for entity in new)
            ctx.async_add_entities(new)

    ctx.config_entry.async_on_unload(ctx.hass.bus.async_listen(EVENT, _discover))
    return entities
