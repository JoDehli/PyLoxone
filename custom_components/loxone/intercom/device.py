"""Native Intercom discovery and shared identity, independent of camera APIs."""

from __future__ import annotations

from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.entity import DeviceInfo

from ..const import DOMAIN
from ..helpers import get_cat_name_from_cat_uuid, get_room_name_from_room_uuid

STATE_KEYS = frozenset({"address", "deviceState", "version", "bell", "muted", "answers", "jLocked"})


def miniserver_identifier(coordinator, entry):
    """Retain the camera's owner identity when structure-file serial metadata is absent."""
    return DOMAIN, coordinator.miniserver.serial or entry.unique_id or entry.entry_id


def registered_device(hass, identifier, entry_id):
    """Look up an entry-owned device using the registry API available on this HA."""
    registry = dr.async_get(hass)
    if hasattr(registry, "async_get_device_by_identifier"):
        return registry.async_get_device_by_identifier(identifier, entry_id)
    device = registry.async_get_device(identifiers={identifier})
    return device if device and entry_id in device.config_entries else None


class IntercomDevice:
    """One native device and the Miniserver control that owns its states and actions."""

    def __init__(self, coordinator, entry, control, uuid):
        self.coordinator = coordinator
        self.entry = entry
        self.control = control
        self.uuid = uuid
        self.action_uuid = control.get("uuidAction") or uuid
        self.details = dict(control.get("details") or {})
        self.states = {
            name: state_uuid
            for name, state_uuid in (control.get("states") or {}).items()
            if isinstance(state_uuid, str) and state_uuid
        }
        owner = miniserver_identifier(coordinator, entry)[1]
        hardware = self.details.get("deviceUuid") or self.action_uuid
        self.key = f"{owner}_{hardware}"
        self.name = control.get("name") or self.details.get("deviceName") or "Intercom"
        structure = coordinator.miniserver.lox_config.json or {}
        self.room = get_room_name_from_room_uuid(structure, control.get("room", ""))
        self.category = get_cat_name_from_cat_uuid(structure, control.get("cat", ""))

    def ensure_parent(self, hass):
        """Create the parent once, preserving any previously registered metadata."""
        identifier = miniserver_identifier(self.coordinator, self.entry)
        parent = registered_device(hass, identifier, self.entry.entry_id)
        if parent is None:
            parent = dr.async_get(hass).async_get_or_create(
                config_entry_id=self.entry.entry_id,
                identifiers={identifier},
                manufacturer="Loxone",
                name=getattr(self.coordinator.miniserver, "name", None) or "Miniserver",
                model="Miniserver",
                sw_version=getattr(self.coordinator.miniserver, "software_version", None),
            )
        return parent

    def device_info(self, hass, firmware=None):
        """Group every Intercom entity with the existing camera hardware identity."""
        info = DeviceInfo(
            identifiers={(DOMAIN, self.key)},
            manufacturer="Loxone",
            model="Intercom Gen 2",
            name=self.name,
            suggested_area=self.room or None,
        )
        if firmware:
            info["sw_version"] = firmware
        if serial := self.details.get("serialNr") or self.details.get("serialNo"):
            info["serial_number"] = str(serial)
        parent = self.ensure_parent(hass)
        if hasattr(dr.async_get(hass), "async_get_device_by_identifier"):
            info["via_device_id"] = parent.id
        else:
            info["via_device"] = miniserver_identifier(self.coordinator, self.entry)
        return info


def intercom_devices(coordinator, entry):
    """Discover the same local native devices on every entity platform."""
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
    """Cache only public states needed by Intercom entities, never auth data."""
    return frozenset(
        uuid
        for control in (structure.get("controls") or {}).values()
        if isinstance(control, dict) and control.get("type") == "IntercomV2"
        for name, uuid in (control.get("states") or {}).items()
        if name in STATE_KEYS and isinstance(uuid, str)
    )
