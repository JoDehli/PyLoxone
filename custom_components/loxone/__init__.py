"""
Component to create an interface to the Loxone Miniserver.

For more details about this component, please refer to the documentation at
https://github.com/JoDehli/PyLoxone
"""

import asyncio
import logging
import re
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
from homeassistant.exceptions import (ConfigEntryAuthFailed,
                                      ConfigEntryNotReady, HomeAssistantError)
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceEntry
from homeassistant.helpers.dispatcher import (async_dispatcher_connect,
                                              async_dispatcher_send)
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

# Seconds to wait before reloading an entry whose listening task died
# from an error ``run()`` does not retry itself.
UNEXPECTED_FAILURE_RELOAD_DELAY = 30

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


def connection_state_signal(entry_id: str) -> str:
    """Dispatcher signal sent when the entry's connection goes up or down."""
    return f"{DOMAIN}_connection_state_{entry_id}"


def _async_listen_once_until_unload(
    hass: HomeAssistant, config_entry: ConfigEntry, event_type, listener
) -> None:
    """``hass.bus.async_listen_once`` that is removed when the entry unloads.

    HA logs an exception when the unsubscribe of a ``listen_once`` is
    called after the event has fired, so it is only called while the
    listener is still pending.
    """
    fired = False

    async def _once(event) -> None:
        nonlocal fired
        fired = True
        await listener(event)

    unsub = hass.bus.async_listen_once(event_type, _once)

    def _remove() -> None:
        if not fired:
            unsub()

    config_entry.async_on_unload(_remove)


def _loaded_coordinators(hass: HomeAssistant) -> list[LoxoneCoordinator]:
    return [
        co
        for co in hass.data.get(DOMAIN, {}).values()
        if isinstance(co, LoxoneCoordinator)
    ]


def _coordinator_for_uuid(
    hass: HomeAssistant, uuid: str
) -> LoxoneCoordinator | None:
    """Find the coordinator of the Miniserver that owns ``uuid``.

    With a single Miniserver every UUID goes to it (also UUIDs that are
    not in the structure file, as before). With several, the UUID must
    belong to exactly that Miniserver's structure file.
    """
    coordinators = _loaded_coordinators(hass)
    if len(coordinators) == 1:
        return coordinators[0]
    for co in coordinators:
        if co.owns_uuid(uuid):
            return co
    return None


def _resolve_command_target(
    hass: HomeAssistant, call
) -> tuple[LoxoneCoordinator, str]:
    """Return (coordinator, uuid) for a websocket-command service call."""
    entity_id = call.data.get(ATTR_DEVICE)
    if entity_id is not None:
        entity = er.async_get(hass).async_get(entity_id)
        if entity is None:
            raise HomeAssistantError(f"Unknown entity '{entity_id}'")
        coordinator = hass.data.get(DOMAIN, {}).get(entity.config_entry_id)
        if not isinstance(coordinator, LoxoneCoordinator):
            raise HomeAssistantError(
                f"The Loxone entry of '{entity_id}' is not loaded"
            )
        return coordinator, entity.unique_id

    uuid = call.data.get(ATTR_UUID, DEFAULT)
    coordinator = _coordinator_for_uuid(hass, uuid)
    if coordinator is None:
        raise HomeAssistantError(
            f"No loaded Loxone Miniserver has a control with uuid '{uuid}'"
        )
    return coordinator, uuid


async def _async_handle_websocket_command(hass: HomeAssistant, call) -> None:
    """Handle websocket command services."""
    value = call.data.get(ATTR_VALUE, DEFAULT)
    coordinator, entity_uuid = _resolve_command_target(hass, call)
    await coordinator.api.send_websocket_command(entity_uuid, value)


async def _async_handle_secured_websocket_command(
    hass: HomeAssistant, call
) -> None:
    """Handle secured websocket command services."""
    value = call.data.get(ATTR_VALUE, DEFAULT)
    code = call.data.get(ATTR_CODE, DEFAULT)
    coordinator, entity_uuid = _resolve_command_target(hass, call)
    await coordinator.api.send_secured_websocket_command(entity_uuid, value, code)


async def _async_sync_areas_with_loxone(hass: HomeAssistant, data={}) -> None:
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


async def _async_handle_sync_areas_with_loxone(hass: HomeAssistant, call) -> None:
    await _async_sync_areas_with_loxone(hass, call.data)


async def _async_handle_reload(hass: HomeAssistant, call) -> None:
    """Handle the service call to reload the integration."""
    _LOGGER.info("Reloading Loxone integration via service call")
    # ``async_reload`` unloads and sets up again; an extra unload
    # beforehand would only unload every entry twice.
    await asyncio.gather(
        *(
            hass.config_entries.async_reload(entry.entry_id)
            for entry in hass.config_entries.async_entries(DOMAIN)
        )
    )
    _LOGGER.info("Loxone integration reload complete")


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

    # Connection close. Cancel the supervisor task first: it may be
    # sleeping in backoff between retries, which api.close() alone
    # would not interrupt. Then close the API and drop listeners
    # (owned by coordinator.async_cleanup).
    if coordinator is not None:
        task = getattr(coordinator, "_listening_task", None)
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                _LOGGER.debug("Listening task cancelled during unload")
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning(
                    "Error waiting for listening task to finish: %s",
                    err,
                    exc_info=True,
                )
        coordinator._listening_task = None

        try:
            await coordinator.async_cleanup()
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Error closing connection: %s", err, exc_info=True)

        hass.data[DOMAIN].pop(config_entry.entry_id, None)

    # Services are not removed here: the integration-wide ones are
    # registered once in ``async_setup`` and route per call, and the
    # cover entity services belong to the platform (HA manages them).
    # Removing them would break every other loaded Miniserver.

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
    # Integration-wide services, shared by all Miniservers: each call
    # is routed to the entry that owns the target entity / uuid.
    for service, handler in (
        ("event_websocket_command", _async_handle_websocket_command),
        (
            "event_secured_websocket_command",
            _async_handle_secured_websocket_command,
        ),
        ("sync_areas", _async_handle_sync_areas_with_loxone),
        ("reload", _async_handle_reload),
    ):
        if not hass.services.has_service(DOMAIN, service):
            hass.services.async_register(DOMAIN, service, partial(handler, hass))

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


def _reload_on_options_change(config_entry: ConfigEntry):
    """Update listener that reloads the entry when its *options* changed.

    The options flow stores host, credentials, port etc. in the options,
    but nothing applied them until the next restart. A plain update
    listener would also reload on every token refresh (the token is
    written to ``data``), so only an options change triggers the reload.
    (``options_flow_reloads`` would do this too, but needs HA 2025.10.)
    """
    options_at_setup = dict(config_entry.options)

    async def _listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
        if dict(entry.options) != options_at_setup:
            _LOGGER.info("Loxone options changed; reloading %s", entry.title)
            hass.config_entries.async_schedule_reload(entry.entry_id)

    return _listener


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
    except LoxoneUnauthorisedError as err:
        await coordinator.api.close()
        # HA starts a reauth flow: the user can enter new credentials
        # instead of deleting and re-adding the integration.
        raise ConfigEntryAuthFailed(
            "Loxone Miniserver rejected the username or password"
        ) from err
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

    # Local opt-in evidence belongs to this existing entry, not another setup.
    from .audio_diagnostics import EntryAudioDiagnostics
    coordinator.audio_diagnostics = EntryAudioDiagnostics(
        hass, config_entry, coordinator.miniserver.lox_config.json)
    await coordinator.audio_diagnostics.async_start()
    coordinator.api.audio_diagnostics = coordinator.audio_diagnostics

    # Config-entry platforms only. The extra ``async_load_platform``
    # per platform (with the ConfigEntry passed as ``hass_config``) ran
    # every ``async_setup_platform`` a second time with an empty config,
    # where they do nothing; YAML-defined custom sensors are loaded by
    # HA from YAML independently of this.
    await hass.config_entries.async_forward_entry_setups(config_entry, LOXONE_PLATFORMS)

    async def _reload_after_delay(delay: float) -> None:
        await coordinator.api.close()
        await asyncio.sleep(delay)
        # Reload only this entry, and not through the ``loxone.reload``
        # service: that reloads every Miniserver. ``async_schedule_reload``
        # runs the reload in its own task — this one is an entry
        # background task and would be cancelled by the reload's unload.
        hass.config_entries.async_schedule_reload(config_entry.entry_id)

    def _schedule_reload(delay: float = 1.0) -> None:
        # Entry background task: cancelled automatically if the entry is
        # unloaded during the delay, so no reload revives an entry the
        # user just disabled or removed.
        config_entry.async_create_background_task(
            hass,
            _reload_after_delay(delay),
            name=f"loxone reload {config_entry.entry_id}",
        )

    def handle_task_result(task: asyncio.Task) -> None:
        try:
            task.result()
        except LoxoneTokenError as e:
            _LOGGER.warning(
                "Token is not valid anymore (%s). Delete token and try "
                "reloading Loxone integration.",
                e,
                exc_info=True,
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
            _schedule_reload()
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
            _LOGGER.warning(
                "Loxone credentials rejected (%s). Delete token and reload "
                "Loxone integration.",
                e,
                exc_info=True,
            )
            hass.config_entries.async_update_entry(
                config_entry,
                data={
                    "token": "",
                    "hash_alg": "",
                    "valid_until": "",
                },
            )
            _schedule_reload()
        except LoxoneOutOfServiceException as e:
            _LOGGER.warning(
                "Loxone out of service (%s). Reloading Loxone integration.",
                e,
                exc_info=True,
            )
            # Loxone-Integration neu laden
            _schedule_reload()
        except LoxoneConnectionError as e:
            _LOGGER.warning(
                "Loxone connection error (%s). Reloading Loxone integration.",
                e,
                exc_info=True,
            )
            # Loxone-Integration neu laden
            _schedule_reload()
        except (
            LoxoneConnectionClosedOk,
            websockets.exceptions.ConnectionClosedOK,
        ) as e:
            _LOGGER.warning(
                "Loxone connection closed (%s). Mostly a timeout problem. "
                "Reloading Loxone integration.",
                e,
                exc_info=True,
            )
            # Loxone-Integration neu laden
            _schedule_reload()
        except asyncio.exceptions.CancelledError:
            _LOGGER.debug("Loxone listening task cancelled")
        except Exception:
            # ``run()`` re-runs the full ``open()`` bootstrap on every
            # reconnect, so e.g. an HTTP 500 or a truncated LoxAPP3.json
            # while the Miniserver reboots ends up here. Without a reload
            # the entry would stay loaded with every entity unavailable.
            # The longer delay keeps a persistent failure from turning
            # into a tight reload loop; if the Miniserver is still down,
            # setup raises ConfigEntryNotReady and HA's retry backoff
            # takes over.
            _LOGGER.exception(
                "Unexpected Loxone listening task failure. Reloading "
                "Loxone integration in %s s.",
                UNEXPECTED_FAILURE_RELOAD_DELAY,
            )
            _schedule_reload(UNEXPECTED_FAILURE_RELOAD_DELAY)

    async def message_callback(message):
        """Fire message on HomeAssistant Bus."""
        try:
            if coordinator.audio_diagnostics is not None and coordinator.audio_diagnostics.enabled:
                coordinator.audio_diagnostics.miniserver_feedback(message)
        except Exception:
            pass  # Optional evidence cannot interrupt the existing feedback path.
        # Lazy %-args — this runs for every Miniserver event, so the dict
        # must not be stringified unless DEBUG is enabled. G004 already
        # bans the f-string variant; do not "simplify" it back.
        _LOGGER.debug("%s", message)
        hass.bus.async_fire(EVENT, message)

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
        # ``run()`` owns the listen loop with bounded
        # exponential backoff — the previous
        # ``start_listening + done_callback`` pattern
        # forced a full integration reload on every
        # transient drop. ``run()`` retries in-place and
        # only propagates unrecoverable failures (auth,
        # unexpected). The done-callback reload path is
        # kept as a safety net for anything ``run()``
        # itself can't handle.
        # Entry background task: HA cancels it on unload and shutdown
        # and does not wait for it (it runs as long as the entry).
        listening_task = config_entry.async_create_background_task(
            hass,
            coordinator.api.run(
                on_state=_on_connection_state,
                callback=message_callback,
            ),
            name=f"loxone listener {config_entry.entry_id}",
        )
        coordinator._listening_task = listening_task
        listening_task.add_done_callback(handle_task_result)

    def _on_connection_state(state: str) -> None:
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
        # Every loaded LoxoneEntity of this entry rewrites its state (see
        # ``LoxoneEntity.async_added_to_hass``). Previously one
        # ``async_update_entity`` task was created per registry entry -
        # disabled entities included, which HA then reported as not found.
        async_dispatcher_send(hass, connection_state_signal(config_entry.entry_id))

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

    def _send_in_background(device_uuid, send) -> None:
        """Run a command send as a tracked entry task and log failures.

        A bare ``asyncio.create_task`` kept no reference (the task could
        be garbage collected) and nobody retrieved its exception, so a
        failed command was silent.
        """

        async def _send() -> None:
            try:
                await send
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning(
                    "Could not send command to %s: %s", device_uuid, err
                )

        config_entry.async_create_background_task(
            hass, _send(), name=f"loxone send {device_uuid}"
        )

    async def loxone_send(event):
        """Listen for change Events from Loxone Components"""
        try:
            if not isinstance(event.data, dict):
                return
            # Every loaded Miniserver listens to these events; only the
            # one that owns the control may send it, otherwise a command
            # would go out on every Miniserver.
            if (
                _coordinator_for_uuid(hass, event.data.get(ATTR_UUID, DEFAULT))
                is not coordinator
            ):
                return
            if event.event_type == SENDDOMAIN and isinstance(event.data, dict):
                value = event.data.get(ATTR_VALUE, DEFAULT)
                device_uuid = event.data.get(ATTR_UUID, DEFAULT)
                if value is None:
                    value = DEFAULT
                if device_uuid is None:
                    device_uuid = DEFAULT

                _send_in_background(
                    device_uuid,
                    coordinator.api.send_websocket_command(device_uuid, value),
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
                _send_in_background(
                    device_uuid,
                    coordinator.api.send_secured_websocket_command(
                        device_uuid, value, code
                    ),
                )

        except Exception as e:
            _LOGGER.error(e)

    config_entry.async_on_unload(
        config_entry.add_update_listener(_reload_on_options_change(config_entry))
    )

    # Tied to this entry: after a reload the old listeners would keep
    # the old coordinator alive and, at shutdown, write its stale token
    # into the entry (also of an entry the user has disabled meanwhile).
    _async_listen_once_until_unload(
        hass, config_entry, EVENT_HOMEASSISTANT_STOP, stop_event
    )
    _async_listen_once_until_unload(
        hass, config_entry, EVENT_HOMEASSISTANT_STARTED, loxone_discovered
    )

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
                # A control attribute that cannot be set is skipped, never
                # fatal: one odd control in the structure file must not
                # take down the entity setup (this used to sys.exit the
                # whole Home Assistant process). ``kwargs`` instead of
                # ``self.name``: the name may not be set yet.
                try:
                    setattr(self, key, kwargs[key])
                except AttributeError:
                    _LOGGER.error(
                        "Could not set %s for %s", key, kwargs.get("name")
                    )
                except Exception:
                    _LOGGER.exception(
                        "Could not set %s for %s", key, kwargs.get("name")
                    )

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
        # ``async_on_remove`` unsubscribes when the entity is removed
        # (unload / reload); otherwise every reload would leave one
        # stale ``event_handler`` per entity on the bus.
        self.listener = self.hass.bus.async_listen(EVENT, self.event_handler)
        self.async_on_remove(self.listener)
        # Rewrite the state when the connection goes up or down, so
        # ``available`` follows it without waiting for the next value.
        registry_entry = getattr(self, "registry_entry", None)
        if registry_entry is not None and registry_entry.config_entry_id:
            self.async_on_remove(
                async_dispatcher_connect(
                    self.hass,
                    connection_state_signal(registry_entry.config_entry_id),
                    self.async_write_ha_state,
                )
            )

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
