"""
Component to create an interface to the Loxone Miniserver.

For more details about this component, please refer to the documentation at
https://github.com/JoDehli/PyLoxone
"""

import asyncio
import logging
import re
import sys
import traceback
from functools import cached_property, partial

import homeassistant.components.group as group
import voluptuous as vol
import websockets
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (CONF_HOST, CONF_PASSWORD, CONF_PORT,
                                 CONF_USERNAME, EVENT_COMPONENT_LOADED,
                                 EVENT_HOMEASSISTANT_STARTED,
                                 EVENT_HOMEASSISTANT_STOP, Platform)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceEntry
from homeassistant.helpers.discovery import async_load_platform
from homeassistant.helpers.entity import Entity
from homeassistant.setup import async_setup_component

from .const import (ATTR_AREA_CREATE, ATTR_CODE, ATTR_COMMAND, ATTR_DEVICE,
                    ATTR_UUID, ATTR_VALUE,
                    CONF_LIGHTCONTROLLER_SUBCONTROLS_GEN, CONF_SCENE_GEN,
                    CONF_SCENE_GEN_DELAY, CONF_VERIFY_SSL, DEFAULT,
                    DEFAULT_DELAY_SCENE, DEFAULT_PORT, DEFAULT_VERIFY_SSL,
                    DOMAIN, DOMAIN_DEVICES, ERROR_VALUE, EVENT, LOXONE_PLATFORMS,
                    SECUREDSENDDOMAIN, SENDDOMAIN, SERVICE_REFRESH_TOKEN, cfmt)
from .coordinator import LoxoneCoordinator
from .helpers import get_miniserver_type
from .miniserver import MiniServer, get_miniserver_from_hass
from .pyloxone_api.connection import LoxoneConnection
from .pyloxone_api.exceptions import (LoxoneAuthEscalatedError,
                                      LoxoneConnectionClosedOk,
                                      LoxoneConnectionError, LoxoneException,
                                      LoxoneOutOfServiceException,
                                      LoxoneServiceUnAvailableError,
                                      LoxoneTokenError,
                                      LoxoneUnauthorisedError)

REQUIREMENTS = ["websockets", "pycryptodome", "numpy"]

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Required(CONF_USERNAME): cv.string,
                vol.Required(CONF_PASSWORD): cv.string,
                vol.Required(CONF_HOST): cv.string,
                vol.Optional(CONF_PORT, default=DEFAULT_PORT): cv.port,
                vol.Optional(
                    CONF_VERIFY_SSL, default=DEFAULT_VERIFY_SSL
                ): cv.boolean,
                vol.Optional(CONF_SCENE_GEN, default=True): cv.boolean,
                vol.Optional(
                    CONF_SCENE_GEN_DELAY, default=DEFAULT_DELAY_SCENE
                ): cv.positive_int,
                vol.Required(CONF_LIGHTCONTROLLER_SUBCONTROLS_GEN, default=False): bool,
            }
        ),
    },
    extra=vol.ALLOW_EXTRA,
)

_UNDEF: dict = {}

# TODO: get version and check for updates https://update.loxone.com/updatecheck.xml?serial=xxxxxxxxx


async def _async_handle_refresh_token(hass: HomeAssistant, call) -> None:
    """Refresh the token for exactly the selected Loxone entry."""
    entry_id = call.data.get("config_entry_id")
    coordinator = hass.data.get(DOMAIN, {}).get(entry_id)
    config_entry = getattr(coordinator, "config_entry", None)
    if (
        coordinator is None
        or config_entry is None
        or config_entry.entry_id != entry_id
        or config_entry.domain != DOMAIN
        or coordinator.api is None
    ):
        raise HomeAssistantError(
            "The selected Loxone config entry is not loaded"
        )

    try:
        await coordinator.api.async_refresh_token()
    except Exception as err:
        raise HomeAssistantError(
            f"Token refresh failed for '{config_entry.title}': {err}"
        ) from err


async def async_remove_entry(hass, config_entry) -> None:
    """Invalidate the Loxone token when the entry is removed for good.

    Runs *after* ``async_unload_entry``, so the websocket is usually
    already closed and ``kill_token`` becomes a no-op — the token then
    simply expires on the Miniserver. A kill is attempted while the
    connection is still open (e.g. a removal triggered from a
    config-flow retry while the entry is loaded).
    """
    coordinator = None
    for co in getattr(hass.data.get(DOMAIN, {}), "values", lambda: [])():
        if (
            hasattr(co, "config_entry")
            and co.config_entry.entry_id == config_entry.entry_id
        ):
            coordinator = co
            break

    if coordinator is None or getattr(coordinator, "api", None) is None:
        return

    try:
        if coordinator.api.is_connected:
            await coordinator.api.kill_token()
        else:
            _LOGGER.debug(
                "Token not invalidated: connection already closed. "
                "The token expires on its own."
            )
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("kill_token on entry removal failed: %s", err)


async def async_unload_entry(hass, config_entry):
    """Completely unloads the Loxone integration and closes all connections."""
    # Get the Miniserver instance from hass.data
    coordinator = None
    for co in getattr(hass.data.get(DOMAIN, {}), "values", lambda: [])():
        if (
            hasattr(co, "config_entry")
            and co.config_entry.entry_id == config_entry.entry_id
        ):
            coordinator = co
            break

    # Connection close
    if coordinator is not None:
        try:
            await coordinator.async_cleanup()
        except Exception as e:
            _LOGGER.warning("Error closing connection: %s", e)

            # Cancel and await the stored listening task (if any)
        try:
            task = getattr(coordinator, "_listening_task", None)
            if task is not None and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    _LOGGER.debug(f"Error waiting for listening task to finish: {e}")

            # Remove event listeners (if any still present)
            if hasattr(coordinator, "listeners") and coordinator.listeners:
                for listener in coordinator.listeners:
                    try:
                        listener()  # Unsubscribe the listener
                    except Exception:
                        pass
                coordinator.listeners = []

            hass.data[DOMAIN].pop(config_entry.entry_id, None)
        except Exception as e:
            raise e

    # Services deregistrieren beim Entladen
    hass.services.async_remove(DOMAIN, "event_websocket_command")
    hass.services.async_remove(DOMAIN, "event_secured_websocket_command")
    hass.services.async_remove(DOMAIN, "sync_areas")
    hass.services.async_remove(DOMAIN, "quick_shade")
    hass.services.async_remove(DOMAIN, "enable_sun_automation")
    hass.services.async_remove(DOMAIN, "disable_sun_automation")
    hass.services.async_remove(DOMAIN, "reload")

    # Unload
    unload_ok = await hass.config_entries.async_unload_platforms(
        config_entry, LOXONE_PLATFORMS
    )
    return unload_ok


async def async_setup(hass, config):
    """Set up integration-wide services and optional YAML import."""
    hass.data.setdefault(DOMAIN, {})
    service_schema = vol.Schema(
        {
            vol.Required("config_entry_id"): cv.string,
        }
    )
    if not hass.services.has_service(DOMAIN, SERVICE_REFRESH_TOKEN):
        hass.services.async_register(
            DOMAIN,
            SERVICE_REFRESH_TOKEN,
            partial(_async_handle_refresh_token, hass),
            schema=service_schema,
        )

    if DOMAIN in config:
        hass.async_create_task(
            hass.config_entries.flow.async_init(
                DOMAIN, context={"source": "import"}, data=config[DOMAIN]
            )
        )
    return True


async def async_migrate_entry(hass, config_entry):
    """Migrate a config entry using Home Assistant's supported update API."""
    old_version = config_entry.version
    version = old_version
    options = dict(config_entry.options)

    if version == 1:
        options[CONF_LIGHTCONTROLLER_SUBCONTROLS_GEN] = True
        version = 2
        _LOGGER.info("Migration to version %s successful", 2)

    if version == 2:
        options[CONF_SCENE_GEN_DELAY] = DEFAULT_DELAY_SCENE
        version = 3
        _LOGGER.info("Migration to version %s successful", 3)

    if version == 3:
        options[CONF_VERIFY_SSL] = DEFAULT_VERIFY_SSL
        version = 4
        _LOGGER.info("Migration to version %s successful", 4)

    if version != old_version:
        hass.config_entries.async_update_entry(
            config_entry, options=options, version=version
        )
    return True


async def async_set_options(hass, config_entry):
    options_in = {**config_entry.options}
    options = {
        CONF_HOST: options_in.pop(CONF_HOST, ""),
        CONF_PORT: options_in.pop(CONF_PORT, DEFAULT_PORT),
        CONF_USERNAME: options_in.pop(CONF_USERNAME, ""),
        CONF_PASSWORD: options_in.pop(CONF_PASSWORD, ""),
        CONF_VERIFY_SSL: options_in.pop(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL),
        CONF_SCENE_GEN: options_in.pop(CONF_SCENE_GEN, ""),
        CONF_SCENE_GEN_DELAY: options_in.pop(CONF_SCENE_GEN_DELAY, DEFAULT_DELAY_SCENE),
        CONF_LIGHTCONTROLLER_SUBCONTROLS_GEN: options_in.pop(
            CONF_LIGHTCONTROLLER_SUBCONTROLS_GEN, ""
        ),
    }
    hass.config_entries.async_update_entry(
        config_entry, data=config_entry.data, options=options
    )


async def async_config_entry_updated(hass, entry) -> None:
    """Handle signals of config entry being updated.

    This is a static method because a class method (bound method), can not be used with weak references.
    Causes for this is either discovery updating host address or config entry options changing.
    """
    pass


async def create_group_for_loxone_entities(hass, entities, name, object_id):
    try:
        await group.Group.async_create_group(
            hass,
            name,
            created_by_service=False,
            entity_ids=entities,
            icon=None,
            mode=None,
            object_id=object_id,
            order=None,
        )
    except HomeAssistantError as err:
        await group.Group.async_create_group(
            hass,
            name,
            created_by_service=True,
            entity_ids=entities,
            icon=None,
            mode=None,
            object_id=object_id,
            order=None,
        )
        _LOGGER.error("Can't create group '%s' with error: %s", name, err)
    except Exception as e:
        _LOGGER.error(
            "Can't create group '%s'. Try to make at least one group manually. ("
            "https://www.home-assistant.io/integrations/group/)",
            e,
        )


async def async_refresh_on_connection_state(
    hass, config_entry, coordinator, state
):
    """Update entity availability on connection-state transitions.

    Called by :meth:`LoxoneConnection.run` whenever the supervisor
    changes state: ``"connected"`` (websocket established),
    ``"disconnected"`` (recoverable error, reconnect scheduled) or
    ``"failed"`` (hard auth failure — the entry will be reloaded).

    While the connection is down the entities report themselves
    unavailable; the fresh values arriving after the reconnect
    restore them. UA refresh is triggered explicitly, otherwise
    the change would only be written with the next value update.
    """
    coordinator.connection_available = state == "connected"
    _LOGGER.debug("Loxone connection state: %s", state)
    try:
        from homeassistant.helpers.entity_component import (
            async_update_entity,
        )

        entity_registry = er.async_get(hass)
        for entry in er.async_entries_for_config_entry(
            entity_registry, config_entry.entry_id
        ):
            await async_update_entity(hass, entry.entity_id)
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug(
            "Could not refresh entities on connection state change: %s",
            err,
        )


async def async_setup_entry(hass, config_entry):
    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = {}

    if not config_entry.options:
        await async_set_options(hass, config_entry)

    coordinator = LoxoneCoordinator(hass, config_entry)
    host = config_entry.options.get(CONF_HOST)

    _LOGGER.info(
        "Setting up Loxone integration for Miniserver at %s:%s",
        host,
        config_entry.options.get(CONF_PORT),
    )

    try:
        await coordinator.async_config_entry_first_refresh()
    except LoxoneServiceUnAvailableError as err:
        _LOGGER.warning(
            "Loxone Miniserver at %s is unavailable (service restarting?). Will retry automatically",
            host,
        )
        raise ConfigEntryNotReady from err
    except LoxoneUnauthorisedError:
        _LOGGER.error(
            "Could not connect to Loxone Miniserver. Unauthorised. Please check username and password."
        )
        return False
    except OSError as err:
        await coordinator.api.close()
        _LOGGER.warning(
            "Network error connecting to Loxone Miniserver at %s: %s. Will retry automatically",
            host,
            err,
        )
        raise ConfigEntryNotReady from err
    except (
        LoxoneConnectionError,
        LoxoneConnectionClosedOk,
        TimeoutError,
        ConnectionError,
    ) as err:
        await coordinator.api.close()
        _LOGGER.warning(
            "Could not connect to Loxone Miniserver at %s: %s. Will retry automatically",
            host,
            err,
        )
        raise ConfigEntryNotReady from err
    except Exception as err:
        await coordinator.api.close()
        _LOGGER.warning(
            "Unexpected error connecting to Loxone Miniserver at %s: %s. Will retry automatically",
            host,
            err,
        )
        raise ConfigEntryNotReady from err

    _LOGGER.info(
        "Successfully connected to Loxone Miniserver at %s",
        host,
    )

    hass.data.setdefault(DOMAIN, {})[config_entry.entry_id] = coordinator

    setup_tasks = []
    await hass.config_entries.async_forward_entry_setups(config_entry, LOXONE_PLATFORMS)
    for platform in LOXONE_PLATFORMS:
        setup_tasks.append(
            hass.async_create_task(
                async_load_platform(hass, platform, DOMAIN, {}, config_entry)
            )
        )

    if setup_tasks:
        await asyncio.wait(setup_tasks)

    async def _reload_after_delay(delay: float = 1.0) -> None:
        await coordinator.api.close()
        await asyncio.sleep(delay)
        await hass.services.async_call("loxone", "reload")

    def handle_task_result(task: asyncio.Task) -> None:
        try:
            task.result()
        except LoxoneTokenError as e:
            _LOGGER.debug(
                "Token is not valid anymore. Delete token and try to reloading Loxone integration."
            )
            # First we delete the invalid token then try to reload
            hass.config_entries.async_update_entry(
                config_entry,
                data={
                    "token": "",
                    "hash_alg": "",
                    "valid_until": "",
                },
            )
            # Loxone-Integration neu laden
            hass.async_create_task(_reload_after_delay(1.0))
        except (
            LoxoneUnauthorisedError,
            LoxoneAuthEscalatedError,
        ) as e:
            # Hard credential rejection (401/4003 in an auth response)
            # or a token refresh that failed TOKEN_REFRESH_MAX_FAILURES
            # times in a row. Both mean: the cached state is unusable —
            # drop the token, reload and re-authenticate from scratch.
            # A persistently wrong password ends up as a setup error on
            # the reload instead of a silent retry loop.
            _LOGGER.debug(
                "Loxone credentials rejected (%s). Delete token and reload "
                "Loxone integration.",
                e,
            )
            hass.config_entries.async_update_entry(
                config_entry,
                data={
                    "token": "",
                    "hash_alg": "",
                    "valid_until": "",
                },
            )
            hass.async_create_task(_reload_after_delay(1.0))
        except LoxoneOutOfServiceException as e:
            _LOGGER.debug(
                "Loxone LoxoneOutOfServiceException received. Try to reloading Loxone integration."
            )
            # Loxone-Integration neu laden
            hass.async_create_task(_reload_after_delay(1.0))
        except LoxoneConnectionError as e:
            _LOGGER.debug(
                "Loxone LoxoneConnectionError received. Try to reloading Loxone integration."
            )
            # Loxone-Integration neu laden
            hass.async_create_task(_reload_after_delay(1.0))
        except (
            LoxoneConnectionClosedOk,
            websockets.exceptions.ConnectionClosedOK,
        ) as e:
            _LOGGER.debug(
                "Loxone LoxoneConnectionClosedOk received. Mostly a timeout Problem. Try to reloading Loxone integration."
            )
            # Loxone-Integration neu laden
            hass.async_create_task(_reload_after_delay(1.0))
        except asyncio.exceptions.CancelledError as e:
            _LOGGER.error(e)
        except Exception as e:
            raise e

    async def message_callback(message):
        """Fire message on HomeAssistant Bus."""
        # Lazy %-args — this runs for every Miniserver event, so the dict
        # must not be stringified unless DEBUG is enabled. G004 already
        # bans the f-string variant; do not "simplify" it back.
        _LOGGER.debug("%s", message)
        hass.bus.async_fire(EVENT, message)

    async def handle_websocket_command(call):
        """Handle websocket command services."""
        value = call.data.get(ATTR_VALUE, DEFAULT)
        if call.data.get(ATTR_DEVICE) is None:
            entity_uuid = call.data.get(ATTR_UUID, DEFAULT)
        else:
            entity_registry = er.async_get(hass)
            entity_id = call.data.get(ATTR_DEVICE)
            entity = entity_registry.async_get(entity_id)
            entity_uuid = entity.unique_id
        await coordinator.api.send_websocket_command(entity_uuid, value)

    async def handle_secured_websocket_command(call):
        """Handle websocket command services."""
        value = call.data.get(ATTR_VALUE, DEFAULT)
        code = call.data.get(ATTR_CODE, DEFAULT)
        if call.data.get(ATTR_DEVICE) is None:
            entity_uuid = call.data.get(ATTR_UUID, DEFAULT)
        else:
            entity_registry = er.async_get(hass)
            entity_id = call.data.get(ATTR_DEVICE)
            entity = entity_registry.async_get(entity_id)
            entity_uuid = entity.unique_id
        await coordinator.api.send_secured_websocket_command(entity_uuid, value, code)

    async def sync_areas_with_loxone(data={}):
        create_areas = data.get(ATTR_AREA_CREATE, DEFAULT)
        if create_areas not in [True, False]:
            create_areas = False
        lox_items = []
        er_registry = er.async_get(hass)
        ar_registry = ar.async_get(hass)
        for id, entry in er_registry.entities.items():
            if entry.platform == DOMAIN:
                state = hass.states.get(entry.entity_id)
                if hasattr(state, "attributes") and "room" in state.attributes:
                    area = ar_registry.async_get_area_by_name(state.attributes["room"])
                    if area is None and create_areas:
                        area = ar_registry.async_get_or_create(state.attributes["room"])
                    if area and entry.area_id is None:
                        lox_items.append((entry.entity_id, area.id))

        for _ in lox_items:
            er_registry.async_update_entity(_[0], area_id=_[1])

    async def handle_sync_areas_with_loxone(call):
        await sync_areas_with_loxone(call.data)

    async def handle_reload(call):
        """Handle the service call to reload the integration."""
        _LOGGER.info("Reloading Loxone integration via service call")
        entries = hass.config_entries.async_entries(DOMAIN)
        unloads = [
            hass.config_entries.async_unload(entry.entry_id) for entry in entries
        ]
        await asyncio.gather(*unloads)
        loads = [hass.config_entries.async_reload(entry.entry_id) for entry in entries]
        await asyncio.gather(*loads)
        _LOGGER.info("Loxone integration reload complete")

    async def loxone_discovered(event):
        _LOGGER.info("Creating groups")
        miniserver = get_miniserver_from_hass(hass, config_entry)
        if miniserver.miniserver_type < 2 and "component" in event.data:
            if event.data["component"] == DOMAIN:
                try:
                    _LOGGER.info("loxone discovered")
                    await asyncio.sleep(0.1)
                    # await sync_areas_with_loxone()
                    entity_ids = hass.states.async_all()
                    sensors_analog = []
                    sensors_digital = []
                    switches = []
                    covers = []
                    lights = []
                    dimmers = []
                    climates = []
                    fans = []
                    accontrols = []
                    numbers = []
                    texts = []
                    buttons = []

                    for s in entity_ids:
                        s_dict = s.as_dict()
                        attr = s_dict["attributes"]
                        if "platform" in attr and attr["platform"] == DOMAIN:
                            device_type = attr.get("device_type", "")
                            if device_type in ["analog_sensor", "Meter"]:
                                sensors_analog.append(s_dict["entity_id"])
                            elif device_type == "digital_sensor":
                                sensors_digital.append(s_dict["entity_id"])
                            elif device_type in ["Jalousie", "Gate", "Window"]:
                                covers.append(s_dict["entity_id"])
                            elif device_type in ["Switch", "TimedSwitch"]:
                                switches.append(s_dict["entity_id"])
                            elif device_type == "Pushbutton":
                                buttons.append(s_dict["entity_id"])
                            elif device_type in ["LightControllerV2"]:
                                lights.append(s_dict["entity_id"])
                            elif device_type == "Dimmer":
                                dimmers.append(s_dict["entity_id"])
                            elif device_type == "IRoomControllerV2":
                                climates.append(s_dict["entity_id"])
                            elif device_type == "Ventilation":
                                fans.append(s_dict["entity_id"])
                            elif device_type == "AcControl":
                                accontrols.append(s_dict["entity_id"])
                            elif device_type == "Slider":
                                numbers.append(s_dict["entity_id"])
                            elif device_type == "TextInput":
                                texts.append(s_dict["entity_id"])

                    sensors_analog.sort()
                    sensors_digital.sort()
                    covers.sort()
                    switches.sort()
                    buttons.sort()
                    lights.sort()
                    climates.sort()
                    dimmers.sort()
                    fans.sort()
                    accontrols.sort()
                    numbers.sort()
                    texts.sort()
                    await async_setup_component(hass, "group", {})
                    await create_group_for_loxone_entities(
                        hass, sensors_analog, "Loxone Analog Sensors", "loxone_analog"
                    )
                    await create_group_for_loxone_entities(
                        hass,
                        sensors_digital,
                        "Loxone Digital Sensors",
                        "loxone_digital",
                    )
                    await create_group_for_loxone_entities(
                        hass, switches, "Loxone Switches", "loxone_switches"
                    )
                    await create_group_for_loxone_entities(
                        hass, buttons, "Loxone Buttons", "loxone_buttons"
                    )
                    await create_group_for_loxone_entities(
                        hass, covers, "Loxone Covers", "loxone_covers"
                    )
                    await create_group_for_loxone_entities(
                        hass, lights, "Loxone LightControllers", "loxone_lights"
                    )
                    await create_group_for_loxone_entities(
                        hass, lights, "Loxone Dimmer", "loxone_dimmers"
                    )
                    await create_group_for_loxone_entities(
                        hass, climates, "Loxone Room Controllers", "loxone_climates"
                    )
                    await create_group_for_loxone_entities(
                        hass,
                        fans,
                        "Loxone Ventilation Controllers",
                        "loxone_ventilations",
                    )
                    await create_group_for_loxone_entities(
                        hass,
                        accontrols,
                        "Loxone AC Controllers",
                        "loxone_accontrollers",
                    )
                    await create_group_for_loxone_entities(
                        hass, numbers, "Loxone Numbers", "loxone_numbers"
                    )
                    await create_group_for_loxone_entities(
                        hass, texts, "Loxone Texts", "loxone_texts"
                    )
                    await hass.async_block_till_done()
                    await create_group_for_loxone_entities(
                        hass,
                        [
                            "group.loxone_analog",
                            "group.loxone_digital",
                            "group.loxone_switches",
                            "group.loxone_buttons",
                            "group.loxone_covers",
                            "group.loxone_lights",
                            "group.loxone_ventilations",
                            "group.loxone_numbers",
                            "group.loxone_texts",
                        ],
                        "Loxone Group",
                        "loxone_group",
                    )
                except Exception as err:
                    _LOGGER.error(
                        "Can't create group '%s'. Try to make at least one group manually. ("
                        "https://www.home-assistant.io/integrations/group/)",
                        err,
                    )

    async def start_event():
        try:
            # ``run()`` owns the listen loop with bounded
            # exponential backoff — the previous
            # ``start_listening + done_callback`` pattern
            # forced a full integration reload on every
            # transient drop. ``run()`` retries in-place and
            # only propagates unrecoverable failures (auth,
            # unexpected). The done-callback reload path is
            # kept as a safety net for anything ``run()``
            # itself can't handle.
            listening_task = asyncio.create_task(
                coordinator.api.run(
                    on_state=_on_connection_state,
                    callback=message_callback,
                )
            )
            listening_task.add_done_callback(handle_task_result)

        except Exception as e:
            raise e

    def _on_connection_state(state: str):
        return async_refresh_on_connection_state(
            hass, config_entry, coordinator, state
        )

    async def stop_event(_):
        token = coordinator.api.get_token_dict()
        hass.config_entries.async_update_entry(
            config_entry,
            data={
                **config_entry.data,  # preserve existing data
                "token": token["token"],
                "hash_alg": token["hash_alg"],
                "valid_until": token["valid_until"],
            },
        )
        await coordinator.api.close()

    async def loxone_send(event):
        """Listen for change Events from Loxone Components"""
        try:
            if event.event_type == SENDDOMAIN and isinstance(event.data, dict):
                value = event.data.get(ATTR_VALUE, DEFAULT)
                device_uuid = event.data.get(ATTR_UUID, DEFAULT)
                if value is None:
                    value = DEFAULT
                if device_uuid is None:
                    device_uuid = DEFAULT

                _ = asyncio.create_task(
                    coordinator.api.send_websocket_command(device_uuid, value)
                )

            elif event.event_type == SECUREDSENDDOMAIN and isinstance(event.data, dict):
                value = event.data.get(ATTR_VALUE, DEFAULT)
                device_uuid = event.data.get(ATTR_UUID, DEFAULT)
                code = event.data.get(ATTR_CODE, DEFAULT)
                if code is None:
                    code = DEFAULT
                if value is None:
                    value = DEFAULT
                if device_uuid is None:
                    device_uuid = DEFAULT
                _ = asyncio.create_task(
                    coordinator.api.send_secured_websocket_command(
                        device_uuid, value, code
                    )
                )

        except Exception as e:
            _LOGGER.error(e)

    hass.services.async_register(
        DOMAIN, "event_websocket_command", handle_websocket_command
    )

    hass.services.async_register(
        DOMAIN, "event_secured_websocket_command", handle_secured_websocket_command
    )
    hass.services.async_register(DOMAIN, "sync_areas", handle_sync_areas_with_loxone)
    hass.services.async_register(DOMAIN, "reload", handle_reload)

    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, stop_event)
    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, loxone_discovered)

    # Store listeners for cleanup
    coordinator.listeners = [
        hass.bus.async_listen(SENDDOMAIN, loxone_send),
        hass.bus.async_listen(SECUREDSENDDOMAIN, loxone_send),
    ]

    await start_event()

    return True


async def async_remove_config_entry_device(
    hass: HomeAssistant, config_entry: ConfigEntry, device_entry: DeviceEntry
) -> bool:
    """Remove a config entry from a device."""
    return True


class LoxoneEntity(Entity):
    """
    @DynamicAttrs
    """

    def __init__(self, **kwargs):
        for key in kwargs:
            if not hasattr(self, key):
                if key == "name":
                    self._attr_name = kwargs[key]
                else:
                    setattr(self, key, kwargs[key])
            else:
                try:
                    setattr(self, key, kwargs[key])
                except AttributeError:
                    _LOGGER.error(f"Could set {key} for {self.name}")
                except (Exception,):
                    traceback.print_exc()
                    sys.exit(-1)

        self.listener = None

        # Initialize base extra state attributes with common Loxone fields
        self._attr_extra_state_attributes = {
            "uuid": kwargs.get("uuidAction", ""),
            "platform": "loxone",
        }

        # Add optional common attributes from Loxone JSON if they exist
        if "room" in kwargs and kwargs["room"]:
            self._attr_extra_state_attributes["room"] = kwargs["room"]
        if "cat" in kwargs and kwargs["cat"]:
            self._attr_extra_state_attributes["category"] = kwargs["cat"]

    async def async_added_to_hass(self):
        """Subscribe to device events."""
        self.listener = self.hass.bus.async_listen(EVENT, self.event_handler)

    async def async_will_remove_from_hass(self):
        """Disconnect callbacks."""
        self.listener = None

    async def event_handler(self, e):
        pass

    def _connection_available(self) -> bool:
        """Return False while the Loxone connection is down.

        Reads the flag the ``run()`` supervisor maintains on the
        coordinator (see ``_on_connection_state`` in ``__init__.py``).
        Returns True when the coordinator cannot be determined (entity
        not yet added, no registry entry) so availability is never
        blocked by a lookup failure.
        """
        try:
            coordinator = self.hass.data.get(DOMAIN, {}).get(
                self.registry_entry.config_entry_id
            )
        except AttributeError:
            # Not added to hass yet (or no registry entry available).
            return True
        if coordinator is None:
            return True
        return coordinator.connection_available

    @property
    def available(self) -> bool:
        """Return True if the entity is available and the connection is up."""
        return self._attr_available and self._connection_available()

    @cached_property
    def name(self):
        return self._attr_name

    # @name.setter
    # def name(self, n):
    #     self._attr_name = n

    @staticmethod
    def _clean_unit(lox_format):
        search = re.search(cfmt, lox_format, flags=re.X)
        if search:
            unit = lox_format.replace(search.group(0).strip(), "").strip()
            if unit == "%%":
                unit = unit.replace("%%", "%")
            return unit
        else:
            return lox_format

    @staticmethod
    def _get_format(lox_format):
        search = re.search(cfmt, lox_format, flags=re.X)
        if search:
            return search.group(0).strip()
        return None

    @cached_property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return self.uuidAction
