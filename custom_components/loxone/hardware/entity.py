"""Home Assistant entities for physical Loxone hardware."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.components.select import SelectEntity
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfTemperature
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ..const import CONF_HARDWARE_MAPPINGS, DOMAIN  # noqa: TID252
from .api import mapping_key
from .coordinator import LoxoneHardwareCoordinator

if TYPE_CHECKING:
    from collections.abc import Callable

    from homeassistant.config_entries import ConfigEntry

    from .models import HardwareData, HardwareDevice, UiControl

AUTOMATIC = "__automatic__"
UNASSIGNED = "__unassigned__"


def window_position_is_open(position: str) -> bool | None:
    """Map an exact handle position to Home Assistant window semantics."""
    if position == "unknown":
        return None
    return position != "closed"


def window_position_icon(position: str) -> str:
    """Return the closest Material Design icon for a handle position."""
    return {
        "closed": "mdi:window-closed-variant",
        "tilted": "mdi:angle-acute",
        "open": "mdi:window-open-variant",
    }.get(position, "mdi:window-closed-alert")


def air_base_identifier(data: HardwareData) -> tuple[str, str]:
    """Return the stable Air Base device identifier."""
    return (DOMAIN, f"{data.miniserver_serial}:air-base:{data.air_base}")


def hardware_identifier(data: HardwareData, device: HardwareDevice) -> tuple[str, str]:
    """Return the stable physical-device identifier."""
    return (DOMAIN, f"{data.miniserver_serial}:air:{device.serial}")


def hardware_device_info(data: HardwareData, device: HardwareDevice) -> DeviceInfo:
    """Build registry metadata for one physical Air device."""
    return DeviceInfo(
        identifiers={hardware_identifier(data, device)},
        manufacturer="Loxone",
        model=device.device_type,
        name=device.name,
        serial_number=device.serial,
        suggested_area=device.room,
        sw_version=device.firmware,
        hw_version=device.hardware_version,
    )


def control_device_mapping(
    data: HardwareData,
) -> dict[str, tuple[DeviceInfo, str]]:
    """Map every assigned logical control to its physical HA device."""
    result = {}
    for device in data.devices.values():
        info = hardware_device_info(data, device)
        for role, control_uuid in device.resolved_mappings.items():
            result[control_uuid.casefold()] = (info, role)
    return result


class LoxoneHardwareEntity(CoordinatorEntity[LoxoneHardwareCoordinator]):
    """Base entity for an Air device."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: LoxoneHardwareCoordinator,
        config_entry: ConfigEntry,
        device_id: str,
        key: str,
    ) -> None:
        """Initialize a physical-hardware entity."""
        super().__init__(coordinator)
        self.config_entry = config_entry
        self.device_id = device_id
        self._attr_unique_id = f"{coordinator.data.miniserver_serial}-air-{device_id}-{key}"
        self._attr_device_info = hardware_device_info(coordinator.data, self.device)

    @property
    def device(self) -> HardwareDevice:
        """Return current device data."""
        return self.coordinator.data.devices[self.device_id]

    @property
    def available(self) -> bool:
        """Require a successful inventory and an online Air device."""
        return super().available and self.device.online

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose identifiers useful for diagnostics."""
        return {
            "hardware_address": self.device.address_prefix,
            "air_device_id": self.device.device_id,
            "installation": self.device.installation,
        }


class HardwareValueSensor(LoxoneHardwareEntity, SensorEntity):
    """A hardware value supplied by the coordinator."""

    def __init__(  # noqa: PLR0913
        self,
        coordinator: LoxoneHardwareCoordinator,
        config_entry: ConfigEntry,
        device_id: str,
        key: str,
        value_fn: Callable[[HardwareDevice], Any],
        *,
        translation_key: str,
        device_class: SensorDeviceClass | None = None,
        native_unit: str | None = None,
        state_class: SensorStateClass | None = None,
        icon: str | None = None,
        diagnostic: bool = True,
        available_offline: bool = False,
    ) -> None:
        """Initialize a coordinator-backed diagnostic value."""
        super().__init__(coordinator, config_entry, device_id, key)
        self._value_fn = value_fn
        self._available_offline = available_offline
        self._attr_translation_key = translation_key
        self._attr_device_class = device_class
        self._attr_native_unit_of_measurement = native_unit
        self._attr_state_class = state_class
        self._attr_icon = icon
        if diagnostic:
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self) -> Any:
        """Return the current native sensor value."""
        return self._value_fn(self.device)

    @property
    def available(self) -> bool:
        """Return whether the latest relevant data is available."""
        if self._available_offline:
            return self.coordinator.last_update_success
        return super().available


class HardwarePositionSensor(LoxoneHardwareEntity, SensorEntity):
    """Fallback three-state position when no LoxAPP control is mapped."""

    _attr_translation_key = "hardware_position"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options: ClassVar[list[str]] = ["closed", "tilted", "open", "unknown"]

    def __init__(
        self,
        coordinator: LoxoneHardwareCoordinator,
        config_entry: ConfigEntry,
        device_id: str,
    ) -> None:
        """Initialize a fallback position sensor."""
        super().__init__(coordinator, config_entry, device_id, "position")

    @property
    def native_value(self) -> str:
        """Return the normalized handle position."""
        return self.device.position_name

    @property
    def icon(self) -> str:
        """Return an icon matching the current handle position."""
        return window_position_icon(self.native_value)


class HardwareUpdateModeSensor(LoxoneHardwareEntity, SensorEntity):
    """Show whether mapped handle values can use push."""

    _attr_translation_key = "hardware_update_mode"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options: ClassVar[list[str]] = ["polled", "hybrid", "pushed"]
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:update"

    def __init__(
        self,
        coordinator: LoxoneHardwareCoordinator,
        config_entry: ConfigEntry,
        device_id: str,
    ) -> None:
        """Initialize an update-mode sensor."""
        super().__init__(coordinator, config_entry, device_id, "update-mode")

    @property
    def native_value(self) -> str:
        """Return the active combination of push and polling."""
        if not self.coordinator.push_connected():
            return "polled"
        count = sum(role in self.device.push_state_uuids for role in ("position", "vibration"))
        return ("polled", "hybrid", "pushed")[count]

    @property
    def available(self) -> bool:
        """Return whether the coordinator has a valid snapshot."""
        return self.coordinator.last_update_success


class HardwareOnlineSensor(LoxoneHardwareEntity, BinarySensorEntity):
    """Report whether a physical device is online."""

    _attr_translation_key = "hardware_online"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: LoxoneHardwareCoordinator,
        config_entry: ConfigEntry,
        device_id: str,
    ) -> None:
        """Initialize a connectivity sensor."""
        super().__init__(coordinator, config_entry, device_id, "online")

    @property
    def is_on(self) -> bool:
        """Return the physical device connectivity state."""
        return self.device.online

    @property
    def available(self) -> bool:
        """Return whether the coordinator has a valid snapshot."""
        return self.coordinator.last_update_success


class HardwareWindowSensor(LoxoneHardwareEntity, BinarySensorEntity):
    """Expose a window handle through Home Assistant's window semantics."""

    _attr_name = None
    _attr_device_class = BinarySensorDeviceClass.WINDOW

    def __init__(
        self,
        coordinator: LoxoneHardwareCoordinator,
        config_entry: ConfigEntry,
        device_id: str,
    ) -> None:
        """Initialize the native window projection."""
        super().__init__(coordinator, config_entry, device_id, "window")

    @property
    def is_on(self) -> bool | None:
        """Return true for fully open and tilted windows."""
        return window_position_is_open(self.device.position_name)

    @property
    def icon(self) -> str:
        """Distinguish closed, tilted and fully open positions visually."""
        return window_position_icon(self.device.position_name)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose the exact position alongside the binary window state."""
        return {
            **super().extra_state_attributes,
            "window_position": self.device.position_name,
        }


class HardwareVibrationSensor(LoxoneHardwareEntity, BinarySensorEntity):
    """Fallback vibration sensor when no LoxAPP control is mapped."""

    _attr_translation_key = "hardware_vibration"
    _attr_device_class = BinarySensorDeviceClass.VIBRATION

    def __init__(
        self,
        coordinator: LoxoneHardwareCoordinator,
        config_entry: ConfigEntry,
        device_id: str,
    ) -> None:
        """Initialize a fallback vibration sensor."""
        super().__init__(coordinator, config_entry, device_id, "vibration")

    @property
    def is_on(self) -> bool | None:
        """Return whether vibration is currently detected."""
        return self.device.vibration


class HardwareBatteryLowSensor(LoxoneHardwareEntity, BinarySensorEntity):
    """Report the physical device's low-battery flag."""

    _attr_translation_key = "hardware_battery_low"
    _attr_device_class = BinarySensorDeviceClass.BATTERY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: LoxoneHardwareCoordinator,
        config_entry: ConfigEntry,
        device_id: str,
    ) -> None:
        """Initialize a low-battery sensor."""
        super().__init__(coordinator, config_entry, device_id, "battery-low")

    @property
    def is_on(self) -> bool | None:
        """Return whether the device reports a weak battery."""
        return self.device.battery_low


def hardware_sensor_entities(coordinator: LoxoneHardwareCoordinator, config_entry: ConfigEntry) -> list[SensorEntity]:
    """Build hardware sensors without duplicating mapped LoxAPP values."""
    entities: list[SensorEntity] = []
    for device_id, device in coordinator.data.devices.items():
        if device.is_window_handle:
            if "position" not in device.resolved_mappings:
                entities.append(HardwarePositionSensor(coordinator, config_entry, device_id))
            entities.append(HardwareUpdateModeSensor(coordinator, config_entry, device_id))
        if device.battery is not None or device.is_window_handle:
            entities.append(
                HardwareValueSensor(
                    coordinator,
                    config_entry,
                    device_id,
                    "battery",
                    lambda item: item.battery,
                    translation_key="hardware_battery",
                    device_class=SensorDeviceClass.BATTERY,
                    native_unit=PERCENTAGE,
                    state_class=SensorStateClass.MEASUREMENT,
                )
            )
        if device.system_temperature is not None:
            entities.append(
                HardwareValueSensor(
                    coordinator,
                    config_entry,
                    device_id,
                    "system-temperature",
                    lambda item: item.system_temperature,
                    translation_key="hardware_system_temperature",
                    device_class=SensorDeviceClass.TEMPERATURE,
                    native_unit=UnitOfTemperature.CELSIUS,
                    state_class=SensorStateClass.MEASUREMENT,
                )
            )
        for key, translation, getter, icon in (
            ("hops", "hardware_hops", lambda item: item.hops, "mdi:access-point-network"),
            ("quality-device", "hardware_quality_device", lambda item: item.quality_device, "mdi:signal"),
            (
                "quality-extension",
                "hardware_quality_extension",
                lambda item: item.quality_extension,
                "mdi:signal-distance-variant",
            ),
            ("last-received", "hardware_last_received", lambda item: item.last_received, None),
        ):
            if getter(device) is None:
                continue
            entities.append(
                HardwareValueSensor(
                    coordinator,
                    config_entry,
                    device_id,
                    key,
                    getter,
                    translation_key=translation,
                    device_class=(SensorDeviceClass.TIMESTAMP if key == "last-received" else None),
                    icon=icon,
                    available_offline=True,
                )
            )
    return entities


def hardware_binary_sensor_entities(
    coordinator: LoxoneHardwareCoordinator, config_entry: ConfigEntry
) -> list[BinarySensorEntity]:
    """Build physical binary sensors."""
    entities: list[BinarySensorEntity] = []
    for device_id, device in coordinator.data.devices.items():
        entities.append(HardwareOnlineSensor(coordinator, config_entry, device_id))
        if device.is_window_handle:
            entities.append(HardwareWindowSensor(coordinator, config_entry, device_id))
            if "vibration" not in device.resolved_mappings:
                entities.append(HardwareVibrationSensor(coordinator, config_entry, device_id))
        if device.battery_low is not None or device.is_window_handle:
            entities.append(HardwareBatteryLowSensor(coordinator, config_entry, device_id))
    return entities


def _control_label(control: UiControl) -> str:
    room = f"{control.room} · " if control.room else ""
    return f"{room}{control.name} [{control.control_type} · {control.uuid[:8]}]"[:255]


class HardwareMappingSelect(LoxoneHardwareEntity, SelectEntity):
    """Assign a physical device/role to one logical LoxAPP control."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:link-variant"

    def __init__(
        self,
        coordinator: LoxoneHardwareCoordinator,
        config_entry: ConfigEntry,
        device_id: str,
        role: str,
    ) -> None:
        """Initialize a logical-control assignment selector."""
        super().__init__(coordinator, config_entry, device_id, f"mapping-{role}")
        self.role = role
        self._attr_translation_key = f"hardware_mapping_{role}"
        self._label_to_value: dict[str, str] = {}
        self._value_to_label: dict[str, str] = {}
        self._rebuild_options()

    def _compatible_controls(self) -> list[UiControl]:
        expected = {
            "position": "InfoOnlyAnalog",
            "vibration": "InfoOnlyDigital",
        }.get(self.role)
        controls = self.coordinator.data.controls.values()
        if expected:
            controls = (item for item in controls if item.control_type == expected)
        return sorted(
            controls,
            key=lambda item: ((item.room or "").casefold(), item.name.casefold(), item.uuid),
        )

    def _rebuild_options(self) -> None:
        automatic_uuid = self.device.automatic_mappings.get(self.role)
        automatic_control = self.coordinator.data.control(automatic_uuid)
        automatic_label = "Automatic"
        if automatic_control:
            automatic_label = f"Automatic · {_control_label(automatic_control)}"[:255]
        self._label_to_value = {automatic_label: AUTOMATIC, "Not assigned": UNASSIGNED}
        self._value_to_label = {AUTOMATIC: automatic_label, UNASSIGNED: "Not assigned"}
        used = set(self._label_to_value)
        for control in self._compatible_controls():
            base = _control_label(control)
            label = base
            number = 2
            while label in used:
                label = f"{base[:240]} ({number})"
                number += 1
            used.add(label)
            self._label_to_value[label] = control.uuid
            self._value_to_label[control.uuid] = label
        self._attr_options = list(self._label_to_value)

    @property
    def current_option(self) -> str:
        """Return the label for the currently resolved assignment."""
        self._rebuild_options()
        key = mapping_key(self.device.serial, self.role)
        mappings = self.config_entry.data.get(CONF_HARDWARE_MAPPINGS, {})
        if key not in mappings:
            if self.device.automatic_mappings.get(self.role):
                return self._value_to_label[AUTOMATIC]
            return self._value_to_label[UNASSIGNED]
        selected = mappings[key]
        if not selected:
            return self._value_to_label[UNASSIGNED]
        return self._value_to_label.get(selected.casefold(), self._value_to_label[UNASSIGNED])

    async def async_select_option(self, option: str) -> None:
        """Persist the selected assignment and reload the integration."""
        selected = self._label_to_value[option]
        mappings = dict(self.config_entry.data.get(CONF_HARDWARE_MAPPINGS, {}))
        key = mapping_key(self.device.serial, self.role)
        if selected == AUTOMATIC:
            mappings.pop(key, None)
        elif selected == UNASSIGNED:
            mappings[key] = ""
        else:
            mappings[key] = selected
        self.hass.config_entries.async_update_entry(
            self.config_entry,
            data={**self.config_entry.data, CONF_HARDWARE_MAPPINGS: mappings},
        )
        await self.hass.config_entries.async_reload(self.config_entry.entry_id)


def hardware_select_entities(coordinator: LoxoneHardwareCoordinator, config_entry: ConfigEntry) -> list[SelectEntity]:
    """Create position and vibration mappings on every window handle."""
    entities: list[SelectEntity] = []
    for device_id in coordinator.data.devices:
        entities.extend(
            (
                HardwareMappingSelect(coordinator, config_entry, device_id, "position"),
                HardwareMappingSelect(coordinator, config_entry, device_id, "vibration"),
            )
        )
    return entities
