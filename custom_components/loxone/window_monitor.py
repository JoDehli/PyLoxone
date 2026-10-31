"""
Window- and door monitor (``WindowMonitor``, #524).

The Loxone block "Fenster- und Türüberwachung" publishes the state of every
contact it watches as one comma-separated text state, ``windowStates``.  The
position of a value in that string is the position of the contact in
``details.windows`` (structure file v16, p. 157).  Each value is a bitmask:

    0  offline / unknown        4  open
    1  closed                   8  locked
    2  tilted                  16  unlocked

A lockable door reports a single value (``8`` closed and locked, ``16``
closed but unlocked, ``4`` open), so ``8`` and ``16`` without the closed bit
still mean "closed" (reporter-observed sequence ``8 → 16 → 4 → 16 → 8``).

Entities, per contact (deduplicated by the contact's uuid across monitors,
because a central monitor repeats every room monitor's contacts):

* ``binary_sensor`` device class ``window``, on when tilted or open.  It is
  the device's main entity (named after the contact) and carries the full
  state as the ``position`` attribute; its icon follows the state (tilted and
  locked get their own icon).
* ``sensor`` device class ``enum`` with every state a contact can report:
  ``closed`` / ``tilted`` / ``open``, and for contacts with a lock input
  ``locked`` (8) / ``unlocked`` (16, closed but not locked).  A separate lock
  entity is not needed: the structure file does not say which contacts have a
  lock input, and a lockable door simply reports ``locked`` / ``unlocked``
  instead of ``closed``.

Per monitor: the ``num*`` counters as measurement sensors.

Contacts whose uuid is a motorised ``Window`` / ``Gate`` (or a ``Jalousie``)
control are skipped: those controls are already covers with their own
position state.

The contact's uuid can be a real control that is already an entity (an
``InfoOnlyDigital`` contact with "Use" ticked), so every entity here uses a
suffixed unique id: ``<uuid>-window``, ``<uuid>-state``.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.helpers.entity import EntityCategory

from . import LoxoneEntity
from .helpers import get_all, get_or_create_device, get_room_name_from_room_uuid

_LOGGER = logging.getLogger(__name__)

WINDOW_MONITOR_TYPE = "WindowMonitor"

BIT_CLOSED = 1
BIT_TILTED = 2
BIT_OPEN = 4
BIT_LOCKED = 8
BIT_UNLOCKED = 16

POSITION_CLOSED = "closed"
POSITION_TILTED = "tilted"
POSITION_OPEN = "open"

# Full state of a contact (enum sensor options, ``position`` attribute).
# ``locked`` / ``unlocked`` are closed doors with a lock input (8 / 16).
STATE_CLOSED = POSITION_CLOSED
STATE_TILTED = POSITION_TILTED
STATE_OPEN = POSITION_OPEN
STATE_LOCKED = "locked"
STATE_UNLOCKED = "unlocked"
STATE_OPTIONS = [STATE_CLOSED, STATE_TILTED, STATE_OPEN, STATE_LOCKED, STATE_UNLOCKED]

# Binary sensor icons per state.  ``None`` keeps Home Assistant's default for
# the window device class (window-open / window-closed).
STATE_ICONS: dict[str, str] = {
    STATE_TILTED: "mdi:window-open-variant",
    STATE_LOCKED: "mdi:window-closed-variant",
}

# Control types that already become a cover with their own position state.
COVER_CONTROL_TYPES = frozenset({"Jalousie", "Gate", "Window"})

# Per-monitor counters: state key -> (entity name, enabled by default,
# diagnostic).  Open and tilted answer "what is open right now"; the rest
# would add six entities per monitor, so they start disabled.
COUNT_SENSOR_SPECS: dict[str, tuple[str, bool, bool]] = {
    "numOpen": ("Open", True, False),
    "numTilted": ("Tilted", True, False),
    "numClosed": ("Closed", False, False),
    "numLocked": ("Locked", False, False),
    "numUnlocked": ("Unlocked", False, False),
    "numOffline": ("Offline", False, True),
}


# --------------------------------------------------------------------------- #
# Pure decoding
# --------------------------------------------------------------------------- #
def parse_window_states(raw: Any) -> list[int | None] | None:
    """
    Split a ``windowStates`` payload into one value per contact.

    Returns ``None`` when the payload is not usable at all (``None``, a
    bool, a container).  An empty field counts as ``0`` (offline); a field that
    is not a number becomes ``None`` (unknown, but the contact stays available).
    """
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        fields: list[str] = [str(raw)]
    elif isinstance(raw, str):
        if not raw.strip():
            return []
        fields = raw.split(",")
    else:
        return None
    values: list[int | None] = []
    for field in fields:
        text = field.strip()
        if not text:
            values.append(0)
            continue
        try:
            number = int(float(text))
        except (TypeError, ValueError, OverflowError):
            values.append(None)
            continue
        values.append(number if number >= 0 else None)
    return values


def window_position(value: int | None) -> str | None:
    """``closed`` / ``tilted`` / ``open`` for one contact value, or ``None``."""
    if not value:
        return None
    if value & BIT_OPEN:
        return POSITION_OPEN
    if value & BIT_TILTED:
        return POSITION_TILTED
    if value & (BIT_CLOSED | BIT_LOCKED | BIT_UNLOCKED):
        # 8 / 16 without the closed bit are "closed and (un)locked".
        return POSITION_CLOSED
    return None


def window_state(value: int | None) -> str | None:
    """
    Full state of one contact value, or ``None``.

    ``open`` / ``tilted`` win over the lock bits (an open door cannot be
    locked).  A closed contact with a lock input reports ``locked`` (8) or
    ``unlocked`` (16); one without a lock input reports ``closed`` (1).
    """
    position = window_position(value)
    if position != POSITION_CLOSED:
        return position
    if value & BIT_LOCKED:
        return STATE_LOCKED
    if value & BIT_UNLOCKED:
        return STATE_UNLOCKED
    return STATE_CLOSED


# --------------------------------------------------------------------------- #
# Structure file -> contacts
# --------------------------------------------------------------------------- #
class WindowStatesFeed:
    """
    One monitor's ``windowStates`` stream.

    Shared by the contacts of that monitor so a length mismatch between
    ``details.windows`` and the pushed values is logged once, not once per
    contact per update.
    """

    def __init__(self, monitor_name: str, states_uuid: str, window_count: int) -> None:
        self.monitor_name = monitor_name
        self.states_uuid = states_uuid
        self.window_count = window_count
        self._mismatch_logged = False

    def values(self, raw: Any) -> list[int | None] | None:
        values = parse_window_states(raw)
        if values is not None and len(values) != self.window_count and not self._mismatch_logged:
            self._mismatch_logged = True
            _LOGGER.debug(
                "WindowMonitor %s: %d windows in the structure file but %d values in windowStates %r; "
                "contacts without a value are unavailable, extra values are ignored",
                self.monitor_name,
                self.window_count,
                len(values),
                raw,
            )
        return values


@dataclass
class WindowContact:
    """One monitored contact, as the entities of all platforms see it."""

    uuid: str
    name: str
    room: str
    install_place: str
    index: int
    feed: WindowStatesFeed
    # The contact's uuid is a control of its own (e.g. an InfoOnlyDigital):
    # its device is shared, so the device payload must not rename it.
    shared_device: bool


@dataclass
class WindowMonitorControl:
    """One ``WindowMonitor`` block with its resolved room."""

    uuid: str
    name: str
    room: str
    states: dict[str, str]


def _walk_controls(controls: Any) -> Iterable[dict]:
    if not isinstance(controls, dict):
        return
    for control in controls.values():
        if not isinstance(control, dict):
            continue
        yield control
        yield from _walk_controls(control.get("subControls"))


def _known_controls(loxconfig: dict) -> dict[str, dict]:
    known: dict[str, dict] = {}
    for control in _walk_controls(loxconfig.get("controls")):
        uuid = control.get("uuidAction")
        if isinstance(uuid, str) and uuid:
            known.setdefault(uuid, control)
    return known


def window_monitor_controls(loxconfig: Any) -> list[WindowMonitorControl]:
    """Every ``WindowMonitor`` in the structure file (guarded lookups)."""
    if not isinstance(loxconfig, dict):
        return []
    monitors = []
    for control in get_all(loxconfig, WINDOW_MONITOR_TYPE):
        uuid = control.get("uuidAction")
        if not isinstance(uuid, str) or not uuid:
            continue
        states = control.get("states")
        monitors.append(
            WindowMonitorControl(
                uuid=uuid,
                name=str(control.get("name") or ""),
                room=get_room_name_from_room_uuid(loxconfig, control.get("room", "")),
                states={k: v for k, v in states.items() if isinstance(v, str) and v}
                if isinstance(states, dict)
                else {},
            )
        )
    return monitors


def window_contacts(loxconfig: Any) -> list[WindowContact]:
    """
    Every monitored contact, deduplicated by uuid across all monitors.

    The first monitor that lists a contact feeds it (all monitors report the
    same value for the same contact).  Entries without a uuid cannot get a
    stable unique id and are skipped, as are motorised covers.
    """
    if not isinstance(loxconfig, dict):
        return []
    known = _known_controls(loxconfig)
    contacts: list[WindowContact] = []
    seen: set[str] = set()
    for control in get_all(loxconfig, WINDOW_MONITOR_TYPE):
        details = control.get("details")
        windows = details.get("windows") if isinstance(details, dict) else None
        states = control.get("states")
        states_uuid = states.get("windowStates") if isinstance(states, dict) else None
        if not isinstance(windows, list) or not isinstance(states_uuid, str) or not states_uuid:
            continue
        feed = WindowStatesFeed(str(control.get("name") or ""), states_uuid, len(windows))
        for index, window in enumerate(windows):
            if not isinstance(window, dict):
                continue
            uuid = window.get("uuid")
            if not isinstance(uuid, str) or not uuid or uuid in seen:
                continue
            seen.add(uuid)
            existing = known.get(uuid)
            if existing is not None and existing.get("type") in COVER_CONTROL_TYPES:
                continue
            name = window.get("name")
            if existing is not None and isinstance(existing.get("name"), str) and existing["name"]:
                # Match the existing control's device name instead of
                # renaming that device.
                name = existing["name"]
            install_place = window.get("installPlace")
            contacts.append(
                WindowContact(
                    uuid=uuid,
                    name=name if isinstance(name, str) and name else uuid,
                    room=get_room_name_from_room_uuid(loxconfig, window.get("room", "")),
                    install_place=install_place if isinstance(install_place, str) else "",
                    index=index,
                    feed=feed,
                    shared_device=existing is not None,
                )
            )
    return contacts


# --------------------------------------------------------------------------- #
# Entities
# --------------------------------------------------------------------------- #
class _WindowContactEntity(LoxoneEntity):
    """Reads one contact's value out of its monitor's ``windowStates``."""

    _attr_has_entity_name = True
    _unique_id_suffix = ""

    def __init__(self, contact: WindowContact, initial: list[int | None] | None = None) -> None:
        super().__init__(room=contact.room)
        self._contact = contact
        model = None if contact.shared_device else "Window contact"
        self._attr_device_info = get_or_create_device(contact.uuid, contact.name, model, contact.room)
        self._seen = False
        self._present = True
        self._value: int | None = None
        self._attr_extra_state_attributes.update(
            {
                "uuid": contact.uuid,
                "state_uuid": contact.feed.states_uuid,
                "device_type": WINDOW_MONITOR_TYPE,
                "monitor": contact.feed.monitor_name,
            }
        )
        if contact.install_place:
            self._attr_extra_state_attributes["install_place"] = contact.install_place
        if initial is not None:
            self._apply(initial)

    @property
    def unique_id(self) -> str:
        return f"{self._contact.uuid}-{self._unique_id_suffix}"

    def _apply(self, values: list[int | None]) -> None:
        self._seen = True
        index = self._contact.index
        self._present = index < len(values)
        self._value = values[index] if self._present else None
        self._attr_extra_state_attributes["raw_state"] = self._value

    async def event_handler(self, e) -> None:
        uuid = self._contact.feed.states_uuid
        if uuid not in e.data:
            return
        values = self._contact.feed.values(e.data[uuid])
        if values is None:
            return
        self._apply(values)
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        if not super().available:
            return False
        if not self._seen:
            return True
        # 0 = offline; no value at this position = list/values mismatch.
        return self._present and self._value != 0


class LoxoneWindowContactSensor(_WindowContactEntity, BinarySensorEntity):
    """The contact as an open/closed window (tilted counts as open)."""

    _unique_id_suffix = "window"
    _attr_device_class = BinarySensorDeviceClass.WINDOW

    def __init__(self, contact: WindowContact, initial: list[int | None] | None = None) -> None:
        if contact.shared_device:
            # The device already has a primary entity (the contact's own
            # control); a second nameless one would collide with it.
            self._attr_name = "Contact"
        else:
            # The device's main entity: it takes the device (contact) name.
            # Must be set explicitly: ``LoxoneEntity.name`` reads
            # ``_attr_name`` and raises when it was never assigned.
            self._attr_name = None
        super().__init__(contact, initial)

    def _apply(self, values: list[int | None]) -> None:
        super()._apply(values)
        self._attr_extra_state_attributes["position"] = window_state(self._value)

    @property
    def is_on(self) -> bool | None:
        position = window_position(self._value)
        if position is None:
            return None
        return position != POSITION_CLOSED

    @property
    def icon(self) -> str | None:
        """Own icon for tilted and locked; the device-class default otherwise."""
        state = window_state(self._value)
        return STATE_ICONS.get(state) if state is not None else None


class LoxoneWindowPositionSensor(_WindowContactEntity, SensorEntity):
    """The contact's full state: closed / tilted / open / locked / unlocked."""

    _unique_id_suffix = "state"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_translation_key = "window_state"
    _attr_options = STATE_OPTIONS

    def __init__(self, contact: WindowContact, initial: list[int | None] | None = None) -> None:
        super().__init__(contact, initial)
        self._attr_name = "State"

    @property
    def native_value(self) -> str | None:
        return window_state(self._value)


class LoxoneWindowMonitorCountSensor(LoxoneEntity, SensorEntity):
    """One of a monitor's ``num*`` counters."""

    _attr_has_entity_name = True
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, monitor: WindowMonitorControl, state_key: str) -> None:
        name, enabled, diagnostic = COUNT_SENSOR_SPECS[state_key]
        super().__init__(uuidAction=monitor.states[state_key], room=monitor.room)
        self._state_uuid = monitor.states[state_key]
        self._attr_name = name
        self._attr_entity_registry_enabled_default = enabled
        if diagnostic:
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_native_value: int | None = None
        self._attr_device_info = get_or_create_device(monitor.uuid, monitor.name, WINDOW_MONITOR_TYPE, monitor.room)
        self._attr_extra_state_attributes.update(
            {"uuid": monitor.uuid, "state_uuid": self._state_uuid, "device_type": WINDOW_MONITOR_TYPE}
        )

    async def event_handler(self, e) -> None:
        if self._state_uuid not in e.data:
            return
        value = e.data[self._state_uuid]
        try:
            count = int(float(value))
        except (TypeError, ValueError, OverflowError):
            count = None
        self._attr_native_value = count if count is None or count >= 0 else None
        self.async_write_ha_state()


def window_monitor_count_sensors(monitors: list[WindowMonitorControl]) -> list:
    """The counter sensors of every monitor, for the states it advertises."""
    return [
        LoxoneWindowMonitorCountSensor(monitor, key)
        for monitor in monitors
        for key in COUNT_SENSOR_SPECS
        if key in monitor.states
    ]
