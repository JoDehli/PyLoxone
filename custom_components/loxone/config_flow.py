"""Config Flow for Advantage Air integration."""
import voluptuous as vol
from collections import OrderedDict

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT, CONF_USERNAME, CONF_PASSWORD

from homeassistant.core import callback

DOMAIN = 'loxone'

LOXONE_DEFAULT_PORT = 8080
LOXONE_DEFAULT_IP = ""
CONF_SCENE_GEN = "generate_scenes"

LOXONE_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME, default=""): str,
        vol.Required(CONF_PASSWORD, default=""): str,
        vol.Required(CONF_HOST, default=LOXONE_DEFAULT_IP): str,
        vol.Required(CONF_PORT, default=LOXONE_DEFAULT_PORT): int,
        vol.Required(CONF_SCENE_GEN, default=True): bool,
    }
)


class LoxoneFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle Pyloxone handle."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_POLL

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        return LoxoneOptionsFlowHandler(config_entry)

    async def async_step_user(self, user_input=None):
        """Handle a flow initialized by the user."""
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=LOXONE_SCHEMA)

        return self.async_create_entry(title="PyLoxone", data=user_input)

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
            return self.async_create_entry(title="Pyloxone", data=user_input)

        user = self.config_entry.options.get(CONF_USERNAME, "")
        password = self.config_entry.options.get(CONF_PASSWORD, "")
        host = self.config_entry.options.get(CONF_HOST, "")
        port = self.config_entry.options.get(CONF_PORT, 80)
        gen_scenes = self.config_entry.options.get(CONF_SCENE_GEN, True)

        options = OrderedDict()

        options[vol.Required(CONF_USERNAME, default=user)] = str
        options[vol.Required(CONF_PASSWORD, default=password)] = str
        options[vol.Required(CONF_HOST, default=host)] = str
        options[vol.Required(CONF_PORT, default=port)] = int
        options[vol.Required(CONF_SCENE_GEN, default=gen_scenes)] = bool

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(options),
            errors=errors,
        )
