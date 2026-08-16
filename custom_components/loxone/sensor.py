"""
Loxone Sensors

For more details about this component, please refer to the documentation at
https://github.com/JoDehli/PyLoxone
"""

import json
import logging
import re
from functools import cached_property
from typing import Any

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.components.sensor import (CONF_STATE_CLASS, PLATFORM_SCHEMA,
                                             SensorDeviceClass, SensorEntity,
                                             SensorEntityDescription,
                                             SensorStateClass)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (CONF_DEVICE_CLASS, CONF_NAME,
                                 CONF_UNIT_OF_MEASUREMENT, CONF_VALUE_TEMPLATE,
                                 LIGHT_LUX, PERCENTAGE, STATE_UNKNOWN,
                                 UnitOfEnergy, UnitOfPower, UnitOfRatio,
                                 UnitOfSpeed, UnitOfTemperature, UnitOfVolume,
                                 UnitOfVolumeFlowRate)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.util import dt as dt_util

from . import LoxoneEntity, MiniServer
from .const import CLIMATE_EVENT, CONF_ACTIONID, DOMAIN, EVENT, SENDDOMAIN, THROTTLE_KEEP_ALIVE_TIME
from .helpers import (add_room_and_cat_to_value_values, clean_unit, get_all,
                      get_or_create_device)
from .miniserver import get_miniserver_from_hass

NEW_SENSOR = "sensors"

_LOGGER = logging.getLogger(__name__)

DEFAULT_NAME = "Loxone Sensor"

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_ACTIONID): cv.string,
        vol.Optional(CONF_NAME): cv.string,
        vol.Optional(CONF_UNIT_OF_MEASUREMENT): cv.string,
        vol.Optional(CONF_DEVICE_CLASS): cv.string,
        vol.Optional(CONF_STATE_CLASS): cv.string,
    }
)

OVERRIDE_REASONS = {
    0: "None",
    1: "Presence",
    2: "Window Open",
    3: "Comfort Override",
    4: "Eco Override",
    5: "Eco+ Override",
    6: "Prepare State Heat Up",
    7: "Prepare State Cool Down",
    8: "Overridden by source",
}

class LoxoneEntityDescription(SensorEntityDescription, frozen_or_thawed=True):
    """
    Describes a Loxone sensor entity.

    Acts as a classification object: carries matching criteria (which Loxone
    units/keywords trigger this description) and the resulting classification
    (device_class, state_class). Presentation details (actual unit, precision)
    come from the Loxone format string via _attr_* in __init__.
    """

    loxone_format_strings: tuple[str, ...]
    category_keywords: tuple[str, ...] = ()
    name_keywords: tuple[str, ...] = ()


SENSOR_TYPES: tuple[LoxoneEntityDescription, ...] = (
    LoxoneEntityDescription(
        key="temperature",
        loxone_format_strings=(UnitOfTemperature.CELSIUS, UnitOfTemperature.FAHRENHEIT),
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.TEMPERATURE,
    ),
    LoxoneEntityDescription(
        key="wind_speed",
        loxone_format_strings=(UnitOfSpeed.KILOMETERS_PER_HOUR,),
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.WIND_SPEED,
    ),
    LoxoneEntityDescription(
        key="energy",
        loxone_format_strings=(
            UnitOfEnergy.KILO_WATT_HOUR,
            UnitOfEnergy.WATT_HOUR,
            UnitOfEnergy.MEGA_WATT_HOUR,
        ),
        state_class=SensorStateClass.TOTAL_INCREASING,
        device_class=SensorDeviceClass.ENERGY,
    ),
    LoxoneEntityDescription(
        key="power",
        loxone_format_strings=(UnitOfPower.WATT, UnitOfPower.KILO_WATT),
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.POWER,
    ),
    LoxoneEntityDescription(
        key="volume_flow_rate",
        loxone_format_strings=(
            UnitOfVolumeFlowRate.LITERS_PER_HOUR,
            UnitOfVolumeFlowRate.LITERS_PER_MINUTE,
        ),
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.VOLUME_FLOW_RATE,
    ),
    LoxoneEntityDescription(
        key="water",
        loxone_format_strings=(UnitOfVolume.LITERS,),
        state_class=SensorStateClass.TOTAL_INCREASING,
        device_class=SensorDeviceClass.WATER,
    ),
    LoxoneEntityDescription(
        key="illuminance",
        loxone_format_strings=(LIGHT_LUX, "Lx", "lx", "lux"),
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.ILLUMINANCE,
    ),
    LoxoneEntityDescription(
        key="carbon_dioxide",
        loxone_format_strings=(UnitOfRatio.PARTS_PER_MILLION,),
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.CO2,
    ),
    LoxoneEntityDescription(
        key="humidity",
        loxone_format_strings=(PERCENTAGE,),
        category_keywords=("vlhkost", "humidity", "feucht", "humidité"),
        name_keywords=("vlhkost", "humidity", "feucht", "humidité"),
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.HUMIDITY,
    ),
    LoxoneEntityDescription(
        key="battery",
        loxone_format_strings=(PERCENTAGE,),
        name_keywords=("batt", "akku", "battery"),
        state_class=SensorStateClass.MEASUREMENT,
        device_class=SensorDeviceClass.BATTERY,
    ),
)

UNAMBIGUOUS_UNITS: frozenset[str] = frozenset(
    u
    for desc in SENSOR_TYPES
    if not desc.category_keywords and not desc.name_keywords
    for u in desc.loxone_format_strings
)
"""Units that map to exactly one device class without needing keyword disambiguation."""

def match_sensor_description(
    unit: str,
    name: str = "",
    category: str = "",
) -> LoxoneEntityDescription | None:
    """
    Find the first matching sensor description for a Loxone sensor.

    Unambiguous units (°C, kWh, ppm, …) match immediately.
    Ambiguous units (%) require a keyword hit in name or category.
    Returns None if no description matches.
    """
    name_lower = name.lower()
    cat_lower = category.lower()
    for desc in SENSOR_TYPES:
        if unit not in desc.loxone_format_strings:
            continue
        if not desc.category_keywords and not desc.name_keywords:
            return desc
        cat_match = any(kw in cat_lower for kw in desc.category_keywords)
        name_match = any(kw in name_lower for kw in desc.name_keywords)
        if cat_match or name_match:
            return desc
    return None


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_devices: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
) -> None:
    """Set up Loxone Sensor from yaml"""
    value_template = config.get(CONF_VALUE_TEMPLATE)
    if value_template is not None:
        value_template.hass = hass

    # Devices from yaml
    if config:
        # Setup all Sensors in Yaml-File
        new_sensor = LoxoneCustomSensor(**config)
        async_add_devices([new_sensor], update_before_add=True)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up entry."""
    miniserver = get_miniserver_from_hass(hass, config_entry)

    loxconfig = miniserver.lox_config.json
    entities: list[Any] = [LoxoneKeepAliveSensor(miniserver.serial)]

    if "softwareVersion" in loxconfig:
        entities.append(LoxoneVersionSensor(miniserver.serial, loxconfig["softwareVersion"]))

    for sensor in get_all(loxconfig, "InfoOnlyAnalog"):
        sensor = add_room_and_cat_to_value_values(loxconfig, sensor)
        sensor.update({"type": "analog"})
        entities.append(LoxoneSensor(**sensor))

    for sensor in get_all(loxconfig, "TextInput"):
        sensor = add_room_and_cat_to_value_values(loxconfig, sensor)
        entities.append(LoxoneTextSensor(**sensor))

    for sensor in get_all(loxconfig, "Meter"):
        _LOGGER.info("Found Meter: %s", sensor)
        sensor = add_room_and_cat_to_value_values(loxconfig, sensor)
        device_info = LoxoneMeterSensor.create_device_info_from_sensor(sensor)

        for state_key, name_suffix, format_key in [
            ("actual", "Actual", "actualFormat"),
            ("total", "Total", "totalFormat"),
            ("totalNeg", "Total Neg", "totalFormat"),
            ("storage", "Level", "storageFormat"),
        ]:
            if state_key in sensor["states"]:
                subsensor = {
                    "device_info": device_info,
                    "parent_id": sensor["uuidAction"],
                    "uuidAction": sensor["states"][state_key],
                    "type": "analog",
                    "room": sensor.get("room", ""),
                    "cat": sensor.get("cat", ""),
                    "name": f"{sensor['name']} {name_suffix}",
                    "details": {"format": sensor["details"][format_key]},
                    "async_add_devices": async_add_entities,
                    "config_entry": config_entry,
                }
                entities.append(LoxoneMeterSensor(**subsensor))

    # Climate controller demand sensors
    for ctrl_type in ("ClimateController", "ClimateControllerUS"):
        for ctrl in get_all(loxconfig, ctrl_type):
            ctrl = add_room_and_cat_to_value_values(loxconfig, ctrl)
            ctrl_kwargs = {**ctrl, "type": "climate_controller", "hass": hass}
            entities.append(LoxoneClimateController(**ctrl_kwargs))

    # IRoomControllerV2 sub-sensors: override reason + comfort temperatures
    for irc in get_all(loxconfig, "IRoomControllerV2"):
        irc = add_room_and_cat_to_value_values(loxconfig, irc)
        states = irc.get("states", {})
        device_info = get_or_create_device(
            irc["uuidAction"], irc["name"], "RoomControllerV2", irc.get("room", "")
        )

        if "overrideReason" in states:
            entities.append(LoxoneRoomControllerOverrideSensor(
                name=f"{irc['name']} Override Reason",
                uuid=states["overrideReason"],
                device_info=device_info,
                parent_uuid=irc["uuidAction"],
            ))

        if "comfortTemperature" in states:
            entities.append(LoxoneRoomControllerTemperatureSensor(
                name=f"{irc['name']} Comfort Temperature",
                uuid=states["comfortTemperature"],
                device_info=device_info,
                parent_uuid=irc["uuidAction"],
            ))

        if "comfortTemperatureCool" in states:
            entities.append(LoxoneRoomControllerTemperatureSensor(
                name=f"{irc['name']} Comfort Temperature Cool",
                uuid=states["comfortTemperatureCool"],
                device_info=device_info,
                parent_uuid=irc["uuidAction"],
            ))

    @callback
    def async_add_sensors(_):
        async_add_entities(_, True)

    miniserver.listeners.append(
        async_dispatcher_connect(hass, miniserver.async_signal_new_device(NEW_SENSOR), async_add_sensors)
    )

    async_add_entities(entities, update_before_add=True)


class LoxoneCustomSensor(LoxoneEntity, SensorEntity):
    def __init__(self, **kwargs):
        self._attr_name = kwargs.pop("name", None)
        self._attr_state_class = kwargs.pop("state_class", None)
        self._attr_device_class = kwargs.pop("device_class", None)
        self._attr_native_unit_of_measurement = kwargs.pop("unit_of_measurement", None)
        self._attr_native_value = None  # Initialize state
        # Must be after the kwargs.pop functions!
        super().__init__(**kwargs)

    @cached_property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return self.uuidAction + self._attr_name

    async def event_handler(self, e):
        if self.uuidAction in e.data:
            data = e.data[self.uuidAction]
            if isinstance(data, (list, dict)):
                data = str(data)
                if len(data) >= 255:
                    self._attr_native_value = data[:255]
                else:
                    self._attr_native_value = data
            else:
                self._attr_native_value = data

            self.async_schedule_update_ha_state()

    @property
    def native_unit_of_measurement(self):
        """Return the unit of measurement of this entity, if any."""
        if self._attr_native_unit_of_measurement in ["None", "none", "-"]:
            return None
        return self._attr_native_unit_of_measurement

    @property
    def extra_state_attributes(self):
        """Return device specific state attributes."""
        return {**self._attr_extra_state_attributes}


class LoxoneKeepAliveSensor(LoxoneEntity, SensorEntity):
    _attr_name = "Loxone Last Keep Alive Message"
    _attr_icon = "mdi:information-outline"
    _attr_unique_id = "loxone_keep_alive_sensor_uuid"
    _attr_device_class = SensorDeviceClass.TIMESTAMP  # tell HA this is a timestamp

    def __init__(self, miniserver_serial, **kwargs):
        super().__init__(**kwargs)
        self._miniserver_serial = miniserver_serial
        self._attr_native_value = None

    @cached_property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"{self._miniserver_serial}-{self._attr_unique_id}"

    async def event_handler(self, e):
        if "keep_alive" in e.data and e.data["keep_alive"] == "received":
            now = dt_util.utcnow()
            # only update if at least 60 seconds passed since last update
            if self._attr_native_value is not None:
                time_since_last = (now - self._attr_native_value).total_seconds()
                if time_since_last < THROTTLE_KEEP_ALIVE_TIME:
                    # too soon, skip this update
                    return

            # update the timestamp
            self._attr_native_value = now
            self.async_schedule_update_ha_state()

    @property
    def extra_state_attributes(self):
        """Return device specific state attributes."""
        return {**self._attr_extra_state_attributes}


class LoxoneVersionSensor(LoxoneEntity, SensorEntity):
    _attr_should_poll = False
    _attr_name = "Loxone Software Version"
    _attr_icon = "mdi:information-outline"
    _attr_unique_id = "loxone_software_version_uuid"

    def __init__(self, minisersver_serial, version_list, **kwargs):
        super().__init__(**kwargs)
        self._miniserver_serial = minisersver_serial
        try:
            self._attr_native_value = ".".join([str(x) for x in version_list])
        except Exception:
            self._attr_native_value = STATE_UNKNOWN

    @cached_property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"{self._miniserver_serial}-{self._attr_unique_id}"


class LoxoneTextSensor(LoxoneEntity, SensorEntity):
    """Representation of a Text Sensor."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._state = STATE_UNKNOWN

    async def event_handler(self, e):
        if self.states["text"] in e.data:
            self._state = str(e.data[self.states["text"]])
            self.async_schedule_update_ha_state()

    @property
    def device_class(self):
        """Return the class of this device, from component DEVICE_CLASSES."""
        return self.type

    @property
    def native_value(self):
        """Return the state of the sensor."""
        return self._state

    async def async_set_value(self, value):
        """Set new value."""
        self.hass.bus.async_fire(
            SENDDOMAIN, dict(uuid=self.uuidAction, value=f"{value}")
        )
        self.async_schedule_update_ha_state()

    @property
    def extra_state_attributes(self):
        """Return device specific state attributes."""
        return {
            **self._attr_extra_state_attributes,
            "device_type": self.type,
        }


class LoxoneSensor(LoxoneEntity, SensorEntity):
    """Representation of a Loxone Sensor."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._format = self._get_format(self.details["format"])
        self._attr_should_poll = False
        self._attr_native_unit_of_measurement = clean_unit(self.details["format"])
        self._parent_id = kwargs.get("parent_id")

        precision = self._parse_digits_after_decimal(self.details["format"])
        if precision:
            self._attr_suggested_display_precision = precision

        # Device class is detected automatically from unit/category/name.
        # To override for a specific entity, use HA's customize in configuration.yaml:
        #   homeassistant:
        #     customize:
        #       sensor.my_sensor:
        #         device_class: battery
        desc = match_sensor_description(
            unit=self._attr_native_unit_of_measurement,
            name=self.name,
            category=kwargs.get("cat", ""),
        )
        if desc:
            self.entity_description = desc
        else:
            self._attr_state_class = SensorStateClass.MEASUREMENT

        _uuid = self.unique_id
        if self._parent_id:
            _uuid = self._parent_id

        self.type = "Sensor analog"
        self._attr_device_info = get_or_create_device(
            _uuid, self.name, self.type, self.room
        )

    def _parse_digits_after_decimal(self, format_string):
        """Parse digits after the decimal point from the format string."""
        pattern = r"\.(\d+)"
        match = re.search(pattern, format_string)
        if match:
            digits = int(match.group(1))
            return digits
        return None

    @property
    def available(self) -> bool:
        """Return entity availability."""
        return self.state is not None

    def _get_lox_rounded_value(self, value):
        try:
            return float(self._format % float(value))
        except ValueError:
            return value

    async def event_handler(self, e):
        if self.uuidAction in e.data:
            self._attr_native_value = e.data[self.uuidAction]
            self.async_schedule_update_ha_state()

    @property
    def extra_state_attributes(self):
        """Return device specific state attributes."""
        return {
            **self._attr_extra_state_attributes,
            "device_type": self.type + "_sensor",
        }


class LoxoneMeterSensor(LoxoneSensor, SensorEntity):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        device_info = kwargs.get("device_info")
        if device_info:
            self._attr_device_info = device_info

    @staticmethod
    def create_device_info_from_sensor(sensor) -> DeviceInfo:
        try:
            # For legacy Meter
            model = sensor["details"]["type"].capitalize() + " Meter"
        except (KeyError, TypeError):
            model = "Meter"
        return DeviceInfo(
            identifiers={(DOMAIN, sensor["uuidAction"])},
            name=sensor["name"],
            manufacturer="Loxone",
            model=model,
        )

class LoxoneRoomControllerTemperatureSensor(SensorEntity):
    """Sensor for IRoomControllerV2 comfort temperature states."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, name: str, uuid: str, device_info: DeviceInfo, parent_uuid: str):
        self._attr_name = name
        self._uuid = uuid
        self._attr_unique_id = uuid
        self._attr_device_info = device_info
        self._attr_native_value = None
        self._parent_uuid = parent_uuid

    async def async_added_to_hass(self):
        """Subscribe to Loxone events."""
        self.async_on_remove(
            self.hass.bus.async_listen(EVENT, self.event_handler)
        )

    async def event_handler(self, e):
        if self._uuid in e.data:
            self._attr_native_value = e.data[self._uuid]
            self.async_schedule_update_ha_state()

class LoxoneRoomControllerOverrideSensor(SensorEntity):
    """Sensor for IRoomControllerV2 override reason."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, name: str, uuid: str, device_info: DeviceInfo, parent_uuid: str):
        self._attr_name = name
        self._uuid = uuid
        self._attr_unique_id = uuid
        self._attr_device_info = device_info
        self._attr_native_value = "None"
        self._attr_options = list(OVERRIDE_REASONS.values())
        self._parent_uuid = parent_uuid

    async def async_added_to_hass(self):
        """Subscribe to Loxone events."""
        self.async_on_remove(
            self.hass.bus.async_listen(EVENT, self.event_handler)
        )

    async def event_handler(self, e):
        if self._uuid in e.data:
            reason_code = int(e.data[self._uuid])
            self._attr_native_value = OVERRIDE_REASONS.get(reason_code, f"Unknown ({reason_code})")
            self.async_schedule_update_ha_state()

class LoxoneClimateController(LoxoneEntity, SensorEntity):
    """Climate controller sensor that fires demand events for IRoomControllerV2.

    Reads the control list from the ClimateController's state and fires
    CLIMATE_EVENT for each linked room controller with the current demand
    (1 = heating, -1 = cooling, 0 = idle).
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.hass = kwargs["hass"]
        self._stateAttribUuids = kwargs.get("states", {})
        self._stateAttribValues = {}
        self._heat_demand = 0
        self._cool_demand = 0
        self.type = "ClimateController"

        self._attr_device_info = get_or_create_device(
            self.unique_id, self.name, self.type, self.room
        )

    async def event_handler(self, e):
        update = False

        for key in set(self._stateAttribUuids.values()) & e.data.keys():
            raw = e.data[key]
            # Parse JSON control lists from the Miniserver
            if isinstance(raw, str) and raw.startswith("["):
                try:
                    parsed = json.loads(raw)
                    self._stateAttribValues[key] = parsed
                    # Fire demand events for each control in the list
                    heat_count = 0
                    cool_count = 0
                    for control in parsed:
                        demand = control.get("demand", 0)
                        if demand == 1:
                            heat_count += 1
                        elif demand == -1:
                            cool_count += 1
                        self.hass.bus.async_fire(
                            CLIMATE_EVENT,
                            {"uuid": control["uuid"], "value": demand},
                        )
                    self._heat_demand = heat_count
                    self._cool_demand = cool_count
                except (json.JSONDecodeError, TypeError, KeyError) as err:
                    _LOGGER.debug("ClimateController JSON parse error: %s", err)
            else:
                self._stateAttribValues[key] = raw
            update = True

        if update:
            self.schedule_update_ha_state()

    @property
    def native_value(self):
        """Return summary state."""
        if self._heat_demand > 0:
            return f"Heating ({self._heat_demand})"
        if self._cool_demand > 0:
            return f"Cooling ({self._cool_demand})"
        return "Idle"

    @property
    def extra_state_attributes(self):
        """Return detailed demand attributes."""
        return {
            **self._attr_extra_state_attributes,
            "heat_demand": self._heat_demand,
            "cool_demand": self._cool_demand,
            "device_type": self.type,
        }