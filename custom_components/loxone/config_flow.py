"""
Config Flow for PyLoxone

For more details about this component, please refer to the documentation at
https://github.com/JoDehli/PyLoxone
"""

import asyncio
import logging
from typing import Any, Mapping

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import (CONF_HOST, CONF_PASSWORD, CONF_PORT,
                                 CONF_USERNAME)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (BooleanSelector, NumberSelector,
                                            NumberSelectorConfig,
                                            NumberSelectorMode, SelectOptionDict,
                                            SelectSelector, SelectSelectorConfig,
                                            SelectSelectorMode, TextSelector,
                                            TextSelectorConfig,
                                            TextSelectorType)

from .const import (CONF_LIGHTCONTROLLER_SUBCONTROLS_GEN, CONF_SCENE_GEN,
                    CONF_SCENE_GEN_DELAY, CONF_SENSOR_DEVICE_CLASS_MAP,
                    DEFAULT_DELAY_SCENE, DEFAULT_IP, DEFAULT_PORT, DOMAIN,
                    MAPPABLE_DEVICE_CLASSES, UNAMBIGUOUS_UNITS)
from .device_class import (_heuristic_device_class,
                           sensor_entries_from_control)
from .pyloxone_api.connection import LoxoneConnection
from .pyloxone_api.exceptions import (LoxoneException,
                                      LoxoneServiceUnAvailableError,
                                      LoxoneUnauthorisedError)

_LOGGER = logging.getLogger(__name__)


def validate_loxone_setup(user_input: dict[str, Any]) -> dict[str, Any]:
    """Validate Loxone setup."""
    # Validate latin-1 encoding for username and password
    try:
        if CONF_USERNAME in user_input:
            user_input[CONF_USERNAME].encode("latin-1")
    except UnicodeEncodeError as err:
        raise ValueError(
            "Username contains characters that are not latin-1 compatible"
        ) from err

    try:
        if CONF_PASSWORD in user_input:
            user_input[CONF_PASSWORD].encode("latin-1")
    except UnicodeEncodeError as err:
        raise ValueError(
            "Password contains characters that are not latin-1 compatible"
        ) from err

    # Ensure port is stored as int
    if CONF_PORT in user_input:
        user_input[CONF_PORT] = int(user_input[CONF_PORT])
    if CONF_SCENE_GEN_DELAY in user_input:
        user_input[CONF_SCENE_GEN_DELAY] = int(user_input[CONF_SCENE_GEN_DELAY])

    return user_input


DATA_SCHEMA_SETUP = vol.Schema(
    {
        vol.Required(CONF_USERNAME, default=""): TextSelector(
            TextSelectorConfig(type=TextSelectorType.TEXT)
        ),
        vol.Required(CONF_PASSWORD, default=""): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        ),
        vol.Required(CONF_HOST, default=DEFAULT_IP): TextSelector(
            TextSelectorConfig(type=TextSelectorType.TEXT)
        ),
        vol.Required(CONF_PORT, default=DEFAULT_PORT): NumberSelector(
            NumberSelectorConfig(mode=NumberSelectorMode.BOX, min=1, max=65535)
        ),
        vol.Required(CONF_SCENE_GEN, default=True): BooleanSelector(),
        vol.Optional(CONF_SCENE_GEN_DELAY, default=DEFAULT_DELAY_SCENE): NumberSelector(
            NumberSelectorConfig(mode=NumberSelectorMode.BOX, min=3)
        ),
        vol.Required(
            CONF_LIGHTCONTROLLER_SUBCONTROLS_GEN, default=False
        ): BooleanSelector(),
    }
)

DATA_SCHEMA_OPTIONS = vol.Schema(
    {
        vol.Required(CONF_USERNAME, default=""): TextSelector(
            TextSelectorConfig(type=TextSelectorType.TEXT)
        ),
        vol.Required(CONF_PASSWORD, default=""): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        ),
        vol.Required(CONF_HOST, default=DEFAULT_IP): TextSelector(
            TextSelectorConfig(type=TextSelectorType.TEXT)
        ),
        vol.Required(CONF_PORT, default=DEFAULT_PORT): NumberSelector(
            NumberSelectorConfig(mode=NumberSelectorMode.BOX, min=1, max=65535)
        ),
        vol.Required(CONF_SCENE_GEN, default=True): BooleanSelector(),
        vol.Optional(CONF_SCENE_GEN_DELAY, default=DEFAULT_DELAY_SCENE): NumberSelector(
            NumberSelectorConfig(mode=NumberSelectorMode.BOX, min=3)
        ),
        vol.Required(
            CONF_LIGHTCONTROLLER_SUBCONTROLS_GEN, default=False
        ): BooleanSelector(),
    }
)


def _build_device_class_schema(
    lox_config: dict, current_map: dict
) -> tuple[vol.Schema | None, dict[str, str]]:
    """Build dynamic schema for device class mapping step.

    Returns (schema, label_to_uuid) or (None, {}) if no mappable sensors exist.
    Shared by both config flow (initial setup) and options flow.
    """
    dc_options = [SelectOptionDict(value="none", label="(no device class)")]
    dc_options += [SelectOptionDict(value=v, label=lbl) for v, lbl in MAPPABLE_DEVICE_CLASSES]

    schema_fields = {}
    label_to_uuid = {}

    controls = lox_config.get("controls", {})
    for ctrl in controls.values():
        entries = sensor_entries_from_control(ctrl, lox_config)
        for uuid, name, room, unit, category in entries:
            if unit in UNAMBIGUOUS_UNITS:
                continue
            heuristic_dc = _heuristic_device_class(name, unit, category)
            has_saved = uuid in current_map
            if not heuristic_dc and not has_saved:
                continue
            default_val = current_map.get(uuid, heuristic_dc or "none")
            label = f"{name} ({room})" if room else name
            label_to_uuid[label] = uuid
            schema_fields[vol.Required(label, default=default_val)] = SelectSelector(
                SelectSelectorConfig(options=dc_options, mode=SelectSelectorMode.DROPDOWN)
            )

    if not schema_fields:
        return None, {}

    return vol.Schema(schema_fields), label_to_uuid


class LoxoneFlowHandler(ConfigFlow, domain=DOMAIN):
    """Handle Loxone config flow."""

    VERSION = 4

    def __init__(self) -> None:
        """Initialize."""
        self._user_input: dict[str, Any] = {}
        self._lox_config: dict | None = None
        self._label_to_uuid: dict[str, str] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial credentials step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                user_input = validate_loxone_setup(user_input)
            except ValueError:
                errors["base"] = "invalid_input"
            else:
                try:
                    self._lox_config = await self._test_connection(user_input)
                except LoxoneUnauthorisedError:
                    errors["base"] = "invalid_auth"
                except (LoxoneServiceUnAvailableError, TimeoutError, OSError, ConnectionError):
                    errors["base"] = "cannot_connect"
                except LoxoneException:
                    _LOGGER.exception("Unexpected Loxone error during connection test")
                    errors["base"] = "cannot_connect"
                except Exception:
                    _LOGGER.exception("Unexpected error during connection test")
                    errors["base"] = "unknown"
                else:
                    self._user_input = user_input
                    return await self.async_step_device_class_mapping()

        schema = DATA_SCHEMA_SETUP
        if user_input is not None:
            schema = self.add_suggested_values_to_schema(schema, user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )

    async def _test_connection(self, user_input: dict[str, Any]) -> dict:
        """Test connection to Loxone Miniserver and return structure file.

        Creates a short-lived connection to validate credentials and fetch
        the LoxApp3.json structure file. The connection is closed immediately after.
        """
        api = LoxoneConnection(
            host=user_input[CONF_HOST],
            port=int(user_input[CONF_PORT]),
            username=user_input[CONF_USERNAME],
            password=user_input[CONF_PASSWORD],
        )
        session = async_get_clientsession(self.hass)
        try:
            await asyncio.wait_for(api.open(session), timeout=10)
            return api.structure_file
        finally:
            await api.close()

    async def async_step_device_class_mapping(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle device class mapping step during initial setup."""
        if user_input is not None:
            mapping = {}
            for label, dc in user_input.items():
                uuid = self._label_to_uuid.get(label)
                if uuid:
                    mapping[uuid] = dc or "none"
            self._user_input[CONF_SENSOR_DEVICE_CLASS_MAP] = mapping
            return self._create_config_entry()

        schema, self._label_to_uuid = _build_device_class_schema(
            self._lox_config, {}
        )
        if schema is None:
            return self._create_config_entry()

        return self.async_show_form(
            step_id="device_class_mapping",
            data_schema=schema,
        )

    def _create_config_entry(self) -> ConfigFlowResult:
        """Create the config entry with all collected data."""
        dc_map = self._user_input.pop(CONF_SENSOR_DEVICE_CLASS_MAP, {})
        host = self._user_input.get(CONF_HOST, "Loxone")
        return self.async_create_entry(
            title=f"PyLoxone ({host})",
            data={},
            options={**self._user_input, CONF_SENSOR_DEVICE_CLASS_MAP: dc_map},
        )

    def async_config_entry_title(self, options: Mapping[str, Any]) -> str:
        """Return config entry title."""
        host = options.get(CONF_HOST, "Loxone")
        return f"PyLoxone ({host})"

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        return LoxoneOptionsFlow()


class LoxoneOptionsFlow(OptionsFlow):
    """Handle Loxone options flow."""

    def __init__(self) -> None:
        """Initialize."""
        self._label_to_uuid: dict[str, str] = {}

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the options menu."""
        return self.async_show_menu(
            step_id="init",
            menu_options=["settings", "device_class_mapping"],
        )

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the settings step."""
        if user_input is not None:
            try:
                user_input = validate_loxone_setup(user_input)
            except ValueError:
                pass  # Re-show form; latin-1 errors are rare
            else:
                # Preserve device class map when updating settings
                dc_map = self.config_entry.options.get(CONF_SENSOR_DEVICE_CLASS_MAP, {})
                new_options = {**user_input, CONF_SENSOR_DEVICE_CLASS_MAP: dc_map}
                return self.async_create_entry(data=new_options)

        schema = self.add_suggested_values_to_schema(
            DATA_SCHEMA_OPTIONS,
            self.config_entry.options,
        )
        return self.async_show_form(step_id="settings", data_schema=schema)

    async def async_step_device_class_mapping(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the device class mapping step."""
        if user_input is not None:
            current_map = dict(self.config_entry.options.get(CONF_SENSOR_DEVICE_CLASS_MAP, {}))
            for label, dc in user_input.items():
                uuid = self._label_to_uuid.get(label)
                if uuid:
                    current_map[uuid] = dc or "none"
            new_options = {**self.config_entry.options, CONF_SENSOR_DEVICE_CLASS_MAP: current_map}
            return self.async_create_entry(data=new_options)

        lox_config = self._get_lox_config()
        if lox_config is None:
            return self.async_abort(reason="no_coordinator")

        current_map = self.config_entry.options.get(CONF_SENSOR_DEVICE_CLASS_MAP, {})
        schema, self._label_to_uuid = _build_device_class_schema(lox_config, current_map)
        if schema is None:
            return self.async_abort(reason="no_mappable_sensors")

        return self.async_show_form(
            step_id="device_class_mapping",
            data_schema=schema,
        )

    def _get_lox_config(self) -> dict | None:
        """Get Loxone config from the running coordinator."""
        domain_data = self.hass.data.get(DOMAIN, {})
        coordinator = domain_data.get(self.config_entry.entry_id)
        if coordinator is None:
            return None
        ms = getattr(coordinator, "miniserver", None)
        if ms is None or ms.lox_config.json is None:
            return None
        return ms.lox_config.json
