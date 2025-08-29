"""Config Flow for PyLoxone

For more details about this component, please refer to the documentation at
https://github.com/JoDehli/PyLoxone
"""

from collections import OrderedDict
import aiohttp
import logging
import voluptuous as vol

from aiohttp import BasicAuth
from homeassistant.config_entries import (
    CONN_CLASS_LOCAL_POLL,
    ConfigEntry,
    ConfigFlow,
    OptionsFlow,
)
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_USERNAME,
)
from homeassistant.core import callback

from .const import (
    CONF_LIGHTCONTROLLER_SUBCONTROLS_GEN,
    CONF_SCENE_GEN,
    CONF_SCENE_GEN_DELAY,
    DEFAULT_DELAY_SCENE,
    DEFAULT_IP,
    DEFAULT_PORT,
    DOMAIN,
    LOXAPPPATH,
)

_LOGGER = logging.getLogger(__name__)

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


class LoxoneFlowHandler(ConfigFlow, domain=DOMAIN):
    """Handle PyLoxone config flow."""

    VERSION = 3
    CONNECTION_CLASS = CONN_CLASS_LOCAL_POLL

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry):
        """Get the options flow for this handler."""
        return LoxoneOptionsFlowHandler(config_entry)

    async def async_step_user(self, user_input=None):
        """Handle a flow initialized by the user."""
        current_entries = self._async_current_entries()
        if current_entries:
            return self.async_abort(reason="single_instance_allowed")

        errors = {}

        if user_input is not None:
            host = user_input[CONF_HOST]
            port = user_input[CONF_PORT]
            username = user_input[CONF_USERNAME]
            password = user_input[CONF_PASSWORD]
            url = f"http://{host}:{port}{LOXAPPPATH}"

            auth = BasicAuth(username, password)

            try:
                async with aiohttp.ClientSession(auth=auth) as session:
                    async with session.get(url, timeout=5) as response:
                        if response.status == 200:
                            _LOGGER.info("Connection with miniserver successful at %s", url)
                            return self.async_create_entry(title="PyLoxone", data=user_input)
                        else:
                            _LOGGER.warning("Connection with miniserver failed with error %s for URL: %s", response.status, url)
                            errors["base"] = "cannot_connect"
            except Exception as e:
                _LOGGER.error("Connection test exception for URL %s: %s", url, str(e))
                errors["base"] = "cannot_connect"

        return self.async_create_entry(title="PyLoxone", data={}, options=user_input)


class LoxoneOptionsFlowHandler(OptionsFlow):
    """Handle Loxone options."""

    def __init__(self, config_entry: ConfigEntry):
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        errors = {}

        if user_input is not None:
            return self.async_create_entry(title="PyLoxone", data=user_input)

        user = self.config_entry.options.get(CONF_USERNAME, "")
        password = self.config_entry.options.get(CONF_PASSWORD, "")
        host = self.config_entry.options.get(CONF_HOST, "")
        port = self.config_entry.options.get(CONF_PORT, DEFAULT_PORT)
        gen_scenes = self.config_entry.options.get(CONF_SCENE_GEN, True)
        gen_scene_delay = self.config_entry.options.get(CONF_SCENE_GEN_DELAY, DEFAULT_DELAY_SCENE)
        gen_subcontrols = self.config_entry.options.get(CONF_LIGHTCONTROLLER_SUBCONTROLS_GEN, False)

        options = OrderedDict()
        options[vol.Required(CONF_USERNAME, default=user)] = str
        options[vol.Required(CONF_PASSWORD, default=password)] = str
        options[vol.Required(CONF_HOST, default=host)] = str
        options[vol.Required(CONF_PORT, default=port)] = int
        options[vol.Required(CONF_SCENE_GEN, default=gen_scenes)] = bool
        options[vol.Required(CONF_SCENE_GEN_DELAY, default=gen_scene_delay)] = int
        options[vol.Required(CONF_LIGHTCONTROLLER_SUBCONTROLS_GEN, default=gen_subcontrols)] = bool

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(options),
            errors=errors,
        )
