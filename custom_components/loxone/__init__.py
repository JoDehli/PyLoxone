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
from functools import cached_property

import homeassistant.components.group as group
import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (CONF_HOST, CONF_PASSWORD, CONF_PORT,
                                 CONF_USERNAME, EVENT_COMPONENT_LOADED,
                                 EVENT_HOMEASSISTANT_START,
                                 EVENT_HOMEASSISTANT_STOP)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
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
                    CONF_SCENE_GEN_DELAY, DEFAULT, DEFAULT_DELAY_SCENE,
                    DEFAULT_PORT, DOMAIN, DOMAIN_DEVICES, ERROR_VALUE, EVENT,
                    LOXONE_PLATFORMS, SECUREDSENDDOMAIN, SENDDOMAIN, cfmt)
from .coordinator import LoxoneCoordinator
from .helpers import get_miniserver_type
from .miniserver import MiniServer, get_miniserver_from_hass
from .pyloxone_api.connection import LoxoneConnection
from .pyloxone_api.exceptions import LoxoneException, LoxoneTokenError

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


async def async_unload_entry(hass, config_entry):
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
                _LOGGER.warning(f"Fehler beim Schließen der Verbindung: {e}")
            try:
                # # Unload
                # coordinator = hass.data[DOMAIN].get(config_entry.entry_id)
                # if coordinator and hasattr(coordinator, "listeners"):
                #     for remove_listener in coordinator.listeners:
                #         remove_listener()
                #     coordinator.listeners = []

                del hass.data[DOMAIN][config_entry.entry_id]
            except Exception as e:
                raise e

        # Services deregistrieren beim Entladen
        hass.services.async_remove(DOMAIN, "event_websocket_command")
        hass.services.async_remove(DOMAIN, "event_secured_websocket_command")
        hass.services.async_remove(DOMAIN, "sync_areas")

        # Unload
        unload_ok = await hass.config_entries.async_unload_platforms(
            config_entry, LOXONE_PLATFORMS
        )
        return unload_ok


async def async_setup(hass, config):
    """setup loxone"""
    if DOMAIN in config:
        hass.async_create_task(
            hass.config_entries.flow.async_init(
                DOMAIN, context={"source": "import"}, data=config[DOMAIN]
            )
        )

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

    hass.services.async_register(DOMAIN, "reload", handle_reload)
    return True


async def async_migrate_entry(hass, config_entry):
    # _LOGGER.debug("Migrating from version %s", config_entry.version)
    if config_entry.version == 1:
        new = {**config_entry.options, CONF_LIGHTCONTROLLER_SUBCONTROLS_GEN: True}
        config_entry.options = {**new}
        config_entry.version = 2
        _LOGGER.info("Migration to version %s successful", 2)

    if config_entry.version == 2:
        new = {**config_entry.options, CONF_SCENE_GEN_DELAY: DEFAULT_DELAY_SCENE}
        config_entry.options = {**new}
        config_entry.version = 3
        _LOGGER.info("Migration to version %s successful", 3)
    return True


async def async_set_options(hass, config_entry):
    options_in = {**config_entry.options}
    options = {
        CONF_HOST: options_in.pop(CONF_HOST, ""),
        CONF_PORT: options_in.pop(CONF_PORT, DEFAULT_PORT),
        CONF_USERNAME: options_in.pop(CONF_USERNAME, ""),
        CONF_PASSWORD: options_in.pop(CONF_PASSWORD, ""),
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


async def async_setup_entry(hass, config_entry):
    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = {}

    if not config_entry.options:
        await async_set_options(hass, config_entry)

    coordinator = LoxoneCoordinator(hass, config_entry)
    await coordinator.async_config_entry_first_refresh()
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

    def handle_task_result(task: asyncio.Task) -> None:
        try:
            task.result()
        except LoxoneTokenError as e:
            _LOGGER.debug(
                "Token is not valid anymore. Please restart Homeassistant to aquire new token."
            )
        except asyncio.exceptions.CancelledError as e:
            _LOGGER.error(e)
        except Exception as e:
            raise e

    async def message_callback(message):
        """Fire message on HomeAssistant Bus."""
        _LOGGER.debug(f"{message}")
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
        await coordinator.api.send_secured__websocket_command(entity_uuid, value, code)

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

    async def loxone_discovered(event):
        miniserver = get_miniserver_from_hass(hass)
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
                            if device_type == "analog_sensor":
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
            # noinspection PyTypeChecker
            listening_task = asyncio.create_task(
                coordinator.api.start_listening(callback=message_callback)
            )
            listening_task.add_done_callback(handle_task_result)

        except Exception as e:
            raise e

    async def stop_event(_):
        token = coordinator.api.get_token_dict()
        hass.config_entries.async_update_entry(
            config_entry,
            data={
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
                await coordinator.api.send_websocket_command(device_uuid, value)

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
                await coordinator.api.send_secured__websocket_command(
                    device_uuid, value, code
                )

        except Exception as e:
            _LOGGER.error(e)

    # listeners = []
    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, stop_event)
    hass.bus.async_listen_once(EVENT_COMPONENT_LOADED, loxone_discovered)
    hass.bus.async_listen(SENDDOMAIN, loxone_send)
    hass.bus.async_listen(SECUREDSENDDOMAIN, loxone_send)
    # hass.data[DOMAIN][config_entry.entry_id].listeners = listeners

    # hass.services.async_register(
    #     DOMAIN, "event_websocket_command", handle_websocket_command
    # )
    #
    # hass.services.async_register(
    #     DOMAIN, "event_secured_websocket_command", handle_secured_websocket_command
    # )

    # hass.services.async_register(DOMAIN, "sync_areas", handle_sync_areas_with_loxone)

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

    async def async_added_to_hass(self):
        """Subscribe to device events."""
        self.listener = self.hass.bus.async_listen(EVENT, self.event_handler)

    async def async_will_remove_from_hass(self):
        """Disconnect callbacks."""
        self.listener = None

    async def event_handler(self, e):
        pass

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
