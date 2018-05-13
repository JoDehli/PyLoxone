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
import pickle
import time
import traceback
import urllib.request as req
import uuid
from base64 import b64encode
from datetime import datetime
from struct import unpack

from homeassistant.config import get_default_config_dir
import homeassistant.helpers.config_validation as cv
import requests
import voluptuous as vol

from homeassistant.const import CONF_HOST, CONF_PORT, CONF_USERNAME, \
    CONF_PASSWORD, EVENT_HOMEASSISTANT_START, \
    EVENT_HOMEASSISTANT_STOP
from homeassistant.helpers import discovery
from requests.auth import HTTPBasicAuth

REQUIREMENTS = ['websockets==4.0.1', "pycryptodome==3.6.1"]
# Loxone constants
TIMEOUT = 10
KEEP_ALIVE_PERIOD = 240

IV_BYTES = 16
AES_KEY_SIZE = 32

SALT_BYTES = 16
SALT_MAX_AGE_SECONDS = 60 * 60
SALT_MAX_USE_COUNT = 30

TOKEN_PERMISSION = 2  # 2=web, 4=app
TOKEN_REFRESH_RETRY_COUNT = 5
# token will be refreshed 1 day before its expiration date
TOKEN_REFRESH_SECONDS_BEFORE_EXPIRY = 24 * 60 * 60  # 1 day
#  if can't determine token expiration date, it will be refreshed after 2 days
TOKEN_REFRESH_DEFAULT_SECONDS = 2 * 24 * 60 * 60  # 2 days

CMD_GET_PUBLIC_KEY = "jdev/sys/getPublicKey"
CMD_KEY_EXCHANGE = "jdev/sys/keyexchange/"
CMD_GET_KEY_AND_SALT = "jdev/sys/getkey2/"
CMD_REQUEST_TOKEN = "jdev/sys/gettoken/"
CMD_GET_KEY = "jdev/sys/getkey"
CMD_AUTH_WITH_TOKEN = "authwithtoken/"
CMD_REFRESH_TOKEN = "jdev/sys/refreshtoken/"
CMD_ENCRYPT_CMD = "jdev/sys/enc/"
CMD_ENABLE_UPDATES = "jdev/sps/enablebinstatusupdate"

DEFAULT_TOKEN_PERSIST_NAME = "lox_token.p"
ERROR_VALUE = -1
# End of loxone constants

_LOGGER = logging.getLogger(__name__)

DEFAULT_PORT = 8080
EVENT = 'loxone_event'
DOMAIN = 'loxone'
SENDDOMAIN = "loxone_send"
DEFAULT = ""
ATTR_UUID = 'uuid'
ATTR_VALUE = 'value'
ATTR_COMMAND = "command"



CONFIG_SCHEMA = vol.Schema({
    DOMAIN: vol.Schema({
        vol.Required(CONF_USERNAME): cv.string,
        vol.Required(CONF_PASSWORD): cv.string,
        vol.Required(CONF_HOST): cv.string,
        vol.Optional(CONF_PORT, default=DEFAULT_PORT): cv.port,
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

    def getJson(self):
        url = "http://" + str(self.host) + ":" + str(
            self.port) + self.loxapppath
        my_response = requests.get(url, auth=HTTPBasicAuth(self.lox_user,
                                                           self.lox_pass),
                                   verify=False)
        if my_response.status_code == 200:
            self.json = my_response.json()
        else:
            self.json = None
        self.responsecode = my_response.status_code
        return self.responsecode

    def getAllAnalogInfo(self):
        controls = []
        for c in self.json['controls'].keys():
            if self.json['controls'][c]['type'] == "InfoOnlyAnalog":
                controls.append(self.json['controls'][c])
        return controls


async def async_setup(hass, config):
    """setup loxone"""
    try:
        lox_config = loxApp()
        lox_config.lox_user = config[DOMAIN][CONF_USERNAME]
        lox_config.lox_pass = config[DOMAIN][CONF_PASSWORD]
        lox_config.host = config[DOMAIN][CONF_HOST]
        lox_config.port = config[DOMAIN][CONF_PORT]
        request_code = lox_config.getJson()
        if request_code == 200 or request_code == "200":
            hass.data[DOMAIN] = config[DOMAIN]
            hass.data[DOMAIN]['loxconfig'] = lox_config.json
            discovery.load_platform(hass, "sensor", "loxone")
            discovery.load_platform(hass, "switch", "loxone")
            discovery.load_platform(hass, "cover", "loxone")
            del lox_config
        else:
            _LOGGER.error("Unable to connect to Loxone")
    except ConnectionError:
        _LOGGER.error("Unable to connect to Loxone")
        return False

    lox = LoxWs(user=config[DOMAIN][CONF_USERNAME],
                password=config[DOMAIN][CONF_PASSWORD],
                host=config[DOMAIN][CONF_HOST],
                port=config[DOMAIN][CONF_PORT])

    async def message_callback(message):
        hass.bus.async_fire(EVENT, message)

    async def start_loxone(event):
        await lox.start()

    async def stop_loxone(event):
        await lox.stop()
    try:
        res = await lox.async_init()
    except:
        _LOGGER.error("Connection Error ", res)

    if res:
        lox.message_call_back = message_callback
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_START, start_loxone)
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, stop_loxone)

        async def listen_loxone_send(event):
            """Listen for change Events from Loxone Components"""
            try:
                if event.event_type == SENDDOMAIN and isinstance(event.data,
                                                                 dict):
                    value = event.data.get(ATTR_VALUE, DEFAULT)
                    device_uuid = event.data.get(ATTR_UUID, DEFAULT)
                    await lox.send_websocket_command(device_uuid, value)
            except ValueError:
                traceback.print_exc()

        hass.bus.async_listen(SENDDOMAIN, listen_loxone_send)

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


class LoxWs:
    def __init__(self, user=None,
                 password=None,
                 host="http://192.168.1.225 ",
                 port="8080", token_persist_filename=None):
        self._username = user
        self._pasword = password
        self._host = host
        self._port = port
        self._token_refresh_count = TOKEN_REFRESH_RETRY_COUNT
        self._token_persist_filename = token_persist_filename

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

        self._keep_alive_task = None

        self.message_call_back = None
        self._pending = []

        self.connect_retries = 10
        self.connect_delay = 30
        self.state = "CLOSED"

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
        from Crypto.Hash import SHA, HMAC
        command = "{}".format(CMD_GET_KEY)
        enc_command = await self.encrypt(command)
        await self._ws.send(enc_command)
        message = await self._ws.recv()
        resp_json = json.loads(message)
        token_hash = None
        if 'LL' in resp_json:
            if "value" in resp_json['LL']:
                key = resp_json['LL']['value']
                if key is not "":
                    digester = HMAC.new(binascii.unhexlify(key),
                                        self._token.token.encode("utf-8"), SHA)
                    token_hash = digester.hexdigest()

        if token_hash is not None:
            command = "{}{}/{}".format(CMD_REFRESH_TOKEN, token_hash,
                                       self._username)
            enc_command = await self.encrypt(command)
            await self._ws.send(enc_command)
            message = await self._ws.recv()
            resp_json = json.loads(message)
            print("Seconds before Refresh: ",
                  self._token.get_seconds_to_expire())
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

        if self.state is not "STOPPING":
            self.state == "CONNECTING"
            for i in range(self.connect_retries):
                await asyncio.sleep(self.connect_delay)
                res = await self.reconnect()
                if res:
                    break

    async def reconnect(self):
        res = await self.async_init()
        if res:
            await self.start()
        return res

    async def stop(self):
        self.state = "STOPPING"
        await self._ws.close()
        for task in self._pending:
            task.cancel()

    async def keep_alive(self, second):
        while True:
            await asyncio.sleep(second)
            if self._encryption_ready:
                await self._ws.send("keepalive")

    async def send_websocket_command(self, device_uuid, value):
        """Send a websocket command to the Miniserver."""
        command = "jdev/sps/io/{}/{}".format(device_uuid, value)
        await self._ws.send(command)

    async def async_init(self):
        import websockets as wslib
        print("try to read token")
        # Read token from file
        try:
            await self.get_token_from_file()
        except IOError:
            print("error token read")
            pass

        # Get public key from Loxone
        resp = self.get_public_key()

        if not resp:
            print("Get public key failed.")
            return ERROR_VALUE

        # Init resa cipher
        rsa_gen = self.init_rsa_cipher()
        if not rsa_gen:
            print("Rsa initialisation failed.")
            return ERROR_VALUE

        # Generate session key
        session_gen = self.generate_session_key()
        if not session_gen:
            print("Rsa initialisation failed.")
            return ERROR_VALUE

        # Exchange keys
        try:
            self._ws = await wslib.connect("ws://{}:{}/ws/rfc6455".format(
                self._host, self._port), timeout=TIMEOUT)
            await self._ws.send("{}{}".format(CMD_KEY_EXCHANGE,
                                              self._session_key))
            message = await self._ws.recv()
            await self.parse_loxone_message(message)
            if self._current_message_typ != 0:
                print("Error by getting the session key response.")
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
            print("Error to Connect to Loxone.")
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
        await self._ws.recv()
        self.state = "CONNECTED"
        return True

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
                print("Keep alive response received")
        else:
            parsed_data = await self._parse_loxone_message(message)
            if self.message_call_back is not None:
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
            pass
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
        from Crypto.Hash import SHA, HMAC
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
                if key is not "":
                    digester = HMAC.new(binascii.unhexlify(key),
                                        self._token.token.encode("utf-8"), SHA)
                    return digester.hexdigest()
        return ERROR_VALUE

    async def acquire_token(self):
        command = "{}".format(CMD_GET_KEY_AND_SALT + self._username)
        enc_command = await self.encrypt(command)

        if not self._encryption_ready or self._ws is None:
            return ERROR_VALUE

        await self._ws.send(enc_command)
        message = await self._ws.recv()
        await self.parse_loxone_message(message)

        message = await self._ws.recv()

        key_and_salf = LxJsonKeySalt()
        key_and_salf.read_user_salt_responce(message)

        new_hash = self.hash_credentials(key_and_salf)
        command = "{}{}/{}/{}/edfc5f9a-df3f-4cad-9dddcdc42c732be2" \
                  "/homeassistant".format(CMD_REQUEST_TOKEN, new_hash,
                                          self._username, TOKEN_PERMISSION)

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
            self._token = pickle.load(open(persist_token, "rb"))
            return True
        except IOError:
            return ERROR_VALUE

    def save_token(self):
        try:
            persist_token = os.path.join(get_default_config_dir(),
                                         self._token_persist_filename)
            pickle.dump(self._token, open(persist_token, "wb"))
            return True
        except IOError:
            return ERROR_VALUE

    async def encrypt(self, command):
        from Crypto.Util import Padding
        if not self._encryption_ready:
            return command
        if self._salt is not "" and self.new_salt_needed():
            prev_salt = self._salt
            self._salt = self.genarate_salt()
            s = "nextSalt/" + prev_salt + "/" + self._salt + "/" + command + "\0"
        else:
            if self._salt is "":
                self._salt = self.genarate_salt()
            s = "salt/" + self._salt + "/" + command + "\0"

        s = Padding.pad(bytes(s, "utf-8"), 16)
        aes_cipher = self.get_new_aes_chiper()
        encrypted = aes_cipher.encrypt(s)
        encoded = b64encode(encrypted)
        encoded_url = req.pathname2url(encoded.decode("utf-8"))
        return CMD_ENCRYPT_CMD + encoded_url

    def hash_credentials(self, key_salt):
        from Crypto.Hash import SHA, HMAC
        pwd_hash_str = self._pasword + ":" + key_salt.salt
        m = hashlib.sha1()
        m.update(pwd_hash_str.encode('utf-8'))
        pwd_hash = m.hexdigest().upper()
        pwd_hash = self._username + ":" + pwd_hash
        digester = HMAC.new(binascii.unhexlify(key_salt.key),
                            pwd_hash.encode("utf-8"), SHA)
        return digester.hexdigest()

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
            unpacked_data = unpack('ccccI', message)
            self._current_message_typ = int.from_bytes(unpacked_data[1],
                                                       byteorder='big')

    def generate_session_key(self):
        try:
            aes_key = binascii.hexlify(self._key).decode("utf-8")
            iv = binascii.hexlify(self._iv).decode("utf-8")
            sess = aes_key + ":" + iv
            sess = self._rsa_cipher.encrypt(bytes(sess, "utf-8"))
            self._session_key = b64encode(sess).decode("utf-8")
            return True
        except KeyError:
            return False

    def get_new_aes_chiper(self):
        from Crypto.Cipher import AES
        return AES.new(self._key, AES.MODE_CBC, self._iv)

    def init_rsa_cipher(self):
        from Crypto.Cipher import PKCS1_v1_5
        from Crypto.PublicKey import RSA
        try:
            self._public_key = self._public_key.replace(
                "-----BEGIN CERTIFICATE-----",
                "-----BEGIN PUBLIC KEY-----\n")
            public_key = self._public_key.replace(
                "-----END CERTIFICATE-----",
                "\n-----END PUBLIC KEY-----\n")
            self._rsa_cipher = PKCS1_v1_5.new(RSA.importKey(public_key))
            return True
        except KeyError:
            return False

    def get_public_key(self):
        command = "http://{}:{}/{}".format(self._host, self._port,
                                           CMD_GET_PUBLIC_KEY)
        response = requests.get(command, auth=(self._username, self._pasword))
        if response.status_code != 200:
            return False
        try:
            resp_json = json.loads(response.text)
            if 'LL' in resp_json and 'value' in resp_json['LL']:
                self._public_key = resp_json['LL']['value']
            else:
                return False
        except ValueError:
            return False
        return True

    async def get_token_from_file(self):
        persist_token = os.path.join(get_default_config_dir(),
                                     self._token_persist_filename)
        if os.path.exists(persist_token):
            if self.load_token():
                print("token loaded")
