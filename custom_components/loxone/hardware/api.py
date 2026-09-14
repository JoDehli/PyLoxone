"""Read physical hardware from the local Loxone Miniserver API."""

from __future__ import annotations

import asyncio
import logging
import re
import xml.etree.ElementTree as ET
from copy import deepcopy
from datetime import datetime, timezone, tzinfo
from typing import Any
from urllib.parse import quote, urlparse

from aiohttp import BasicAuth, ClientError, ClientResponseError, ClientSession

from .models import HardwareData, HardwareDevice, control_catalog

_LOGGER = logging.getLogger(__name__)

CHANNEL_BATTERY_LOW = "I0"
CHANNEL_BATTERY = "AI0"
CHANNEL_POSITION = "AI2"
CHANNEL_VIBRATION = "I4"
CHANNEL_SYSTEM_TEMPERATURE = "ST"


class LoxoneHardwareError(Exception):
    """Base error for physical hardware access."""


def _ll_value(payload: dict[str, Any]) -> Any:
    ll = payload.get("LL") or {}
    if str(ll.get("Code", ll.get("code", ""))) != "200":
        raise LoxoneHardwareError(f"Loxone returned code {ll.get('Code', ll.get('code', 'unknown'))}")
    return ll.get("value")


def _as_int(value: str | None) -> int | None:
    if value is None:
        return None
    match = re.search(r"-?\d+", value)
    return int(match.group()) if match else None


def _as_float(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _as_bool(value: str | None) -> bool | None:
    number = _as_int(value)
    return bool(number) if number is not None else None


def _parse_datetime(value: str | None, local_timezone: tzinfo) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=local_timezone)
    except ValueError:
        return None


def parse_enum_devices(value: str) -> tuple[str, str]:
    """Extract Miniserver serial and Air Base address from enumdev."""
    miniserver = re.search(r"\(([0-9A-Fa-f]{12})\)", value)
    air_base = re.search(r"[0-9A-Fa-f]{12}\.([0-9A-Fa-f]{8})", value)
    if not miniserver or not air_base:
        raise LoxoneHardwareError("Could not identify Miniserver and Air Base")
    return miniserver.group(1).upper(), air_base.group(1).upper()


def parse_channel_names(value: str) -> dict[str, str]:
    """Return physical I/O address to configured designation mapping."""
    result: dict[str, str] = {}
    pattern = re.compile(
        r"(?:^|,\s*)(.*?)\s+"
        r"\(([0-9A-Fa-f]{8}\.[0-9A-Fa-f]{6}\."
        r"(?:AI|AQ|I|Q|ST)\d*),"
    )
    for match in pattern.finditer(value):
        result[match.group(2).upper()] = match.group(1).strip()
    return result


def parse_status_xml(
    xml: str,
    miniserver_serial: str,
    air_base_hint: str,
    structure: dict[str, Any],
    local_timezone: tzinfo = timezone.utc,
) -> HardwareData:
    """Parse the physical inventory from /data/status."""
    root = ET.fromstring(xml)
    miniserver = root.find(".//Miniserver")
    extension = next(
        (
            item
            for item in root.findall(".//Extension")
            if item.attrib.get("Serial", "").upper() == air_base_hint.upper()
            or "air base" in item.attrib.get("Type", "").casefold()
        ),
        None,
    )
    miniserver_name = (
        miniserver.attrib.get("Name", "Loxone Miniserver") if miniserver is not None else "Loxone Miniserver"
    )
    miniserver_version = miniserver.attrib.get("Version") if miniserver is not None else None
    air_base = air_base_hint
    air_base_version = None
    if extension is not None:
        air_base = extension.attrib.get("Serial", air_base_hint).upper()
        air_base_version = extension.attrib.get("Version")

    data = HardwareData(
        miniserver_serial=miniserver_serial,
        miniserver_name=miniserver_name,
        miniserver_version=miniserver_version,
        air_base=air_base,
        air_base_version=air_base_version,
        controls=control_catalog(structure),
        last_inventory=datetime.now(timezone.utc),
    )
    for element in root.findall(".//AirDevice"):
        serial = element.attrib.get("Serial", "").upper()
        if not serial:
            continue
        device_id = "".join(serial.split(":")[-3:])
        data.devices[device_id] = HardwareDevice(
            device_id=device_id,
            serial=serial,
            name=element.attrib.get("Name") or f"{element.attrib.get('Type', 'Air Device')} {device_id}",
            device_type=element.attrib.get("Type") or "Air Device",
            room=element.attrib.get("Place") or None,
            installation=element.attrib.get("Inst") or None,
            air_base=air_base,
            online=element.attrib.get("Online", "false").lower() == "true",
            battery=_as_int(element.attrib.get("Battery")),
            battery_low=(
                element.attrib.get("BattWeak", "false").lower() == "true" if "BattWeak" in element.attrib else None
            ),
            last_received=_parse_datetime(element.attrib.get("LastReceived"), local_timezone),
            firmware=element.attrib.get("Version"),
            hardware_version=element.attrib.get("HwVersion"),
            hops=_as_int(element.attrib.get("Hops")),
            quality_extension=_as_int(element.attrib.get("QualityExt")),
            quality_device=_as_int(element.attrib.get("QualityDev")),
            extra={
                key: value
                for key, value in element.attrib.items()
                if key
                in {
                    "Code",
                    "IP",
                    "TimeDiff",
                    "MinVersion",
                    "IsDeviceAlwaysActive",
                    "BatTooWeakForUpdate",
                }
            },
        )
    return data


def apply_control_mappings(
    data: HardwareData,
    channel_names: dict[str, str],
    manual_mappings: dict[str, str] | None = None,
) -> dict[str, tuple[str, str]]:
    """Resolve automatic/manual UI mappings and return push-state routing."""
    manual_mappings = manual_mappings or {}
    controls_by_name: dict[str, list[Any]] = {}
    for control in data.controls.values():
        controls_by_name.setdefault(control.name.strip().casefold(), []).append(control)

    push_mapping: dict[str, tuple[str, str]] = {}
    for device in data.devices.values():
        if device.is_window_handle:
            for channel, role, expected_type in (
                (CHANNEL_POSITION, "position", "InfoOnlyAnalog"),
                (CHANNEL_VIBRATION, "vibration", "InfoOnlyDigital"),
            ):
                address = f"{device.address_prefix}.{channel}".upper()
                designation = channel_names.get(address)
                if not designation:
                    continue
                matches = [
                    control
                    for control in controls_by_name.get(designation.casefold(), [])
                    if control.control_type == expected_type
                ]
                if len({control.uuid for control in matches}) == 1:
                    device.automatic_mappings[role] = matches[0].uuid

        for role in ("primary", "position", "vibration"):
            key = mapping_key(device.serial, role)
            if key in manual_mappings:
                chosen = manual_mappings[key]
            else:
                chosen = device.automatic_mappings.get(role, "")
            if chosen and chosen.casefold() in data.controls:
                device.resolved_mappings[role] = chosen.casefold()

        for role in ("position", "vibration"):
            control = data.control(device.resolved_mappings.get(role))
            if control is None:
                continue
            preferred = "value" if role == "position" else "active"
            state_uuid = control.states.get(preferred)
            if not state_uuid and len(control.states) == 1:
                state_uuid = next(iter(control.states.values()))
            state_uuid = state_uuid or control.uuid
            device.push_state_uuids[role] = state_uuid.casefold()
            push_mapping[state_uuid.casefold()] = (device.device_id, role)
    return push_mapping


def mapping_key(serial: str, role: str) -> str:
    """Return the persistent key for one physical association."""
    return f"{serial.upper()}:{role}"


class LoxoneHardwareApi:
    """HTTP client for physical Air hardware."""

    def __init__(
        self,
        session: ClientSession,
        host: str,
        port: int,
        username: str,
        password: str,
        verify_ssl: bool,
        structure: dict[str, Any],
        manual_mappings: dict[str, str] | None = None,
        local_timezone: tzinfo = timezone.utc,
    ) -> None:
        parsed = urlparse(host if "://" in host else f"//{host}")
        scheme = parsed.scheme or ("https" if port == 443 else "http")
        hostname = parsed.hostname or parsed.path
        default_port = 443 if scheme == "https" else 80
        port_part = "" if port == default_port else f":{port}"
        self.base_url = f"{scheme}://{hostname}{port_part}"
        self.session = session
        self.auth = BasicAuth(username, password, encoding="utf-8")
        self.verify_ssl = verify_ssl
        self.structure = structure
        self.manual_mappings = manual_mappings or {}
        self.local_timezone = local_timezone
        self.miniserver_serial: str | None = None
        self.air_base: str | None = None
        self.channel_names: dict[str, str] = {}
        self.push_mapping: dict[str, tuple[str, str]] = {}

    async def _request_json(self, path: str) -> dict[str, Any]:
        try:
            async with asyncio.timeout(15):
                response = await self.session.get(
                    f"{self.base_url}/{path.lstrip('/')}",
                    auth=self.auth,
                    ssl=self.verify_ssl if self.base_url.startswith("https") else None,
                )
                response.raise_for_status()
                return await response.json(content_type=None)
        except (TimeoutError, ClientError, ValueError) as err:
            raise LoxoneHardwareError(str(err)) from err

    async def _request_text(self, path: str) -> str:
        try:
            async with asyncio.timeout(15):
                response = await self.session.get(
                    f"{self.base_url}/{path.lstrip('/')}",
                    auth=self.auth,
                    ssl=self.verify_ssl if self.base_url.startswith("https") else None,
                )
                response.raise_for_status()
                return await response.text()
        except (TimeoutError, ClientResponseError, ClientError) as err:
            raise LoxoneHardwareError(str(err)) from err

    async def async_discover(self) -> HardwareData:
        """Read inventory, channel designations and mappings."""
        enum_devices, enum_inputs, enum_outputs, status = await asyncio.gather(
            self._request_json("jdev/sps/enumdev"),
            self._request_json("jdev/sps/enumin"),
            self._request_json("jdev/sps/enumout"),
            self._request_text("data/status"),
        )
        serial, air_base = parse_enum_devices(str(_ll_value(enum_devices)))
        self.miniserver_serial = serial
        self.air_base = air_base
        self.channel_names = {
            **parse_channel_names(str(_ll_value(enum_inputs))),
            **parse_channel_names(str(_ll_value(enum_outputs))),
        }
        data = parse_status_xml(
            status,
            serial,
            air_base,
            self.structure,
            self.local_timezone,
        )
        self.push_mapping = apply_control_mappings(data, self.channel_names, self.manual_mappings)
        return data

    async def async_read_channel(self, device: HardwareDevice, channel: str) -> str:
        """Read one physical channel."""
        address = quote(f"{device.address_prefix}.{channel}", safe=".")
        return str(_ll_value(await self._request_json(f"jdev/sps/io/{address}")))

    async def async_refresh_fast(self, data: HardwareData) -> HardwareData:
        """Poll the live channels not guaranteed to exist in LoxAPP."""
        updated = deepcopy(data)

        async def read(device: HardwareDevice) -> None:
            channels: list[tuple[str, str]] = []
            if device.is_window_handle:
                channels.extend(((CHANNEL_POSITION, "position"), (CHANNEL_VIBRATION, "vibration")))
            if not channels:
                return
            values = await asyncio.gather(
                *(self.async_read_channel(device, channel) for channel, _ in channels),
                return_exceptions=True,
            )
            for (_, attribute), value in zip(channels, values, strict=True):
                if isinstance(value, Exception):
                    continue
                setattr(
                    device,
                    attribute,
                    _as_int(value) if attribute == "position" else _as_bool(value),
                )

        await asyncio.gather(*(read(device) for device in updated.devices.values()))
        updated.last_poll = datetime.now(timezone.utc)
        return updated

    async def async_refresh_battery_and_temperature(self, data: HardwareData) -> HardwareData:
        """Refresh slow battery and system-temperature channels."""
        updated = deepcopy(data)

        async def read(device: HardwareDevice) -> None:
            requests: list[tuple[str, str]] = [(CHANNEL_SYSTEM_TEMPERATURE, "temperature")]
            if device.is_window_handle:
                requests.extend(((CHANNEL_BATTERY, "battery"), (CHANNEL_BATTERY_LOW, "battery_low")))
            values = await asyncio.gather(
                *(self.async_read_channel(device, channel) for channel, _ in requests),
                return_exceptions=True,
            )
            for (_, attribute), value in zip(requests, values, strict=True):
                if isinstance(value, Exception):
                    continue
                if attribute == "temperature":
                    parsed = _as_float(value)
                    if parsed is not None and parsed < 120:
                        device.system_temperature = parsed
                elif attribute == "battery":
                    device.battery = _as_int(value)
                else:
                    device.battery_low = _as_bool(value)

        await asyncio.gather(*(read(device) for device in updated.devices.values()))
        return updated
