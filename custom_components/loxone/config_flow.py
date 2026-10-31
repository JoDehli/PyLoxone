"""
Config Flow for PyLoxone

For more details about this component, please refer to the documentation at
https://github.com/JoDehli/PyLoxone
"""

from typing import Any, Mapping, cast

import voluptuous as vol
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.const import (CONF_HOST, CONF_PASSWORD, CONF_PORT,
                                 CONF_USERNAME)
from homeassistant.helpers.schema_config_entry_flow import (
    SchemaCommonFlowHandler, SchemaConfigFlowHandler, SchemaFlowError,
    SchemaFlowFormStep)
from homeassistant.helpers.selector import (BooleanSelector, NumberSelector,
                                            NumberSelectorConfig,
                                            NumberSelectorMode, TextSelector,
                                            TextSelectorConfig,
                                            TextSelectorType)

from .const import (CONF_AUDIOSERVER_HOST, CONF_AUDIOSERVER_PLAYBACK,
                    CONF_LIGHTCONTROLLER_SUBCONTROLS_GEN, CONF_SCENE_GEN,
                    CONF_SCENE_GEN_DELAY, CONF_VERIFY_SSL,
                    DEFAULT_DELAY_SCENE, DEFAULT_IP, DEFAULT_PORT,
                    DEFAULT_VERIFY_SSL, DOMAIN)
from .pyloxone_api.audioserver import audioserver_uri



async def validate_loxone_setup(
    handler: SchemaCommonFlowHandler, user_input: dict[str, Any]
) -> dict[str, Any]:
    """Validate Loxone setup."""
    # Validate latin-1 encoding for username and password
    try:
        if CONF_USERNAME in user_input:
            user_input[CONF_USERNAME].encode("latin-1")
    except UnicodeEncodeError as err:
        raise SchemaFlowError(
            "Username contains characters that are not latin-1 compatible"
        ) from err

    try:
        if CONF_PASSWORD in user_input:
            user_input[CONF_PASSWORD].encode("latin-1")
    except UnicodeEncodeError as err:
        raise SchemaFlowError(
            "Password contains characters that are not latin-1 compatible"
        ) from err

    # Ensure port is stored as int
    if CONF_PORT in user_input:
        user_input[CONF_PORT] = int(user_input[CONF_PORT])
    if CONF_SCENE_GEN_DELAY in user_input:
        user_input[CONF_SCENE_GEN_DELAY] = int(user_input[CONF_SCENE_GEN_DELAY])

    if host := user_input.get(CONF_AUDIOSERVER_HOST):
        try:
            audioserver_uri(host)
        except ValueError as err:
            message = "invalid_audioserver_host"
            raise SchemaFlowError(message) from err

    if user_input.get(CONF_AUDIOSERVER_PLAYBACK) and not user_input.get(CONF_AUDIOSERVER_HOST):
        message = "audioserver_playback_requires_host"
        raise SchemaFlowError(message)


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
        vol.Required(CONF_VERIFY_SSL, default=DEFAULT_VERIFY_SSL): BooleanSelector(),
        vol.Optional(CONF_AUDIOSERVER_HOST, default=""): TextSelector(
            TextSelectorConfig(type=TextSelectorType.TEXT)
        ),
        vol.Optional(CONF_AUDIOSERVER_PLAYBACK, default=False): BooleanSelector(),
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
        vol.Required(CONF_VERIFY_SSL, default=DEFAULT_VERIFY_SSL): BooleanSelector(),
        vol.Optional(CONF_AUDIOSERVER_HOST, default=""): TextSelector(
            TextSelectorConfig(type=TextSelectorType.TEXT)
        ),
        vol.Optional(CONF_AUDIOSERVER_PLAYBACK, default=False): BooleanSelector(),
        vol.Required(CONF_SCENE_GEN, default=True): BooleanSelector(),
        vol.Optional(CONF_SCENE_GEN_DELAY, default=DEFAULT_DELAY_SCENE): NumberSelector(
            NumberSelectorConfig(mode=NumberSelectorMode.BOX, min=3)
        ),
        vol.Required(
            CONF_LIGHTCONTROLLER_SUBCONTROLS_GEN, default=False
        ): BooleanSelector(),
    }
)

DATA_SCHEMA_REAUTH = vol.Schema(
    {
        vol.Required(CONF_USERNAME): TextSelector(
            TextSelectorConfig(type=TextSelectorType.TEXT)
        ),
        vol.Required(CONF_PASSWORD): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        ),
    }
)

# Cleared on reauth: the cached token belongs to the old credentials.
_EMPTY_TOKEN = {"token": "", "hash_alg": "", "valid_until": ""}

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

    VERSION = 4
    config_flow = CONFIG_FLOW
    options_flow = OPTIONS_FLOW

    def async_config_entry_title(self, options: Mapping[str, Any]) -> str:
        """Return config entry title."""
        host = options.get(CONF_HOST, "Loxone")
        return f"PyLoxone ({host})"

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """The Miniserver rejected the credentials (``ConfigEntryAuthFailed``)."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for new credentials and reload the entry with them."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                user_input = await validate_loxone_setup(
                    cast(SchemaCommonFlowHandler, None), dict(user_input)
                )
            except SchemaFlowError:
                errors["base"] = "invalid_credentials_encoding"
            else:
                return self.async_update_reload_and_abort(
                    entry,
                    options={**entry.options, **user_input},
                    data_updates=_EMPTY_TOKEN,
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=self.add_suggested_values_to_schema(
                DATA_SCHEMA_REAUTH,
                {CONF_USERNAME: entry.options.get(CONF_USERNAME, "")},
            ),
            errors=errors,
        )

    async def async_step_import(self, import_data: dict[str, Any]) -> ConfigFlowResult:
        """Import ``loxone:`` from configuration.yaml.

        ``async_setup`` starts this flow on every HA start, so an entry
        for the same host and port is only created once. The values are
        stored as options, like the ones entered in the UI.
        """
        for entry in self._async_current_entries():
            if entry.options.get(CONF_HOST) == import_data.get(
                CONF_HOST
            ) and entry.options.get(CONF_PORT) == import_data.get(CONF_PORT):
                return self.async_abort(reason="already_configured")
        try:
            options = await validate_loxone_setup(
                cast(SchemaCommonFlowHandler, None), dict(import_data)
            )
        except SchemaFlowError:
            return self.async_abort(reason="invalid_import")
        return self.async_create_entry(options)
