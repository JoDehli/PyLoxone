"""Coordinator for physical Loxone hardware."""

from __future__ import annotations

import logging
import time
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import LoxoneHardwareApi, LoxoneHardwareError
from .models import HardwareData

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


class LoxoneHardwareCoordinator(DataUpdateCoordinator[HardwareData]):
    """Combine WebSocket events with tiered HTTP polling."""

    def __init__(  # noqa: PLR0913
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        api: LoxoneHardwareApi,
        initial_data: HardwareData,
        fast_interval: int = 2,
        inventory_interval: int = 30,
        battery_interval: int = 900,
    ) -> None:
        """Initialize polling around an already discovered hardware snapshot."""
        super().__init__(
            hass,
            logger=_LOGGER,
            config_entry=config_entry,
            name="PyLoxone hardware",
            update_interval=timedelta(seconds=fast_interval),
            always_update=True,
        )
        self.api = api
        self.data = initial_data
        self.inventory_interval = inventory_interval
        self.battery_interval = battery_interval
        self._last_inventory = time.monotonic()
        self._last_slow_poll = 0.0
        self.push_connected = lambda: False

    async def _async_update_data(self) -> HardwareData:
        now = time.monotonic()
        try:
            current = deepcopy(self.data)
            if now - self._last_inventory >= self.inventory_interval:
                self._last_inventory = now
                try:
                    discovered = await self.api.async_discover()
                except LoxoneHardwareError as err:
                    _LOGGER.warning(
                        "Could not refresh Loxone hardware inventory; retaining last snapshot: %s",
                        err,
                    )
                else:
                    self._merge_runtime_values(discovered, current)
                    current = discovered
            current = await self.api.async_refresh_fast(current)
            if now - self._last_slow_poll >= self.battery_interval:
                current = await self.api.async_refresh_battery_and_temperature(current)
                self._last_slow_poll = now
            self._publish_mapped_values(current)
        except LoxoneHardwareError as err:
            message = f"Could not update Loxone hardware: {err}"
            raise UpdateFailed(message) from err
        else:
            return current

    def _publish_mapped_values(self, data: HardwareData) -> None:
        """Feed polled fallback values into existing PyLoxone entities."""
        payload: dict[str, float] = {}
        for device in data.devices.values():
            for role, value in (
                ("position", device.position),
                ("vibration", device.vibration),
            ):
                control_uuid = device.resolved_mappings.get(role)
                if control_uuid and value is not None:
                    payload[control_uuid] = float(value)
        if payload:
            self.hass.bus.async_fire("loxone_event", payload)

    @staticmethod
    def _merge_runtime_values(target: HardwareData, source: HardwareData) -> None:
        target.last_push = source.last_push
        target.last_poll = source.last_poll
        for device_id, target_device in target.devices.items():
            if source_device := source.devices.get(device_id):
                target_device.position = source_device.position
                target_device.vibration = source_device.vibration
                target_device.system_temperature = source_device.system_temperature

    async def async_apply_push(self, values: dict[str, Any]) -> None:
        """Apply mapped WebSocket values immediately."""
        if not isinstance(values, dict):
            return
        updated = deepcopy(self.data)
        changed = False
        for state_uuid, value in values.items():
            mapped = self.api.push_mapping.get(str(state_uuid).casefold())
            if not mapped:
                continue
            device_id, role = mapped
            device = updated.devices.get(device_id)
            if not device:
                continue
            new_value = round(value) if role == "position" else bool(value)
            attribute = "position" if role == "position" else "vibration"
            if getattr(device, attribute) != new_value:
                setattr(device, attribute, new_value)
                changed = True
        if changed:
            updated.last_push = datetime.now(UTC)
            self.async_set_updated_data(updated)
