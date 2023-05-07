"""
Component to create an interface to the Loxone Miniserver.

For more details about this component, please refer to the documentation at
https://github.com/JoDehli/PyLoxone
"""
import asyncio
import json
import logging
import os
import re
import sys
import traceback
from collections.abc import Callable

import homeassistant.components.group as group
import voluptuous as vol
from homeassistant.config import get_default_config_dir
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (CONF_HOST, CONF_PASSWORD, CONF_PORT,
                                 CONF_USERNAME, EVENT_COMPONENT_LOADED,
                                 EVENT_HOMEASSISTANT_START,
                                 EVENT_HOMEASSISTANT_STOP)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.device_registry import DeviceEntry
from homeassistant.helpers.discovery import async_load_platform
from homeassistant.helpers.entity import Entity

from .const import *
from .pyloxone_api import *
from .pyloxone_api.exceptions import LoxoneCommandError

# from .helpers import get_miniserver_type


# from .minismerver import MiniServer, get_miniserver_from_config_entry

REQUIREMENTS = ["pycryptodome", "numpy"]
DEFAULT_TOKEN_PERSIST_NAME = "lox_token.cfg"

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


# TODO: Implement a complete restart of the loxone component without restart HomeAssistant
# TODO: Unload device
# TODO: get version and check for updates https://update.loxone.com/updatecheck.xml?serial=xxxxxxxxx


# class GlobalListeners:
#     def __init__(self):
#         self.listeners: list[Callable[[], None]] = []
#
#     @callback
#     def async_add_listener(self, update_callback):
#         """Listen for data updates."""
#         # This is the first listener, set up interval.
#         self.listeners.append(update_callback)
#
#     @callback
#     def async_remove_listener(self, update_callback):
#         """Remove data update."""
#         self.listeners.remove(update_callback)


@callback
def get_miniserver_from_config_entry(hass, config_entry) -> Miniserver:
    """Return Miniserver with a matching bridge id."""
    return hass.data[DOMAIN][config_entry.entry_id]


@callback
def get_miniserver_from_hass(hass) -> Miniserver:
    """Return Miniserver with a matching bridge id."""
    return hass.data[DOMAIN][list(hass.data[DOMAIN].keys())[0]]["miniserver"]


# @callback
# def get_listeners_from_hass(hass) -> GlobalListeners:
#     """Return Miniserver with a matching bridge id."""
#     return hass.data[DOMAIN][list(hass.data[DOMAIN].keys())[0]]['listeners']


@callback
def get_miniserver_from_config(hass, config):
    """Return first Miniserver. Only one Miniserver is allowed"""
    if len(config) == 0:
        return None
    return config[next(iter(config))]


def safe_token(dict_token: dict) -> None:
    persist_token = ""
    try:
        persist_token = os.path.join(
            get_default_config_dir(), DEFAULT_TOKEN_PERSIST_NAME
        )
        try:
            with open(persist_token, "w") as write_file:
                json.dump(dict_token, write_file)
            _LOGGER.debug("Token saved successfully...")
        except FileNotFoundError:
            persist_token = DEFAULT_TOKEN_PERSIST_NAME
            with open(persist_token, "w") as write_file:
                json.dump(dict_token, write_file)
            _LOGGER.debug("Token saved successfully...")

    except IOError:
        _LOGGER.debug("Error while saving token...")
        _LOGGER.debug(f"Tokenpath: {persist_token}")


def load_token() -> None | dict:
    try:
        persist_token = os.path.join(
            get_default_config_dir(), DEFAULT_TOKEN_PERSIST_NAME
        )
        try:
            with open(persist_token) as f:
                try:
                    dict_token = json.load(f)
                    _LOGGER.debug("Loading token successfully...")
                    return dict_token
                except ValueError:
                    return None
        except FileNotFoundError:
            with open(DEFAULT_TOKEN_PERSIST_NAME) as f:
                try:
                    dict_token = json.load(f)
                    _LOGGER.debug("Loading token successfully...")
                    return dict_token
                except ValueError:
                    return None
    except IOError:
        _LOGGER.debug("Error while loading token...")
        return None


async def async_setup(hass, config):
    """setup loxone"""
    if DOMAIN in config:
        hass.async_create_task(
            hass.config_entries.flow.async_init(
                DOMAIN, context={"source": "import"}, data=config[DOMAIN]
            )
        )
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
    data = {**config_entry.data}
    options = {
        CONF_HOST: data.pop(CONF_HOST, ""),
        CONF_PORT: data.pop(CONF_PORT, DEFAULT_PORT),
        CONF_USERNAME: data.pop(CONF_USERNAME, ""),
        CONF_PASSWORD: data.pop(CONF_PASSWORD, ""),
        CONF_SCENE_GEN: data.pop(CONF_SCENE_GEN, ""),
        CONF_SCENE_GEN_DELAY: data.pop(CONF_SCENE_GEN_DELAY, DEFAULT_DELAY_SCENE),
        CONF_LIGHTCONTROLLER_SUBCONTROLS_GEN: data.pop(
            CONF_LIGHTCONTROLLER_SUBCONTROLS_GEN, ""
        ),
    }
    hass.config_entries.async_update_entry(config_entry, data=data, options=options)


async def async_config_entry_updated(hass, entry) -> None:
    """Handle signals of config entry being updated.

    This is a static method because a class method (bound method), can not be used with weak references.
    Causes for this is either discovery updating host address or config entry options changing.
    """
    pass


async def create_group_for_loxone_enties(hass, entites, name, object_id):
    try:
        await group.Group.async_create_group(
            hass,
            name,
            object_id=object_id,
            entity_ids=entites,
        )
    except HomeAssistantError as err:
        _LOGGER.error("Can't create group '%s' with error: %s", name, err)
    except Exception as err:
        _LOGGER.error("Can't create group '%s' with error: %s", name, err)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    unload_ok = all(
        await asyncio.gather(
            *[
                hass.config_entries.async_forward_entry_unload(entry, component)
                for component in LOXONE_PLATFORMS
            ]
        )
    )
    if not unload_ok:
        return False

    if unload_ok:
        hass.services.async_remove(DOMAIN, "event_websocket_command")
        miniserver = get_miniserver_from_hass(hass)
        await miniserver.close()
    await asyncio.sleep(1)

    return unload_ok


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if DOMAIN not in hass.data:
        hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
            "miniserver": None,
            # "listeners": GlobalListeners()
        }

    if not entry.options:
        await async_set_options(hass, entry)

    token = load_token()

    # check if old token format. if old do not use
    if "_token" in token:
        _LOGGER.debug("Old token format found. Token will not be used.")
        token = None

    miniserver = Miniserver(
        user=entry.options.get("username"),
        password=entry.options.get("password"),
        host=entry.options.get("host"),
        port=entry.options.get("port"),
        use_tls=False,
        token_store=token,
    )

    # _LOGGER = logging.getLogger("pyloxone_api")
    # _LOGGER.setLevel(logging.DEBUG)
    # _LOGGER.addHandler(logging.StreamHandler())

    await miniserver.connect()
    hass.data[DOMAIN][entry.entry_id].update({"miniserver": miniserver})

    setup_tasks = []

    for platform in LOXONE_PLATFORMS:
        # for platform in [Platform.SENSOR]:
        _LOGGER.debug("starting loxone {}...".format(platform))
        setup_tasks.append(
            hass.async_create_task(
                hass.config_entries.async_forward_entry_setup(entry, platform)
            )
        )
        setup_tasks.append(
            hass.async_create_task(
                async_load_platform(hass, platform, DOMAIN, {}, entry)
            )
        )

    if setup_tasks:
        await asyncio.wait(setup_tasks)

    async def enable_state_updates(event):
        await miniserver.enable_state_updates()

    @callback
    async def message_callback():
        """Fire message on HomeAssistant Bus."""
        while True:
            # Wait for and then print a state update
            e = await miniserver.get_state_updates()
            message = e.as_dict()
            if isinstance(message, str):
                message = eval(message)
            if message != {}:
                _LOGGER.debug(message)
            hass.bus.async_fire(EVENT, message)
            await asyncio.sleep(0)

    message_listening_task = asyncio.create_task(
        message_callback(), name="message_callback"
    )

    new_data = _UNDEF

    if entry.unique_id is None:
        hass.config_entries.async_update_entry(
            entry, unique_id=miniserver.snr, data=new_data
        )
        # Workaround
        await asyncio.sleep(5)

    async def handle_websocket_command(call):
        """Handle websocket command services."""
        value = call.data.get(ATTR_VALUE, DEFAULT)
        device_uuid = call.data.get(ATTR_UUID, DEFAULT)
        if value is None or device_uuid is None:
            _LOGGER.error(f"Can not send command. Please fill in all required data.")
            return False
        if not isinstance(value, str):
            value = str(value).strip()
        if not isinstance(device_uuid, str):
            device_uuid = str(value).strip()
        _LOGGER.debug(f"send command: jdev/sps/io/{device_uuid}/{value}")
        try:
            await miniserver.send_control_command(device_uuid, value)
        except LoxoneCommandError as e:
            _LOGGER.error(
                f"Error on sending command jdev/sps/io/{device_uuid}/{value}: {str(e)}"
            )
            _LOGGER.error(f"Error code {e.code} -> message: {e.message}")

    async def send_to_loxone(event):
        """Listen for change Events from Loxone Components"""
        try:
            if event.event_type == SENDDOMAIN and isinstance(event.data, dict):
                value = event.data.get(ATTR_VALUE, DEFAULT)
                device_uuid = event.data.get(ATTR_UUID, DEFAULT)
                if device_uuid is None:
                    device_uuid = DEFAULT
                if value is None:
                    value = DEFAULT
                await miniserver.send_control_command(device_uuid, value)
            elif event.event_type == SECUREDSENDDOMAIN and isinstance(event.data, dict):
                value = event.data.get(ATTR_VALUE, DEFAULT)
                device_uuid = event.data.get(ATTR_UUID, DEFAULT)
                code = event.data.get(ATTR_CODE, DEFAULT)
                if code is None:
                    code = DEFAULT
                if device_uuid is None:
                    device_uuid = DEFAULT
                if value is None:
                    value = DEFAULT
                miniserver.visual_password = code
                await miniserver.send_secured_control_command(device_uuid, value)
                miniserver.visual_password = ""
        except ValueError:
            traceback.print_exc()

    async def stop_miniserver(event):
        safe_token(miniserver.token_dict)
        message_listening_task.cancel()
        await miniserver.close()

    async def loxone_discovered(event):
        _LOGGER.debug("Loxone discovered")

    entry.async_on_unload(hass.bus.async_listen(SENDDOMAIN, send_to_loxone))
    entry.async_on_unload(hass.bus.async_listen(SECUREDSENDDOMAIN, send_to_loxone))
    entry.async_on_unload(
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, stop_miniserver)
    )
    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_START, loxone_discovered)

    hass.services.async_register(
        DOMAIN, "event_websocket_command", handle_websocket_command
    )

    await miniserver.enable_state_updates()

    return True
    # hass.bus.async_listen_once(EVENT_COMPONENT_LOADED, loxone_discovered)
    #
    # hass.bus.async_listen(SENDDOMAIN, miniserver.listen_loxone_send)
    # hass.bus.async_listen(SECUREDSENDDOMAIN, miniserver.listen_loxone_send)
    #
    # hass.services.async_register(
    #     DOMAIN, "event_websocket_command", handle_websocket_command
    # )
    #
    # hass.services.async_register(DOMAIN, "sync_areas", handle_sync_areas_with_loxone)

    # If you want to receive status updates from the Miniserver, you need to
    # tell it!
    # await miniserver.enable_state_updates()
    #
    # import json
    # print(json.dumps(miniserver.structure, indent=2))
    # print("d")
    # while True:
    #     # Wait for and then print a state update
    #     print(await miniserver.get_state_updates())
    #     await asyncio.sleep(0)

    # if not await miniserver.async_setup():
    #     return False

    # if DOMAIN not in hass.data:
    #     hass.data[DOMAIN] = {}
    #
    # if not config_entry.options:
    #     await async_set_options(hass, config_entry)
    #
    # miniserver = MiniServer(hass, config_entry)
    #
    # if not await miniserver.async_setup():
    #     return False
    #
    # hass.data[DOMAIN][miniserver.serial] = miniserver
    #
    # setup_tasks = []
    #
    # for platform in LOXONE_PLATFORMS:
    #     _LOGGER.debug("starting loxone {}...".format(platform))
    #
    #     hass.async_create_task(
    #         hass.config_entries.async_forward_entry_setup(config_entry, platform)
    #     )
    #     setup_tasks.append(
    #         hass.async_create_task(
    #             async_load_platform(hass, platform, DOMAIN, {}, config_entry)
    #         )
    #     )
    #
    # if setup_tasks:
    #     await asyncio.wait(setup_tasks)
    #
    # config_entry.add_update_listener(async_config_entry_updated)
    #
    # new_data = _UNDEF
    #
    # if config_entry.unique_id is None:
    #     hass.config_entries.async_update_entry(
    #         config_entry, unique_id=miniserver.serial, data=new_data
    #     )
    #     # Workaround
    #     await asyncio.sleep(5)
    #
    # await miniserver.async_update_device_registry()
    #
    # async def message_callback(message):
    #     """Fire message on HomeAssistant Bus."""
    #     hass.bus.async_fire(EVENT, message)
    #
    # async def handle_websocket_command(call):
    #     """Handle websocket command services."""
    #     value = call.data.get(ATTR_VALUE, DEFAULT)
    #     device_uuid = call.data.get(ATTR_UUID, DEFAULT)
    #     await miniserver.api.send_websocket_command(device_uuid, value)
    #
    # async def sync_areas_with_loxone(data={}):
    #     create_areas = data.get(ATTR_AREA_CREATE, DEFAULT)
    #     if create_areas not in [True, False]:
    #         create_areas = False
    #     lox_items = []
    #     er_registry = er.async_get(hass)
    #     ar_registry = ar.async_get(hass)
    #     for id, entry in er_registry.entities.items():
    #         if entry.platform == DOMAIN:
    #             state = hass.states.get(entry.entity_id)
    #             if hasattr(state, "attributes") and "room" in state.attributes:
    #                 area = ar_registry.async_get_area_by_name(state.attributes["room"])
    #                 if area is None and create_areas:
    #                     area = ar_registry.async_get_or_create(state.attributes["room"])
    #                 if area and entry.area_id is None:
    #                     lox_items.append((entry.entity_id, area.id))
    #
    #     for _ in lox_items:
    #         er_registry.async_update_entity(_[0], area_id=_[1])
    #
    # async def handle_sync_areas_with_loxone(call):
    #     await sync_areas_with_loxone(call.data)
    #
    # async def loxone_discovered(event):
    #     miniserver = get_miniserver_from_hass(hass)
    #     if miniserver.miniserver_type < 2 and "component" in event.data:
    #         if event.data["component"] == DOMAIN:
    #             try:
    #                 _LOGGER.info("loxone discovered")
    #                 await asyncio.sleep(0.1)
    #                 # await sync_areas_with_loxone()
    #                 entity_ids = hass.states.async_all()
    #                 sensors_analog = []
    #                 sensors_digital = []
    #                 switches = []
    #                 covers = []
    #                 lights = []
    #                 dimmers = []
    #                 climates = []
    #                 fans = []
    #
    #                 for s in entity_ids:
    #                     s_dict = s.as_dict()
    #                     attr = s_dict["attributes"]
    #                     if "platform" in attr and attr["platform"] == DOMAIN:
    #                         device_typ = attr.get("device_typ", "")
    #                         if device_typ == "analog_sensor":
    #                             sensors_analog.append(s_dict["entity_id"])
    #                         elif device_typ == "digital_sensor":
    #                             sensors_digital.append(s_dict["entity_id"])
    #                         elif device_typ in ["Jalousie", "Gate", "Window"]:
    #                             covers.append(s_dict["entity_id"])
    #                         elif device_typ in ["Switch", "Pushbutton", "TimedSwitch"]:
    #                             switches.append(s_dict["entity_id"])
    #                         elif device_typ in ["LightControllerV2"]:
    #                             lights.append(s_dict["entity_id"])
    #                         elif device_typ == "Dimmer":
    #                             dimmers.append(s_dict["entity_id"])
    #                         elif device_typ == "IRoomControllerV2":
    #                             climates.append(s_dict["entity_id"])
    #                         elif device_typ == "Ventilation":
    #                             fans.append(s_dict["entity_id"])
    #
    #                 sensors_analog.sort()
    #                 sensors_digital.sort()
    #                 covers.sort()
    #                 switches.sort()
    #                 lights.sort()
    #                 climates.sort()
    #                 dimmers.sort()
    #                 fans.sort()
    #
    #                 await create_group_for_loxone_enties(
    #                     hass, sensors_analog, "Loxone Analog Sensors", "loxone_analog"
    #                 )
    #                 await create_group_for_loxone_enties(
    #                     hass,
    #                     sensors_digital,
    #                     "Loxone Digital Sensors",
    #                     "loxone_digital",
    #                 )
    #                 await create_group_for_loxone_enties(
    #                     hass, switches, "Loxone Switches", "loxone_switches"
    #                 )
    #                 await create_group_for_loxone_enties(
    #                     hass, covers, "Loxone Covers", "loxone_covers"
    #                 )
    #                 await create_group_for_loxone_enties(
    #                     hass, lights, "Loxone LightControllers", "loxone_lights"
    #                 )
    #                 await create_group_for_loxone_enties(
    #                     hass, lights, "Loxone Dimmer", "loxone_dimmers"
    #                 )
    #                 await create_group_for_loxone_enties(
    #                     hass, climates, "Loxone Room Controllers", "loxone_climates"
    #                 )
    #                 await create_group_for_loxone_enties(
    #                     hass,
    #                     fans,
    #                     "Loxone Ventilation Controllers",
    #                     "loxone_ventilations",
    #                 )
    #                 await hass.async_block_till_done()
    #                 await create_group_for_loxone_enties(
    #                     hass,
    #                     [
    #                         "group.loxone_analog",
    #                         "group.loxone_digital",
    #                         "group.loxone_switches",
    #                         "group.loxone_covers",
    #                         "group.loxone_lights",
    #                         "group.loxone_ventilations",
    #                     ],
    #                     "Loxone Group",
    #                     "loxone_group",
    #                 )
    #             except Exception as err:
    #                 _LOGGER.error("Error Group generation: %s", err)
    #
    # await miniserver.async_set_callback(message_callback)
    #
    # res = await miniserver.start_ws()
    # if not res:
    #     return False
    #
    # for platform in ["scene"]:
    #     _LOGGER.debug("starting loxone {}...".format(platform))
    #     hass.async_create_task(
    #         hass.config_entries.async_forward_entry_setup(config_entry, platform)
    #     )
    #
    # hass.bus.async_listen_once(EVENT_HOMEASSISTANT_START, miniserver.start_loxone)
    # hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, miniserver.stop_loxone)
    # hass.bus.async_listen_once(EVENT_COMPONENT_LOADED, loxone_discovered)
    #
    # hass.bus.async_listen(SENDDOMAIN, miniserver.listen_loxone_send)
    # hass.bus.async_listen(SECUREDSENDDOMAIN, miniserver.listen_loxone_send)
    #
    # hass.services.async_register(
    #     DOMAIN, "event_websocket_command", handle_websocket_command
    # )
    #
    # hass.services.async_register(DOMAIN, "sync_areas", handle_sync_areas_with_loxone)


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
        self._name = ""
        for key in kwargs:
            if not hasattr(self, key):
                setattr(self, key, kwargs[key])
            else:
                try:
                    setattr(self, key, kwargs[key])
                except AttributeError:
                    _LOGGER.info(f"Could set {key} for {self._name}")
                except (Exception,):
                    traceback.print_exc()
                    sys.exit(-1)
        self.listener: Callable | None = None

    async def async_added_to_hass(self):
        """Subscribe to device events."""
        await super().async_added_to_hass()
        self.listener = self.hass.bus.async_listen(EVENT, self.event_handler)

    async def async_will_remove_from_hass(self):
        """Disconnect callbacks."""
        await super().async_will_remove_from_hass()
        if self.listener:
            self.listener()

    async def event_handler(self, e):
        pass

    @property
    def name(self):
        return self._name

    @name.setter
    def name(self, n):
        self._name = n

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

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return self.uuidAction
