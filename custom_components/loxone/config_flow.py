"""
Config Flow for PyLoxone

For more details about this component, please refer to the documentation at
https://github.com/JoDehli/PyLoxone
"""

from collections import OrderedDict

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import (CONF_HOST, CONF_PASSWORD, CONF_PORT,
                                 CONF_USERNAME)
from homeassistant.core import callback

from .const import (CONF_LIGHTCONTROLLER_SUBCONTROLS_GEN, CONF_SCENE_GEN,
                    CONF_SCENE_GEN_DELAY, DEFAULT_DELAY_SCENE, DEFAULT_IP,
                    DEFAULT_PORT, DOMAIN)

LOXONE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME, default=""): str,
        vol.Required(CONF_PASSWORD, default=""): str,
        vol.Required(CONF_HOST, default=DEFAULT_IP): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
        vol.Required(CONF_SCENE_GEN, default=True): bool,
        vol.Optional(CONF_SCENE_GEN_DELAY, default=DEFAULT_DELAY_SCENE): int,
        vol.Required(CONF_LIGHTCONTROLLER_SUBCONTROLS_GEN, default=False): bool,
    }
)


class LoxoneFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle Pyloxone handle."""

    VERSION = 3
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_POLL

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        return LoxoneOptionsFlowHandler(config_entry)

    async def async_step_user(self, user_input=None):
        """Handle a flow initialized by the user."""
        current_entries = self._async_current_entries()
        if current_entries:
            return self.async_abort(reason="single_instance_allowed")

        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=LOXONE_SCHEMA)

        return self.async_create_entry(title="PyLoxone", data={}, options=user_input)

    async def async_step_import(self, import_config):
        return await self.async_step_user(user_input=import_config)


class LoxoneOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle Loxone options."""

    def __init__(self, config_entry):
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        errors = {}

        if user_input is not None:
            res = self.async_create_entry(title="Pyloxone", data=user_input)
            return res

        user = self.config_entry.options.get(CONF_USERNAME, "")
        password = self.config_entry.options.get(CONF_PASSWORD, "")
        host = self.config_entry.options.get(CONF_HOST, "")
        port = self.config_entry.options.get(CONF_PORT, 80)
        gen_scenes = self.config_entry.options.get(CONF_SCENE_GEN, True)
        gen_scene_delay = self.config_entry.options.get(
            CONF_SCENE_GEN_DELAY, DEFAULT_DELAY_SCENE
        )
        gen_subcontrols = self.config_entry.options.get(
            CONF_LIGHTCONTROLLER_SUBCONTROLS_GEN, False
        )

        options = OrderedDict()

        options[vol.Required(CONF_USERNAME, default=user)] = str
        options[vol.Required(CONF_PASSWORD, default=password)] = str
        options[vol.Required(CONF_HOST, default=host)] = str
        options[vol.Required(CONF_PORT, default=port)] = int
        options[vol.Required(CONF_SCENE_GEN, default=gen_scenes)] = bool
        options[vol.Required(CONF_SCENE_GEN_DELAY, default=gen_scene_delay)] = int
        options[
            vol.Required(CONF_LIGHTCONTROLLER_SUBCONTROLS_GEN, default=gen_subcontrols)
        ] = bool

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(options),
            errors=errors,
        )
