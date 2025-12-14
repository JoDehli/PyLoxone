"""
Config Flow for PyLoxone

For more details about this component, please refer to the documentation at
https://github.com/JoDehli/PyLoxone
"""

from typing import Any, Mapping, cast

import voluptuous as vol
from homeassistant.const import (CONF_HOST, CONF_PASSWORD, CONF_PORT,
                                 CONF_USERNAME)
from homeassistant.helpers.schema_config_entry_flow import (
    SchemaCommonFlowHandler,
    SchemaConfigFlowHandler,
    SchemaFlowError,
    SchemaFlowFormStep,
)
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (CONF_LIGHTCONTROLLER_SUBCONTROLS_GEN, CONF_SCENE_GEN,
                    CONF_SCENE_GEN_DELAY, DEFAULT_DELAY_SCENE, DEFAULT_IP,
                    DEFAULT_PORT, DOMAIN)

async def validate_loxone_setup(
    handler: SchemaCommonFlowHandler, user_input: dict[str, Any]
) -> dict[str, Any]:
    """Validate Loxone setup."""
    # Validate latin-1 encoding for username and password
    try:
        if CONF_USERNAME in user_input:
            user_input[CONF_USERNAME].encode("latin-1")
    except UnicodeEncodeError as err:
        raise SchemaFlowError("Username contains characters that are not latin-1 compatible") from err

    try:
        if CONF_PASSWORD in user_input:
            user_input[CONF_PASSWORD].encode("latin-1")
    except UnicodeEncodeError as err:
        raise SchemaFlowError("Password contains characters that are not latin-1 compatible") from err
    
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
        vol.Required(CONF_LIGHTCONTROLLER_SUBCONTROLS_GEN, default=False): BooleanSelector(),
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
        vol.Required(CONF_LIGHTCONTROLLER_SUBCONTROLS_GEN, default=False): BooleanSelector(),
    }
)

CONFIG_FLOW = {
    "user": SchemaFlowFormStep(
        schema=DATA_SCHEMA_SETUP,
        validate_user_input=validate_loxone_setup,
    ),
}

OPTIONS_FLOW = {
    "init": SchemaFlowFormStep(
        schema=DATA_SCHEMA_OPTIONS,
        validate_user_input=validate_loxone_setup,
    ),
}


class LoxoneFlowHandler(SchemaConfigFlowHandler, domain=DOMAIN):
    """Handle Loxone config flow."""

    VERSION = 3
    config_flow = CONFIG_FLOW
    options_flow = OPTIONS_FLOW

    def async_config_entry_title(self, options: Mapping[str, Any]) -> str:
        """Return config entry title."""
        host = options.get(CONF_HOST, "Loxone")
        return f"PyLoxone ({host})"
