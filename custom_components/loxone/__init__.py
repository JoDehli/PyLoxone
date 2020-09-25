"""
Component to create an interface to the Loxone Miniserver.

For more details about this component, please refer to the documentation at
https://home-assistant.io/components/loxone/
"""
import asyncio
import binascii
import datetime
import hashlib
import json
import logging
import os
import time
import traceback
import urllib.request as req
import uuid
from base64 import b64encode
from datetime import datetime
from struct import unpack
import queue
import requests_async as requests

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.helpers.entity import Entity
from homeassistant.config import get_default_config_dir
from homeassistant.const import (CONF_HOST, CONF_PASSWORD, CONF_PORT,
                                 CONF_USERNAME, EVENT_COMPONENT_LOADED,
                                 EVENT_HOMEASSISTANT_START,
                                 EVENT_HOMEASSISTANT_STOP)
from homeassistant.helpers.discovery import async_load_platform
from requests.auth import HTTPBasicAuth

REQUIREMENTS = ['websockets', "pycryptodome", "numpy", "requests_async"]

# Loxone constants
TIMEOUT = 10
KEEP_ALIVE_PERIOD = 240

IV_BYTES = 16
AES_KEY_SIZE = 32

SALT_BYTES = 16
SALT_MAX_AGE_SECONDS = 60 * 60
SALT_MAX_USE_COUNT = 30

TOKEN_PERMISSION = 4  # 2=web, 4=app
TOKEN_REFRESH_RETRY_COUNT = 5
# token will be refreshed 1 day before its expiration date
TOKEN_REFRESH_SECONDS_BEFORE_EXPIRY = 24 * 60 * 60  # 1 day
#  if can't determine token expiration date, it will be refreshed after 2 days
TOKEN_REFRESH_DEFAULT_SECONDS = 2 * 24 * 60 * 60  # 2 days

CMD_GET_PUBLIC_KEY = "jdev/sys/getPublicKey"
CMD_KEY_EXCHANGE = "jdev/sys/keyexchange/"
CMD_GET_KEY_AND_SALT = "jdev/sys/getkey2/"
CMD_REQUEST_TOKEN = "jdev/sys/gettoken/"
CMD_REQUEST_TOKEN_JSON_WEB = "jdev/sys/getjwt/"
CMD_GET_KEY = "jdev/sys/getkey"
CMD_AUTH_WITH_TOKEN = "authwithtoken/"
CMD_REFRESH_TOKEN = "jdev/sys/refreshtoken/"
CMD_REFRESH_TOKEN_JSON_WEB = "jdev/sys/refreshjwt/"
CMD_ENCRYPT_CMD = "jdev/sys/enc/"
CMD_ENABLE_UPDATES = "jdev/sps/enablebinstatusupdate"
CMD_GET_VISUAL_PASSWD = "jdev/sys/getvisusalt/"

DEFAULT_TOKEN_PERSIST_NAME = "lox_token.cfg"
ERROR_VALUE = -1
# End of loxone constants

_LOGGER = logging.getLogger(__name__)

DEFAULT_PORT = 8080
EVENT = 'loxone_event'
DOMAIN = 'loxone'
SENDDOMAIN = "loxone_send"
SECUREDSENDDOMAIN = "loxone_send_secured"
DEFAULT = ""
ATTR_UUID = 'uuid'
ATTR_VALUE = 'value'
ATTR_CODE = "code"
ATTR_COMMAND = "command"
CONF_SCENE_GEN = "generate_scenes"

LOXONE_PLATFORMS = ["sensor", "switch", "cover", "light", "scene", "alarm_control_panel", "climate"]

CONFIG_SCHEMA = vol.Schema({
    DOMAIN: vol.Schema({
        vol.Required(CONF_USERNAME): cv.string,
        vol.Required(CONF_PASSWORD): cv.string,
        vol.Required(CONF_HOST): cv.string,
        vol.Optional(CONF_PORT, default=DEFAULT_PORT): cv.port,
        vol.Optional(CONF_SCENE_GEN, default=True): cv.boolean,
    }),
}, extra=vol.ALLOW_EXTRA)


class loxApp(object):
    def __init__(self):
        self.host = None
        self.port = None
        self.loxapppath = "/data/LoxAPP3.json"

        self.lox_user = None
        self.lox_pass = None
        self.json = None
        self.responsecode = None
        self.version = None

    async def getJson (self):
        url_version = "http://{}:{}/jdev/cfg/version".format(self.host, self.port)
        version_resp = await requests.get(url_version,
                                          auth=HTTPBasicAuth(self.lox_user, self.lox_pass),
                                          verify=False, timeout=TIMEOUT)

        if version_resp.status_code == 200:
            vjson = version_resp.json()
            if 'LL' in vjson:
                if 'Code' in vjson['LL'] and 'value' in vjson['LL']:
                    self.version = [int(x) for x in vjson['LL']['value'].split(".")]

        url = "http://" + str(self.host) + ":" + str(self.port) + self.loxapppath
        my_response = await requests.get(url, auth=HTTPBasicAuth(self.lox_user, self.lox_pass),
                                         verify=False, timeout=TIMEOUT)
        if my_response.status_code == 200:
            self.json = my_response.json()
            if self.version is not None:
                self.json['softwareVersion'] = self.version
        else:
            self.json = None
        self.responsecode = my_response.status_code
        return self.responsecode


def get_room_name_from_room_uuid(lox_config, room_uuid):
    if "rooms" in lox_config:
        if room_uuid in lox_config['rooms']:
            return lox_config['rooms'][room_uuid]['name']

    return ""


def get_cat_name_from_cat_uuid(lox_config, cat_uuid):
    if "cats" in lox_config:
        if cat_uuid in lox_config['cats']:
            return lox_config['cats'][cat_uuid]['name']
    return ""

def get_all_roomcontroller_entities(json_data):
    return get_all(json_data, 'IRoomControllerV2')


def get_all_switch_entities(json_data):
    return get_all(json_data, ["Pushbutton", "Switch", "TimedSwitch", "Intercom"])


def get_all_covers(json_data):
    return get_all(json_data, ["Jalousie", "Gate", 'Window'])


def get_all_analog_info(json_data):
    return get_all(json_data, 'InfoOnlyAnalog')


def get_all_digital_info(json_data):
    return get_all(json_data, 'InfoOnlyDigital')


def get_all_light_controller(json_data):
    return get_all(json_data, 'LightControllerV2')


def get_all_alarm(json_data):
    return get_all(json_data, 'Alarm')


def get_all_dimmer(json_data):
    return get_all(json_data, 'Dimmer')


def get_all(json_data, name):
    controls = []
    if isinstance(name, list):
        for c in json_data['controls'].keys():
            if json_data['controls'][c]['type'] in name:
                controls.append(json_data['controls'][c])
    else:
        for c in json_data['controls'].keys():
            if json_data['controls'][c]['type'] == name:
                controls.append(json_data['controls'][c])
    return controls


async def async_setup(hass, config):
    """setup loxone"""

    try:
        lox_config = loxApp()
        lox_config.lox_user = config[DOMAIN][CONF_USERNAME]
        lox_config.lox_pass = config[DOMAIN][CONF_PASSWORD]
        lox_config.host = config[DOMAIN][CONF_HOST]
        lox_config.port = config[DOMAIN][CONF_PORT]
        request_code = await lox_config.getJson()

        if request_code == 200 or request_code == "200":
            hass.data[DOMAIN] = config[DOMAIN]
            hass.data[DOMAIN]['loxconfig'] = lox_config.json
            for platform in LOXONE_PLATFORMS:
                _LOGGER.debug("starting loxone {}...".format(platform))
                hass.async_create_task(
                    async_load_platform(hass, platform, DOMAIN, {}, config)
                )
            del lox_config
        else:
            _LOGGER.error("unable to connect to Loxone")
    except ConnectionError:
        _LOGGER.error("unable to connect to Loxone")
        return False

    lox = LoxWs(user=config[DOMAIN][CONF_USERNAME],
                password=config[DOMAIN][CONF_PASSWORD],
                host=config[DOMAIN][CONF_HOST],
                port=config[DOMAIN][CONF_PORT],
                loxconfig=config[DOMAIN]['loxconfig'])

    async def message_callback(message):
        hass.bus.async_fire(EVENT, message)

    async def start_loxone(event):
        await lox.start()

    async def stop_loxone(event):
        _ = await lox.stop()
        _LOGGER.debug(_)

    async def loxone_discovered(event):
        if "component" in event.data:
            if event.data['component'] == DOMAIN:
                try:
                    _LOGGER.info("loxone discovered")
                    await asyncio.sleep(0.1)
                    # await asyncio.sleep(0)
                    entity_ids = hass.states.async_all()
                    sensors_analog = []
                    sensors_digital = []
                    switches = []
                    covers = []
                    lights = []
                    climates = []

                    for s in entity_ids:
                        s_dict = s.as_dict()
                        attr = s_dict['attributes']
                        if "plattform" in attr and \
                                attr['plattform'] == DOMAIN:
                            if attr['device_typ'] == "analog_sensor":
                                sensors_analog.append(s_dict['entity_id'])
                            elif attr['device_typ'] == "digital_sensor":
                                sensors_digital.append(s_dict['entity_id'])
                            elif attr['device_typ'] == "Jalousie" or \
                                    attr['device_typ'] == "Gate":
                                covers.append(s_dict['entity_id'])
                            elif attr['device_typ'] == "Switch" or \
                                    attr['device_typ'] == "Pushbutton" or \
                                    attr['device_typ'] == "TimedSwitch":
                                switches.append(s_dict['entity_id'])
                            elif attr['device_typ'] == "LightControllerV2" or \
                                    attr['device_typ'] == "Dimmer":
                                lights.append(s_dict['entity_id'])
                            elif attr['device_typ'] == "IRoomControllerV2":
                                climates.append(s_dict['entity_id'])

                    sensors_analog.sort()
                    sensors_digital.sort()
                    covers.sort()
                    switches.sort()
                    lights.sort()
                    climates.sort()

                    async def create_loxone_group(object_id, name,
                                                  entity_names, visible=True,
                                                  view=False
                                                  ):
                        if visible:
                            visiblity = "true"
                        else:
                            visiblity = "false"
                        if view:
                            view_state = "true"
                        else:
                            view_state = "false"
                        command = {"object_id": object_id,
                                   "entities": entity_names,
                                   "name": name}

                        await hass.services.async_call("group", "set", command)

                    await create_loxone_group("loxone_analog",
                                              "Loxone Analog Sensors",
                                              sensors_analog, True, False)

                    await create_loxone_group("loxone_digital",
                                              "Loxone Digital Sensors",
                                              sensors_digital, True, False)

                    await create_loxone_group("loxone_switches",
                                              "Loxone Switches", switches,
                                              True, False)

                    await create_loxone_group("loxone_covers", "Loxone Covers",
                                              covers, True, False)

                    await create_loxone_group("loxone_lights", "Loxone Lights",
                                              lights, True, False)

                    await create_loxone_group("loxone_climates", "Loxone Room Controllers",
                                              climates, True, False)

                    await create_loxone_group("loxone_group", "Loxone Group",
                                              ["group.loxone_analog",
                                               "group.loxone_digital",
                                               "group.loxone_switches",
                                               "group.loxone_covers",
                                               "group.loxone_lights",
                                               "group.loxone_dimmers"
                                               ],
                                              True, True)
                except:
                    traceback.print_exc()

    res = False

    try:
        res = await lox.async_init()
    except ConnectionError:
        _LOGGER.error("Connection Error")

    if res is True:
        lox.message_call_back = message_callback
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_START, start_loxone)
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, stop_loxone)
        hass.bus.async_listen_once(EVENT_COMPONENT_LOADED, loxone_discovered)

        async def listen_loxone_send(event):
            """Listen for change Events from Loxone Components"""
            try:
                if event.event_type == SENDDOMAIN and isinstance(event.data,
                                                                 dict):
                    value = event.data.get(ATTR_VALUE, DEFAULT)
                    device_uuid = event.data.get(ATTR_UUID, DEFAULT)
                    await lox.send_websocket_command(device_uuid, value)

                elif event.event_type == SECUREDSENDDOMAIN and isinstance(event.data,
                                                                          dict):
                    value = event.data.get(ATTR_VALUE, DEFAULT)
                    device_uuid = event.data.get(ATTR_UUID, DEFAULT)
                    code = event.data.get(ATTR_CODE, DEFAULT)
                    await lox.send_secured__websocket_command(device_uuid, value, code)

            except ValueError:
                traceback.print_exc()

        hass.bus.async_listen(SENDDOMAIN, listen_loxone_send)
        hass.bus.async_listen(SECUREDSENDDOMAIN, listen_loxone_send)

        async def handle_websocket_command(call):
            """Handle websocket command services."""
            value = call.data.get(ATTR_VALUE, DEFAULT)
            device_uuid = call.data.get(ATTR_UUID, DEFAULT)
            await lox.send_websocket_command(device_uuid, value)

        hass.services.async_register(DOMAIN, 'event_websocket_command',
                                     handle_websocket_command)

    else:
        res = False
        _LOGGER.info("Error")
    return res


# Loxone Stuff
def gen_init_vec():
    from Crypto.Random import get_random_bytes
    return get_random_bytes(IV_BYTES)


def gen_key():
    from Crypto.Random import get_random_bytes
    return get_random_bytes(AES_KEY_SIZE)


def time_elapsed_in_seconds():
    return int(round(time.time()))


class LxJsonKeySalt:
    def __init__(self):
        self.key = None
        self.salt = None
        self.response = None
        self.time_elapsed_in_seconds = None

    def read_user_salt_responce(self, reponse):
        js = json.loads(reponse, strict=False)
        value = js['LL']['value']
        self.key = value['key']
        self.salt = value['salt']


class LxToken:
    def __init__(self, token="", vaild_until=""):
        self._token = token
        self._vaild_until = vaild_until

    def get_seconds_to_expire(self):
        start_date = int(
            datetime.strptime("1.1.2009", "%d.%m.%Y").strftime('%s'))
        start_date = int(start_date) + self._vaild_until
        return start_date - int(round(time.time()))

    @property
    def token(self):
        return self._token

    @property
    def vaild_until(self):
        return self._vaild_until

    def set_vaild_until(self, value):
        self._vaild_until = value

    def set_token(self, token):
        self._token = token


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

    @property
    def name(self):
        return self._name

    @name.setter
    def name(self, n):
        self._name = n

    @staticmethod
    def _clean_unit(lox_format):
        cleaned_fields = []
        fields = lox_format.split(" ")
        for f in fields:
            _ = f.strip()
            if len(_) > 0:
                cleaned_fields.append(_)

        if len(cleaned_fields) > 1:
            unit = cleaned_fields[1]
            if unit == "%%":
                unit = "%"
            return unit
        return None

    @staticmethod
    def _get_format(lox_format):
        cleaned_fields = []
        fields = lox_format.split(" ")
        for f in fields:
            _ = f.strip()
            if len(_) > 0:
                cleaned_fields.append(_)

        if len(cleaned_fields) > 1:
            return cleaned_fields[0]
        return None

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return self.uuidAction


class LoxWs:
    def __init__(self, user=None,
                 password=None,
                 host="http://192.168.1.225 ",
                 port="8080", token_persist_filename=None,
                 loxconfig=None):
        self._username = user
        self._pasword = password
        self._host = host
        self._port = port
        self._token_refresh_count = TOKEN_REFRESH_RETRY_COUNT
        self._token_persist_filename = token_persist_filename
        self._loxconfig = loxconfig
        self._version = 0
        if self._loxconfig is not None:
            if 'softwareVersion' in self._loxconfig:
                vers = self._loxconfig['softwareVersion']
                if isinstance(vers, list) and len(vers) >= 2:
                    try:
                        self._version = float("{}.{}".format(vers[0], vers[1]))
                    except ValueError:
                        self._version = 0

        if self._token_persist_filename is None:
            self._token_persist_filename = DEFAULT_TOKEN_PERSIST_NAME

        self._iv = gen_init_vec()
        self._key = gen_key()
        self._token = LxToken()
        self._token_valid_until = 0
        self._salt = ""
        self._salt_uesed_count = 0
        self._salt_time_stamp = 0
        self._public_key = None
        self._rsa_cipher = None
        self._session_key = None
        self._ws = None
        self._current_message_typ = None
        self._encryption_ready = False
        self._visual_hash = None
        self._keep_alive_task = None

        self.message_call_back = None
        self._pending = []

        self.connect_retries = 10
        self.connect_delay = 30
        self.state = "CLOSED"
        self._secured_queue = queue.Queue(maxsize=1)

    @property
    def key(self):
        return self._key

    @property
    def iv(self):
        return self._iv

    async def refresh_token(self):
        while True:
            seconds_to_refresh = self._token.get_seconds_to_expire()
            await asyncio.sleep(seconds_to_refresh)
            await self._refresh_token()

    async def decrypt(self, message):
        pass

    async def _refresh_token(self):
        from Crypto.Hash import SHA1, HMAC
        command = "{}".format(CMD_GET_KEY)
        enc_command = await self.encrypt(command)
        await self._ws.send(enc_command)
        message = await self._ws.recv()
        resp_json = json.loads(message)
        token_hash = None
        if 'LL' in resp_json:
            if "value" in resp_json['LL']:
                key = resp_json['LL']['value']
                if key == "":
                    digester = HMAC.new(binascii.unhexlify(key),
                                        self._token.token.encode("utf-8"), SHA1)
                    token_hash = digester.hexdigest()

        if token_hash is not None:
            if self._version < 10.2:
                command = "{}{}/{}".format(CMD_REFRESH_TOKEN, token_hash,
                                           self._username)
            else:
                command = "{}{}/{}".format(CMD_REFRESH_TOKEN_JSON_WEB, token_hash,
                                           self._username)

            enc_command = await self.encrypt(command)
            await self._ws.send(enc_command)
            message = await self._ws.recv()
            resp_json = json.loads(message)

            _LOGGER.debug("Seconds before refresh: {}".format(
                self._token.get_seconds_to_expire()))

            if 'LL' in resp_json:
                if "value" in resp_json['LL']:
                    if "validUntil" in resp_json['LL']['value']:
                        self._token.set_vaild_until(
                            resp_json['LL']['value']['validUntil'])
            self.save_token()

    async def start(self):
        consumer_task = asyncio.ensure_future(self.ws_listen())
        keep_alive_task = asyncio.ensure_future(
            self.keep_alive(KEEP_ALIVE_PERIOD))
        refresh_token_task = asyncio.ensure_future(self.refresh_token())

        self._pending.append(consumer_task)
        self._pending.append(keep_alive_task)
        self._pending.append(refresh_token_task)

        done, pending = await asyncio.wait(
            [consumer_task, keep_alive_task, refresh_token_task],
            return_when=asyncio.FIRST_COMPLETED,
        )

        for task in pending:
            task.cancel()

        if self.state != "STOPPING":
            self.state == "CONNECTING"
            self._pending = []
            for i in range(self.connect_retries):
                _LOGGER.debug("reconnect: {} from {}".format(i + 1, self.connect_retries))
                await self.stop()
                await asyncio.sleep(self.connect_delay)
                res = await self.reconnect()
                if res is True:
                    await self.start()
                    break

    async def reconnect(self):
        return await self.async_init()

    async def stop(self):
        try:
            self.state = "STOPPING"
            if not self._ws.closed:
                await self._ws.close()
            return 1
        except:
            return -1

    async def keep_alive(self, second):
        while True:
            await asyncio.sleep(second)
            if self._encryption_ready:
                await self._ws.send("keepalive")

    async def send_secured(self, device_uuid, value, code):
        from Crypto.Hash import SHA1, HMAC
        pwd_hash_str = code + ":" + self._visual_hash.salt
        m = hashlib.sha1()
        m.update(pwd_hash_str.encode('utf-8'))
        pwd_hash = m.hexdigest().upper()
        digester = HMAC.new(binascii.unhexlify(self._visual_hash.key),
                            pwd_hash.encode("utf-8"), SHA1)

        command = "jdev/sps/ios/{}/{}/{}".format(digester.hexdigest(), device_uuid, value)
        await self._ws.send(command)

    async def send_secured__websocket_command(self, device_uuid, value, code):
        self._secured_queue.put((device_uuid, value, code))
        await self.get_visual_hash()

    async def send_websocket_command(self, device_uuid, value):
        """Send a websocket command to the Miniserver."""
        command = "jdev/sps/io/{}/{}".format(device_uuid, value)
        _LOGGER.debug("send command: {}".format(command))
        await self._ws.send(command)

    async def async_init(self):
        import websockets as wslib
        _LOGGER.debug("try to read token")
        # Read token from file
        try:
            await self.get_token_from_file()
        except IOError:
            _LOGGER.debug("error token read")

        # Get public key from Loxone
        resp = await self.get_public_key()

        if not resp:
            return ERROR_VALUE

        # Init resa cipher
        rsa_gen = self.init_rsa_cipher()
        if not rsa_gen:
            return ERROR_VALUE

        # Generate session key
        session_gen = self.generate_session_key()
        if not session_gen:
            return ERROR_VALUE

        # Exchange keys
        try:
            self._ws = await wslib.connect(
                "ws://{}:{}/ws/rfc6455".format(self._host, self._port),
                timeout=TIMEOUT)
            await self._ws.send(
                "{}{}".format(CMD_KEY_EXCHANGE, self._session_key))

            message = await self._ws.recv()
            await self.parse_loxone_message(message)
            if self._current_message_typ != 0:
                _LOGGER.debug("error by getting the session key response...")
                return ERROR_VALUE

            message = await self._ws.recv()
            resp_json = json.loads(message)
            if 'LL' in resp_json:
                if "Code" in resp_json['LL']:
                    if resp_json['LL']['Code'] != '200':
                        return ERROR_VALUE
            else:
                return ERROR_VALUE

        except ConnectionError:
            _LOGGER.debug("connection error...")
            return ERROR_VALUE

        self._encryption_ready = True

        if self._token is None or self._token.token == "" or \
                self._token.get_seconds_to_expire() < 300:
            res = await self.acquire_token()
        else:
            res = await self.use_token()

        if res is ERROR_VALUE:
            return ERROR_VALUE

        command = "{}".format(CMD_ENABLE_UPDATES)
        enc_command = await self.encrypt(command)
        await self._ws.send(enc_command)
        _ = await self._ws.recv()
        _ = await self._ws.recv()

        self.state = "CONNECTED"
        return True

    async def get_visual_hash(self):
        command = "{}{}".format(CMD_GET_VISUAL_PASSWD, self._username)
        enc_command = await self.encrypt(command)
        await self._ws.send(enc_command)

    async def ws_listen(self):
        """Listen to all commands from the Miniserver."""
        try:
            while True:
                message = await self._ws.recv()
                await self._async_process_message(message)
                await asyncio.sleep(0)
        except:
            pass

    async def _async_process_message(self, message):
        """Process the messages."""
        if len(message) == 8:
            unpacked_data = unpack('ccccI', message)
            self._current_message_typ = int.from_bytes(unpacked_data[1],
                                                       byteorder='big')
            if self._current_message_typ == 6:
                _LOGGER.debug("Keep alive response received...")
        else:
            parsed_data = await self._parse_loxone_message(message)
            _LOGGER.debug("message [type:{}]):{}".format(self._current_message_typ, parsed_data))

            try:
                resp_json = json.loads(parsed_data)
            except TypeError:
                resp_json = None

            # Visual hash and key response
            if resp_json is not None and 'LL' in resp_json:
                if "control" in resp_json['LL'] and "code" in resp_json['LL'] and resp_json['LL']['code'] in [200,
                                                                                                              '200']:
                    if 'value' in resp_json['LL']:
                        if 'key' in resp_json['LL']['value'] and 'salt' in resp_json['LL']['value']:
                            key_and_salt = LxJsonKeySalt()
                            key_and_salt.key = resp_json['LL']['value']['key']
                            key_and_salt.salt = resp_json['LL']['value']['salt']
                            key_and_salt.time_elapsed_in_seconds = time_elapsed_in_seconds()
                            self._visual_hash = key_and_salt

                            while not self._secured_queue.empty():
                                secured_message = self._secured_queue.get()
                                await self.send_secured(secured_message[0], secured_message[1], secured_message[2])

            if self.message_call_back is not None:
                if "LL" not in parsed_data and parsed_data != {}:
                    await self.message_call_back(parsed_data)
            self._current_message_typ = None
            await asyncio.sleep(0)

    async def _parse_loxone_message(self, message):
        """Parser of the Loxone message."""
        event_dict = {}
        if self._current_message_typ == 0:
            event_dict = message
        elif self._current_message_typ == 1:
            pass
        elif self._current_message_typ == 2:
            length = len(message)
            num = length / 24
            start = 0
            end = 24
            for i in range(int(num)):
                packet = message[start:end]
                event_uuid = uuid.UUID(bytes_le=packet[0:16])
                fields = event_uuid.urn.replace("urn:uuid:", "").split("-")
                uuidstr = "{}-{}-{}-{}{}".format(
                    fields[0], fields[1], fields[2], fields[3], fields[4])
                value = unpack('d', packet[16:24])[0]
                event_dict[uuidstr] = value
                start += 24
                end += 24
        elif self._current_message_typ == 3:
            from math import floor
            start = 0

            def get_text(message, start, offset):
                first = start
                second = start + offset
                event_uuid = uuid.UUID(bytes_le=message[first:second])
                first += offset
                second += offset

                icon_uuid_fields = event_uuid.urn.replace("urn:uuid:", "").split("-")
                uuidstr = "{}-{}-{}-{}{}".format(
                    icon_uuid_fields[0], icon_uuid_fields[1], icon_uuid_fields[2], icon_uuid_fields[3],
                    icon_uuid_fields[4])

                icon_uuid = uuid.UUID(bytes_le=message[first:second])
                icon_uuid_fields = icon_uuid.urn.replace("urn:uuid:", "").split("-")
                uuidiconstr = "{}-{}-{}-{}{}".format(icon_uuid_fields[0], icon_uuid_fields[1], icon_uuid_fields[2],
                                                     icon_uuid_fields[3], icon_uuid_fields[4])

                first = second
                second += 4

                text_length = unpack('<I', message[first:second])[0]

                first = second
                second = first + text_length
                message_str = unpack('{}s'.format(text_length), message[first:second])[0]
                start += (floor((4 + text_length + 16 + 16 - 1) / 4) + 1) * 4
                event_dict[uuidstr] = message_str.decode("utf-8")
                return start

            while start < len(message):
                start = get_text(message, start, 16)

        elif self._current_message_typ == 6:
            event_dict["keep_alive"] = "received"
        else:
            self._current_message_typ = 7
        return event_dict

    async def use_token(self):
        token_hash = await self.hash_token()
        if token_hash is ERROR_VALUE:
            return ERROR_VALUE
        command = "{}{}/{}".format(CMD_AUTH_WITH_TOKEN, token_hash,
                                   self._username)
        enc_command = await self.encrypt(command)
        await self._ws.send(enc_command)
        message = await self._ws.recv()
        await self.parse_loxone_message(message)
        message = await self._ws.recv()
        resp_json = json.loads(message)
        if 'LL' in resp_json:
            if "code" in resp_json['LL']:
                if resp_json['LL']['code'] == "200":
                    if "value" in resp_json['LL']:
                        self._token.set_vaild_until(
                            resp_json['LL']['value']['validUntil'])
                    return True
        return ERROR_VALUE

    async def hash_token(self):
        try:
            from Crypto.Hash import SHA1, HMAC
            command = "{}".format(CMD_GET_KEY)
            enc_command = await self.encrypt(command)
            await self._ws.send(enc_command)
            message = await self._ws.recv()
            await self.parse_loxone_message(message)
            message = await self._ws.recv()
            resp_json = json.loads(message)
            if 'LL' in resp_json:
                if "value" in resp_json['LL']:
                    key = resp_json['LL']['value']
                    if key != "":
                        digester = HMAC.new(binascii.unhexlify(key),
                                            self._token.token.encode("utf-8"), SHA1)
                        return digester.hexdigest()
            return ERROR_VALUE
        except:
            return ERROR_VALUE

    async def acquire_token(self):
        _LOGGER.debug("acquire_tokend")
        command = "{}{}".format(CMD_GET_KEY_AND_SALT, self._username)
        enc_command = await self.encrypt(command)

        if not self._encryption_ready or self._ws is None:
            return ERROR_VALUE

        await self._ws.send(enc_command)
        message = await self._ws.recv()
        await self.parse_loxone_message(message)

        message = await self._ws.recv()

        key_and_salt = LxJsonKeySalt()
        key_and_salt.read_user_salt_responce(message)

        new_hash = self.hash_credentials(key_and_salt)

        if self._version < 10.2:
            command = "{}{}/{}/{}/edfc5f9a-df3f-4cad-9dddcdc42c732be2" \
                      "/homeassistant".format(CMD_REQUEST_TOKEN, new_hash,
                                              self._username, TOKEN_PERMISSION)
        else:
            command = "{}{}/{}/{}/edfc5f9a-df3f-4cad-9dddcdc42c732be2" \
                      "/homeassistant".format(CMD_REQUEST_TOKEN_JSON_WEB,
                                              new_hash, self._username,
                                              TOKEN_PERMISSION)

        enc_command = await self.encrypt(command)
        await self._ws.send(enc_command)
        message = await self._ws.recv()
        await self.parse_loxone_message(message)
        message = await self._ws.recv()

        resp_json = json.loads(message)
        if 'LL' in resp_json:
            if "value" in resp_json['LL']:
                if "token" in resp_json['LL']['value'] and "validUntil" in \
                        resp_json['LL']['value']:
                    self._token = LxToken(resp_json['LL']['value']['token'],
                                          resp_json['LL']['value'][
                                              'validUntil'])

        if self.save_token() == ERROR_VALUE:
            return ERROR_VALUE
        return True

    def load_token(self):
        try:
            persist_token = os.path.join(get_default_config_dir(),
                                         self._token_persist_filename)
            try:
                with open(persist_token) as f:
                    try:
                        dict_token = json.load(f)
                    except ValueError:
                        return ERROR_VALUE
            except FileNotFoundError:
                with open(self._token_persist_filename) as f:
                    try:
                        dict_token = json.load(f)
                    except ValueError:
                        return ERROR_VALUE
            self._token.set_token(dict_token['_token'])
            self._token.set_vaild_until(dict_token['_valid_until'])
            _LOGGER.debug("load_token successfully...")
            return True
        except IOError:
            _LOGGER.debug("error load_token...")
            return ERROR_VALUE

    def save_token(self):
        try:
            persist_token = os.path.join(get_default_config_dir(),
                                         self._token_persist_filename)

            dict_token = {"_token": self._token.token,
                          "_valid_until": self._token.vaild_until}
            try:
                with open(persist_token, "w") as write_file:
                    json.dump(dict_token, write_file)
            except FileNotFoundError:
                with open(self._token_persist_filename, "w") as write_file:
                    json.dump(dict_token, write_file)

            _LOGGER.debug("save_token successfully...")
            return True
        except IOError:
            _LOGGER.debug("error save_token...")
            _LOGGER.debug("tokenpath: {}".format(persist_token))
            return ERROR_VALUE

    async def encrypt(self, command):
        from Crypto.Util import Padding
        if not self._encryption_ready:
            return command
        if self._salt != "" and self.new_salt_needed():
            prev_salt = self._salt
            self._salt = self.genarate_salt()
            s = "nextSalt/{}/{}/{}\0".format(prev_salt, self._salt, command)
        else:
            if self._salt == "":
                self._salt = self.genarate_salt()
            s = "salt/{}/{}\0".format(self._salt, command)
        s = Padding.pad(bytes(s, "utf-8"), 16)
        aes_cipher = self.get_new_aes_chiper()
        encrypted = aes_cipher.encrypt(s)
        encoded = b64encode(encrypted)
        encoded_url = req.pathname2url(encoded.decode("utf-8"))
        return CMD_ENCRYPT_CMD + encoded_url

    def hash_credentials(self, key_salt):
        try:
            from Crypto.Hash import SHA1, HMAC
            pwd_hash_str = self._pasword + ":" + key_salt.salt
            m = hashlib.sha1()
            m.update(pwd_hash_str.encode('utf-8'))
            pwd_hash = m.hexdigest().upper()
            pwd_hash = self._username + ":" + pwd_hash
            digester = HMAC.new(binascii.unhexlify(key_salt.key),
                                pwd_hash.encode("utf-8"), SHA1)
            _LOGGER.debug("hash_credentials successfully...")
            return digester.hexdigest()
        except ValueError:
            _LOGGER.debug("error hash_credentials...")
            return None

    def genarate_salt(self):
        from Crypto.Random import get_random_bytes
        salt = get_random_bytes(SALT_BYTES)
        salt = binascii.hexlify(salt).decode("utf-8")
        salt = req.pathname2url(salt)
        self._salt_time_stamp = time_elapsed_in_seconds()
        self._salt_uesed_count = 0
        return salt

    def new_salt_needed(self):
        self._salt_uesed_count += 1
        if self._salt_uesed_count > SALT_MAX_USE_COUNT or time_elapsed_in_seconds() - self._salt_time_stamp > SALT_MAX_AGE_SECONDS:
            return True
        return False

    async def parse_loxone_message(self, message):
        if len(message) == 8:
            try:
                unpacked_data = unpack('ccccI', message)
                self._current_message_typ = int.from_bytes(unpacked_data[1],
                                                           byteorder='big')
                _LOGGER.debug("parse_loxone_message successfully...")
            except ValueError:
                _LOGGER.debug("error parse_loxone_message...")

    def generate_session_key(self):
        try:
            aes_key = binascii.hexlify(self._key).decode("utf-8")
            iv = binascii.hexlify(self._iv).decode("utf-8")
            sess = aes_key + ":" + iv
            sess = self._rsa_cipher.encrypt(bytes(sess, "utf-8"))
            self._session_key = b64encode(sess).decode("utf-8")
            _LOGGER.debug("generate_session_key successfully...")
            return True
        except KeyError:
            _LOGGER.debug("error generate_session_key...")
            return False

    def get_new_aes_chiper(self):
        try:
            from Crypto.Cipher import AES
            _new_aes = AES.new(self._key, AES.MODE_CBC, self._iv)
            _LOGGER.debug("get_new_aes_chiper successfully...")
            return _new_aes
        except ValueError:
            _LOGGER.debug("error get_new_aes_chiper...")
            return None

    def init_rsa_cipher(self):
        try:
            from Crypto.Cipher import PKCS1_v1_5
            from Crypto.PublicKey import RSA
            self._public_key = self._public_key.replace(
                "-----BEGIN CERTIFICATE-----",
                "-----BEGIN PUBLIC KEY-----\n")
            public_key = self._public_key.replace(
                "-----END CERTIFICATE-----",
                "\n-----END PUBLIC KEY-----\n")
            self._rsa_cipher = PKCS1_v1_5.new(RSA.importKey(public_key))
            _LOGGER.debug("init_rsa_cipher successfully...")
            return True
        except KeyError:
            _LOGGER.debug("init_rsa_cipher error...")
            _LOGGER.debug("{}".format(traceback.print_exc()))
            return False

    async def get_public_key(self):
        command = "http://{}:{}/{}".format(self._host, self._port,
                                           CMD_GET_PUBLIC_KEY)
        _LOGGER.debug("try to get public key: {}".format(command))

        try:
            response = await requests.get(command, auth=(self._username, self._pasword), timeout=TIMEOUT)
        except:
            return False

        if response.status_code != 200:
            _LOGGER.debug(
                "error get_public_key: {}".format(response.status_code))
            return False
        try:
            resp_json = json.loads(response.text)
            if 'LL' in resp_json and 'value' in resp_json['LL']:
                self._public_key = resp_json['LL']['value']
                _LOGGER.debug("get_public_key successfully...")
            else:
                _LOGGER.debug("public key load error")
                return False
        except ValueError:
            _LOGGER.debug("public key load error")
            return False
        return True

    async def get_token_from_file(self):
        try:
            persist_token = os.path.join(get_default_config_dir(),
                                         self._token_persist_filename)
            if os.path.exists(persist_token):
                if self.load_token():
                    _LOGGER.debug(
                        "token successfully loaded from file: {}".format(
                            persist_token))
        except FileExistsError:
            _LOGGER.debug("error loading token {}".format(persist_token))
            _LOGGER.debug("{}".format(traceback.print_exc()))
