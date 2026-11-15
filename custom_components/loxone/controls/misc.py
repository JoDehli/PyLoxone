"""Sequential, StatusMonitor, MailBox, UpDownLeftRight (structure file spec V17).

* Sequential: ``details.sequences`` (id, name), ``activeSequence``;
  ``triggerSequence/{id}`` (0 stops the active sequence)
* StatusMonitor: ``details.inputs`` / ``details.status``, ``numState0`` ..
  ``numState9`` / ``numDef`` (inputs per status), ``inputStates``
  (comma-separated status id per input)
* MailBox (Paketsafe): ``packetReceived``, ``mailReceived``,
  ``notificationsDisabledInput``, ``disableEndTime`` (UTC seconds since
  2009); ``confirmPacket``, ``confirmMail``, ``disableNotifications/{s}``
* UpDownLeftRight digital: ``PulseUp`` / ``PulseDown`` (and On / Off)
* UpDownLeftRight analog: ``details.min/max/step/format``, ``value``,
  ``error``; ``{value}``
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.number import NumberEntity
from homeassistant.components.sensor import SensorEntity
from homeassistant.const import Platform, UnitOfTime
from homeassistant.util import dt as dt_util

from . import SetupContext, register
from .base import (
    ControlBinarySensor,
    ControlButton,
    ControlEntity,
    ControlNumber,
    ControlSelect,
    ControlStateSensor,
    NumberMode,
    SensorDeviceClass,
    StateSpec,
    from_loxone_time,
    state_entities,
    to_bool,
    to_float,
    to_int,
    unit_from_format,
)

# --- Sequential --------------------------------------------------------------

SEQUENCE_OFF = "Off"


@register(Platform.SELECT, "Sequential")
def _sequential(_ctx: SetupContext, control: dict) -> list:
    if not (control.get("states") or {}).get("activeSequence"):
        return []
    options: dict[Any, str] = {0: SEQUENCE_OFF}
    for sequence in (control.get("details") or {}).get("sequences") or []:
        if isinstance(sequence, dict) and to_int(sequence.get("id")):
            options[to_int(sequence["id"])] = str(sequence.get("name") or f"Sequence {sequence['id']}")
    return [
        ControlSelect(
            control,
            key=None,
            suffix=None,
            state="activeSequence",
            options=options,
            command="triggerSequence/{id}",
            icon="mdi:playlist-play",
        )
    ]


# --- StatusMonitor -----------------------------------------------------------

STATUS_UNDEFINED = "Undefined"
_UNCONFIGURED = 255


def status_definitions(details: dict) -> dict[int, dict]:
    """Output index (``id``) -> status object of ``details.status``."""
    raw = details.get("status") or {}
    items = raw.values() if isinstance(raw, dict) else raw if isinstance(raw, list) else []
    result = {}
    for item in items:
        if isinstance(item, dict) and to_int(item.get("id")) is not None:
            result[to_int(item["id"])] = item
    return result


def _count_state(status_id: int) -> str:
    # id 10 is the "no matching status" counter.
    return "numDef" if status_id >= 10 else f"numState{status_id}"


class StatusMonitorSensor(ControlEntity, SensorEntity):
    """The highest-priority status any input currently has.

    Priorities start at 0 (most important). Counts per status and the
    status of every input are attributes.
    """

    _attr_icon = "mdi:list-status"

    def __init__(self, control: dict) -> None:
        self.statuses = status_definitions(control.get("details") or {})
        watch = tuple(f"numState{i}" for i in range(10)) + ("numDef", "inputStates")
        super().__init__(control, watch=watch)
        self._attr_native_value = None
        self._counts: dict[str, float | None] = {}
        self._input_states: list[int | None] = []

    def _name(self, status_id: int | None) -> str | None:
        if status_id is None:
            return None
        if status_id == _UNCONFIGURED:
            return "Unconfigured"
        status = self.statuses.get(status_id)
        return str(status.get("name")) if status else STATUS_UNDEFINED

    def _handle_states(self, changes: dict[str, Any]) -> None:
        for key, value in changes.items():
            if key == "inputStates":
                text = value if isinstance(value, str) else ""
                self._input_states = [to_int(part) for part in text.split(",")] if text else []
            else:
                self._counts[key] = to_float(value)
        active = [
            (to_int(status.get("prio")) or 0, status_id)
            for status_id, status in self.statuses.items()
            if self._counts.get(_count_state(status_id))
        ]
        self._attr_native_value = self._name(min(active)[1]) if active else None

    def _extra_attributes(self) -> dict[str, Any]:
        inputs = [i for i in (self.details.get("inputs") or []) if isinstance(i, dict)]
        return {
            "counts": {
                str(status.get("name")): self._counts.get(_count_state(status_id))
                for status_id, status in self.statuses.items()
            },
            "undefined_count": self._counts.get("numDef"),
            "inputs": {
                str(item.get("name")): self._name(self._input_states[index])
                if index < len(self._input_states)
                else None
                for index, item in enumerate(inputs)
            },
        }


@register(Platform.SENSOR, "StatusMonitor")
def _status_monitor(_ctx: SetupContext, control: dict) -> list:
    entities: list = [StatusMonitorSensor(control)]
    for status_id, status in status_definitions(control.get("details") or {}).items():
        key = _count_state(status_id)
        if (control.get("states") or {}).get(key):
            entities.append(
                ControlStateSensor(
                    control,
                    StateSpec(key=key, suffix=str(status.get("name")), convert=to_int, icon="mdi:counter"),
                )
            )
    return entities


# --- MailBox -----------------------------------------------------------------


class MailBoxPauseNotifications(ControlEntity, NumberEntity):
    """Minutes the notifications stay disabled (0 = enabled again)."""

    _attr_native_min_value = 0
    _attr_native_max_value = 10080  # one week
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_mode = NumberMode.BOX
    _attr_icon = "mdi:bell-sleep"

    def __init__(self, control: dict) -> None:
        super().__init__(control, key="disableNotifications", suffix="Pause Notifications", watch=("disableEndTime",))
        self._end = None

    def _handle_states(self, changes: dict[str, Any]) -> None:
        self._end = from_loxone_time(changes["disableEndTime"], utc=True)

    @property
    def native_value(self) -> float | None:
        if self._end is None:
            return 0
        remaining = (self._end - dt_util.utcnow()).total_seconds() / 60
        return max(0, round(remaining))

    async def async_set_native_value(self, value: float) -> None:
        self.send(f"disableNotifications/{int(value) * 60}")


@register(Platform.BINARY_SENSOR, "MailBox")
def _mailbox_binary(_ctx: SetupContext, control: dict) -> list:
    specs = (
        StateSpec(key="packetReceived", suffix="Parcel", icon="mdi:package-variant-closed"),
        StateSpec(key="mailReceived", suffix="Mail", icon="mdi:email"),
        StateSpec(key="notificationsDisabledInput", suffix="Notifications Disabled", icon="mdi:bell-off"),
    )
    return state_entities(control, specs, ControlBinarySensor)


@register(Platform.SENSOR, "MailBox")
def _mailbox_sensors(_ctx: SetupContext, control: dict) -> list:
    spec = StateSpec(
        key="disableEndTime",
        suffix="Notifications Disabled Until",
        convert=lambda value: from_loxone_time(value, utc=True),
        device_class=SensorDeviceClass.TIMESTAMP,
    )
    return state_entities(control, (spec,), ControlStateSensor)


@register(Platform.BUTTON, "MailBox")
def _mailbox_buttons(_ctx: SetupContext, control: dict) -> list:
    return [
        ControlButton(control, "confirmPacket", "Confirm Parcel", icon="mdi:package-variant"),
        ControlButton(control, "confirmMail", "Confirm Mail", icon="mdi:email-check"),
    ]


@register(Platform.NUMBER, "MailBox")
def _mailbox_numbers(_ctx: SetupContext, control: dict) -> list:
    return [MailBoxPauseNotifications(control)] if (control.get("states") or {}).get("disableEndTime") else []


# --- UpDownLeftRight ---------------------------------------------------------

_DIGITAL = ("UpDownDigital", "LeftRightDigital")
_ANALOG = ("UpDownAnalog", "LeftRightAnalog")


@register(Platform.BUTTON, *_DIGITAL)
def _up_down_buttons(_ctx: SetupContext, control: dict) -> list:
    # Up = up / right output, Down = down / left output.
    left_right = control["type"].startswith("LeftRight")
    return [
        ControlButton(
            control,
            "PulseUp",
            "Right" if left_right else "Up",
            icon="mdi:chevron-right" if left_right else "mdi:chevron-up",
        ),
        ControlButton(
            control,
            "PulseDown",
            "Left" if left_right else "Down",
            icon="mdi:chevron-left" if left_right else "mdi:chevron-down",
        ),
    ]


class UpDownAnalogNumber(ControlNumber):
    """Analog virtual input; ``error`` marks an invalid value."""

    def __init__(self, control: dict) -> None:
        details = control.get("details") or {}
        super().__init__(
            control,
            key=None,  # main entity
            suffix=None,
            command="{value}",
            state="value",
            minimum=to_float(details.get("min")) or 0,
            maximum=to_float(details.get("max")) if to_float(details.get("max")) is not None else 100,
            step=to_float(details.get("step")) or 1,
            unit=unit_from_format(details.get("format")),
            mode=NumberMode.BOX,
        )
        error_uuid = (control.get("states") or {}).get("error")
        if error_uuid:
            self._watched[error_uuid] = "error"
        self._error: bool | None = None

    def _handle_states(self, changes: dict[str, Any]) -> None:
        if "value" in changes:
            super()._handle_states(changes)
        if "error" in changes:
            self._error = to_bool(changes["error"])

    def _extra_attributes(self) -> dict[str, Any]:
        return {"invalid_value": self._error}


@register(Platform.NUMBER, *_ANALOG)
def _up_down_analog(_ctx: SetupContext, control: dict) -> list:
    return [UpDownAnalogNumber(control)] if (control.get("states") or {}).get("value") else []
