"""Discovery and shared device identity of native Intercom Gen 2 controls."""

from __future__ import annotations

from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.entity import DeviceInfo

from ..const import DOMAIN
from ..helpers import get_cat_name_from_cat_uuid, get_room_name_from_room_uuid

# States the Intercom entities read. ``version`` and ``jLocked`` are not in
# the structure file documentation; they were observed on a real device.
STATE_KEYS = frozenset({"address", "deviceState", "version", "bell", "muted", "answers", "jLocked"})


def miniserver_identifier(coordinator, entry):
    """Return the identifier the Miniserver device is registered with.

    Same rule as ``MiniServer.async_update_device_registry``: the serial,
    else the config entry's unique id. The entry id is only the last
    resort for the Intercom's own key; no Miniserver device has it.
    """
    return DOMAIN, coordinator.miniserver.serial or entry.unique_id or entry.entry_id


class IntercomDevice:
    """One native Intercom and the Miniserver control that owns its states."""

    def __init__(self, coordinator, entry, control, uuid):
        self.coordinator = coordinator
        self.entry = entry
        self.control = control
        self.uuid = uuid
        self.action_uuid = control.get("uuidAction") or uuid
        details = control.get("details")
        self.details = dict(details) if isinstance(details, dict) else {}
        states = control.get("states")
        self.states = {
            name: state_uuid
            for name, state_uuid in (states if isinstance(states, dict) else {}).items()
            if isinstance(state_uuid, str) and state_uuid
        }
        owner = miniserver_identifier(coordinator, entry)[1]
        hardware = self.details.get("deviceUuid") or self.action_uuid
        self.key = f"{owner}_{hardware}"
        self.name = control.get("name") or self.details.get("deviceName") or "Intercom"
        structure = coordinator.miniserver.lox_config.json or {}
        self.room = get_room_name_from_room_uuid(structure, control.get("room", ""))
        self.category = get_cat_name_from_cat_uuid(structure, control.get("cat", ""))

    def device_info(self, hass, firmware=None):
        """Group every Intercom entity on one device below its Miniserver."""
        info = DeviceInfo(
            identifiers={(DOMAIN, self.key)},
            manufacturer="Loxone",
            model="Intercom Gen 2",
            name=self.name,
            suggested_area=self.room or None,
        )
        if firmware:
            info["sw_version"] = firmware
        if serial := self.details.get("serialNo") or self.details.get("serialNr"):
            info["serial_number"] = str(serial)
        # Only reference the Miniserver device if it is registered: Home
        # Assistant rejects a ``via_device`` that does not exist.
        parent = miniserver_identifier(self.coordinator, self.entry)
        if dr.async_get(hass).async_get_device(identifiers={parent}) is not None:
            info["via_device"] = parent
        return info


def intercom_devices(coordinator, entry):
    """Yield the local native Intercom Gen 2 devices of this Miniserver.

    Spec (Structure File, IntercomV2): ``details.deviceType`` 1 is the
    Intercom, 0 a custom/unknown device; ``details.trustAddress`` is set
    for a device of a trust member. Both are left out.
    """
    seen = set()
    structure = coordinator.miniserver.lox_config.json or {}
    for uuid, control in (structure.get("controls") or {}).items():
        if not isinstance(control, dict) or control.get("type") != "IntercomV2":
            continue
        details = control.get("details") or {}
        if not isinstance(details, dict) or details.get("deviceType", 1) not in (1, "1") or details.get("trustAddress"):
            continue
        device = IntercomDevice(coordinator, entry, control, uuid)
        if device.key not in seen:
            seen.add(device.key)
            yield device


def intercom_state_uuids(structure):
    """Return the state uuids the Intercom entities read."""
    return frozenset(
        uuid
        for control in ((structure or {}).get("controls") or {}).values()
        if isinstance(control, dict) and control.get("type") == "IntercomV2"
        for name, uuid in (control.get("states") or {}).items()
        if name in STATE_KEYS and isinstance(uuid, str)
    )
