"""
Component to create an interface to the Loxone Miniserver.

For more details about this component, please refer to the documentation at
https://github.com/JoDehli/PyLoxone
"""
import asyncio
import logging
import re
import traceback

import homeassistant.components.group as group
import voluptuous as vol
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_USERNAME,
    EVENT_COMPONENT_LOADED,
    EVENT_HOMEASSISTANT_START,
    EVENT_HOMEASSISTANT_STOP,
)

from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.discovery import async_load_platform
from homeassistant.helpers.entity import Entity

from .helpers import get_miniserver_type
from .miniserver import MiniServer, get_miniserver_from_config_entry

REQUIREMENTS = ["websockets", "pycryptodome", "numpy", "requests_async"]

from .const import (
    ATTR_CODE,
    ATTR_COMMAND,
    ATTR_UUID,
    ATTR_VALUE,
    DOMAIN_DEVICES,
    SECUREDSENDDOMAIN,
    SENDDOMAIN,
    CONF_LIGHTCONTROLLER_SUBCONTROLS_GEN,
    CONF_SCENE_GEN_DELAY,
    cfmt,
    LOXONE_PLATFORMS,
    CONF_SCENE_GEN,
    DEFAULT,
    DOMAIN,
    DEFAULT_DELAY_SCENE,
    DEFAULT_PORT,
    EVENT,
)

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


async def async_unload_entry(hass, config_entry):
    """Restart of Home Assistant needed."""
    return False


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
    _LOGGER.debug("Migrating from version %s", config_entry.version)
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


async def async_setup_entry(hass, config_entry):
    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = {}

    if not config_entry.options:
        await async_set_options(hass, config_entry)

    miniserver = MiniServer(hass, config_entry)

    if not await miniserver.async_setup():
        return False

    for platform in LOXONE_PLATFORMS:
        _LOGGER.debug("starting loxone {}...".format(platform))
        hass.async_create_task(
            hass.config_entries.async_forward_entry_setup(config_entry, platform)
        )
        hass.async_create_task(
            async_load_platform(hass, platform, DOMAIN, {}, config_entry)
        )

    config_entry.add_update_listener(async_config_entry_updated)

    new_data = _UNDEF

    if config_entry.unique_id is None:
        hass.config_entries.async_update_entry(
            config_entry, unique_id=miniserver.serial, data=new_data
        )
        # Workaround
        await asyncio.sleep(5)

    hass.data[DOMAIN][config_entry.unique_id] = miniserver

    await miniserver.async_update_device_registry()

    async def message_callback(message):
        """Fire message on HomeAssistant Bus."""
        hass.bus.async_fire(EVENT, message)

    async def handle_websocket_command(call):
        """Handle websocket command services."""
        value = call.data.get(ATTR_VALUE, DEFAULT)
        device_uuid = call.data.get(ATTR_UUID, DEFAULT)
        await miniserver.api.send_websocket_command(device_uuid, value)

    async def loxone_discovered(event):
        if "component" in event.data:
            if event.data["component"] == DOMAIN:
                try:
                    _LOGGER.info("loxone discovered")
                    await asyncio.sleep(0.1)
                    entity_ids = hass.states.async_all()
                    sensors_analog = []
                    sensors_digital = []
                    switches = []
                    covers = []
                    lights = []
                    climates = []

                    for s in entity_ids:
                        s_dict = s.as_dict()
                        attr = s_dict["attributes"]
                        if "plattform" in attr and attr["plattform"] == DOMAIN:
                            device_typ = attr.get("device_typ", "")
                            if device_typ == "analog_sensor":
                                sensors_analog.append(s_dict["entity_id"])
                            elif device_typ == "digital_sensor":
                                sensors_digital.append(s_dict["entity_id"])
                            elif device_typ in ["Jalousie", "Gate", "Window"]:
                                covers.append(s_dict["entity_id"])
                            elif device_typ in ["Switch", "Pushbutton", "TimedSwitch"]:
                                switches.append(s_dict["entity_id"])
                            elif device_typ in ["LightControllerV2", "Dimmer"]:
                                lights.append(s_dict["entity_id"])
                            elif device_typ == "IRoomControllerV2":
                                climates.append(s_dict["entity_id"])

                    sensors_analog.sort()
                    sensors_digital.sort()
                    covers.sort()
                    switches.sort()
                    lights.sort()
                    climates.sort()

                    await group.Group.async_create_group(
                        hass,
                        "Loxone Analog Sensors",
                        object_id="loxone_analog",
                        entity_ids=sensors_analog,
                    )

                    await group.Group.async_create_group(
                        hass,
                        "Loxone Digital Sensors",
                        object_id="loxone_digital",
                        entity_ids=sensors_digital,
                    )

                    await group.Group.async_create_group(
                        hass,
                        "Loxone Switches",
                        object_id="loxone_switches",
                        entity_ids=switches,
                    )

                    await group.Group.async_create_group(
                        hass,
                        "Loxone Covers",
                        object_id="loxone_covers",
                        entity_ids=covers,
                    )

                    await group.Group.async_create_group(
                        hass,
                        "Loxone Lights",
                        object_id="loxone_lights",
                        entity_ids=lights,
                    )

                    await group.Group.async_create_group(
                        hass,
                        "Loxone Room Controllers",
                        object_id="loxone_climates",
                        entity_ids=climates,
                    )

                    await hass.async_block_till_done()

                    await group.Group.async_create_group(
                        hass,
                        "Loxone Group",
                        object_id="loxone_group",
                        entity_ids=[
                            "group.loxone_analog",
                            "group.loxone_digital",
                            "group.loxone_switches",
                            "group.loxone_covers",
                            "group.loxone_lights",
                        ],
                    )
                except:
                    traceback.print_exc()

    await miniserver.async_set_callback(message_callback)

    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_START, miniserver.start_loxone)
    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, miniserver.stop_loxone)
    hass.bus.async_listen_once(EVENT_COMPONENT_LOADED, loxone_discovered)

    hass.bus.async_listen(SENDDOMAIN, miniserver.listen_loxone_send)
    hass.bus.async_listen(SECUREDSENDDOMAIN, miniserver.listen_loxone_send)

    hass.services.async_register(
        DOMAIN, "event_websocket_command", handle_websocket_command
    )

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
                except:
                    traceback.print_exc()
                    import sys

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
