import asyncio
import codecs
import hashlib
import hmac
import json
import uuid
from struct import unpack
import websockets as wslib


class LoxoneGateway:
    """Main class for the communication with the miniserver."""

    def __init__(self, event_loop, user, password, host, port):
        """Username, password, host and port of a Loxone user."""
        self._user = user
        self._password = password
        self._host = host
        self._port = port
        self._loop = event_loop
        self._time_out = 30
        self._ws = None
        self._current_typ = None
        self._tasks = []
        self._log = None
        self._call_back = None
        self._keep_alive_interval = 120
        self._stop = False
        self._last_keep_alive = 0

    def set_callback(self, callback):
        self._call_back = callback

    def set_logger(self, l):
        """Sets the logger."""
        self._log = l

    def set_time_out(self, t):
        """Sets Timout in seconds."""
        self._time_out = t

    def get_hash(self, key):
        """Get the login data from username and password."""
        key_dict = json.loads(key)
        key_value = key_dict['LL']['value']
        data = "{}:{}".format(self._user, self._password)
        decoded_key = codecs.decode(key_value.encode("ascii"), "hex")
        hmac_obj = hmac.new(decoded_key, data.encode('UTF-8'), hashlib.sha1)
        return hmac_obj.hexdigest()

    @asyncio.coroutine
    def _ws_read(self):
        result = None
        try:
            if not self._ws:
                self._ws = yield from wslib.connect(
                    "ws://{}:{}/ws/rfc6455".format(self._host, self._port),
                    timeout=5)
                yield from self._ws.send("jdev/sys/getkey")
                yield from self._ws.recv()
                key = yield from self._ws.recv()
                new_hash = self.get_hash(key)
                yield from self._ws.send("authenticate/{}".format(new_hash))
                yield from self._ws.recv()
                yield from self._ws.send("jdev/sps/enablebinstatusupdate")
                yield from self._ws.recv()
        except Exception as ws_exc:
            print("Failed to connect to websocket: %s", ws_exc)

        try:
            result = yield from self._ws.recv()
        except Exception as ws_exc:  # pylint: disable=broad-except
            try:
                yield from self._ws.close()
            finally:
                self._ws = None
        return result

    @asyncio.coroutine
    def keep_alive(self):
        """Send an keep alive to the Miniserver."""
        while True:
            yield from asyncio.sleep(self._keep_alive_interval)
            yield from self._ws.ping("keepalive")

    @asyncio.coroutine
    def stop_listener(self):
        """Stop listener."""
        for task in self._tasks:
            task.cancel()

    def start_listener(self):
        """Start listener."""
        try:
            from asyncio import ensure_future
        except ImportError:
            from asyncio import async as ensure_future
        self._tasks.append(self._loop.create_task(self.ws_listen()))
        self._tasks.append(self._loop.create_task(self.keep_alive()))

    @asyncio.coroutine
    def ws_listen(self):
        """Listen to all commands from the Miniserver."""
        try:
            while True:
                result = yield from self._ws_read()
                if result:
                    yield from self._async_process_message(result)
                else:
                    yield from asyncio.sleep(self._time_out)
        finally:
            if self._ws:
                yield from self._ws.close()

    @asyncio.coroutine
    def _async_process_message(self, message):
        """Process the messages."""
        if len(message) == 8:
            unpacked_data = unpack('ccccI', message)
            self._current_typ = int.from_bytes(unpacked_data[1],
                                               byteorder='big')
        else:
            parsed_data = self.parse_loxone_message(message)
            if self._call_back is not None and parsed_data:
                self._call_back(parsed_data)

    def _print_log(self, message, level="debug"):
        """Log function."""
        if not self._log is None:
            if level is "info":
                self._log.info(message)
            elif level is "debug":
                self._log.debug(message)

    @asyncio.coroutine
    def send_websocket_command(self, device_uuid, value):
        """Send a websocket command to the Miniserver."""
        yield from self._ws.send(
            "jdev/sps/io/{}/{}".format(device_uuid, value))

    def parse_loxone_message(self, message):
        """Parser of the Loxone message."""
        event_dict = {}
        if self._current_typ == 0:
            self._print_log("Text Message received!!")
            event_dict = message
        elif self._current_typ == 1:
            self._print_log("Binary Message received!!")
        elif self._current_typ == 2:
            self._print_log("Event-Table of Value-States received!!")
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
        elif self._current_typ == 3:
            self._print_log("Typ 3 received!")
        elif self._current_typ == 6:
            self._print_log("Keep alive Message received!")
        else:
            self._print_log("Typ not known!")
        return event_dict


