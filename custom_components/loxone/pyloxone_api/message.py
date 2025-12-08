"""
Component to create an interface to the Loxone Miniserver.

For more details about this component, please refer to the documentation at
https://github.com/JoDehli/pyloxone-api
"""

import json
import logging
import math
import re
import struct
import time
import uuid
from enum import IntEnum
from typing import Optional, Union
import hashlib
from functools import lru_cache
from .exceptions import LoxoneException

_LOGGER = logging.getLogger(__name__)

# small in-memory cache for expensive encoding detection results
_encoding_cache: dict[str, Optional[str]] = {}
_DETECT_SAMPLE_SIZE = 512  # sample length used for detection & caching
_DETECT_MAX_BYTES = 4096  # only run heavy detection for messages <= this size


class AsyncTimer:
    def __init__(self, label: str, logger: logging.Logger = _LOGGER):
        self.label = label
        self.logger = logger
    async def __aenter__(self):
        self._start = time.perf_counter()
        return self
    async def __aexit__(self, exc_type, exc, tb):
        elapsed = time.perf_counter() - self._start
        self.logger.debug("%s took %.6f s", self.label, elapsed)

class SyncTimer:
    def __init__(self, label: str, logger: logging.Logger = _LOGGER):
        self.label = label
        self.logger = logger

    def __enter__(self):
        self._start = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb):
        elapsed = time.perf_counter() - self._start
        self.logger.debug("%s took %.6f s", self.label, elapsed)


def detect_encoding(byte_string):
    encodings = [
        "utf-8",
        "iso-8859-1",
        "ascii",
        "utf-16",
        "utf-32",
        "latin-1",
        "cp1252",
        "mac-roman",
        "big5",
        "shift_jis",
        "euc-jp",
        "gb2312",
    ]

    for encoding in encodings:
        try:
            byte_string.decode(encoding)
            return encoding
        except (UnicodeDecodeError, AttributeError):
            continue
    return None


def check_and_decode_if_needed(message):
    if isinstance(message, str):
        return message

    # ensure we handle bytearray too
    b: bytes = bytes(message)

    # fast happy-path: utf-8 works for most messages
    try:
        return b.decode("utf-8")
    except UnicodeDecodeError:
        pass

    # if ascii, decode cheaply (shouldn't usually get here)
    if getattr(b, "isascii", lambda: False)():
        return b.decode("ascii", errors="replace")

    # try a few common single-byte encodings (cheap)
    for enc in ("latin-1", "cp1252", "iso-8859-15"):
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            continue
        except Exception:
            # defensive: skip any unexpected errors from decoder
            continue

    # heavy detection: only for small messages, with a cache keyed on sample hash
    if len(b) <= _DETECT_MAX_BYTES:
        sample = b[:_DETECT_SAMPLE_SIZE]
        key = hashlib.sha256(sample).hexdigest()
        enc = _encoding_cache.get(key)
        if enc is None and "detect_encoding" in globals():
            try:
                enc = detect_encoding(sample)  # may be expensive
            except Exception:
                enc = None
            _encoding_cache[key] = enc  # cache even None to avoid repeated work

        if enc:
            try:
                return b.decode(enc)
            except Exception:
                pass

    # last resort: replace invalid characters (fast and safe)
    _LOGGER.info(
        "Decoding problem for message (len=%d). Falling back to replace invalid chars.",
        len(b),
    )
    return b.decode("utf-8", errors="replace")


class MessageType(IntEnum):
    """The different types of message which the miniserver might send"""

    TEXT = 0
    BINARY = 1
    VALUE_STATES = 2
    TEXT_STATES = 3
    DAYTIMER_STATES = 4
    OUT_OF_SERVICE = 5
    KEEPALIVE = 6
    WEATHER_STATES = 7
    UNKNOWN = -1


class LLResponse:
    """A class for parsing LL Responses from the miniserver

    An LL Response is a json object often returned by a miniserver in response
    to a command. It begins "{"LL": {..." and has a control, code and value
    keys. This class provides easy access to code (as an integer) and control
    attributes (as a string), which should be present in every case.
    LLResponse.value is a string containing the value of the response.
    LLResponse.as_dict is guaranteed to be a dict, with at least a value key,
    and if value has sub-values, keys for the sub-values as well.

    Raises ValueError if the response cannot be parsed.

    """

    def __init__(self, response: str | bytes):
        try:
            self._parsed: dict = json.loads(response)
            # Sometimes, Loxone uses "Code", and sometimes "code"
            self.code: int = int(
                self._parsed.get("LL", {}).get("code", "")
                or self._parsed.get("LL", {}).get("Code", "")
            )
            self.control: str = self._parsed["LL"]["control"]
            self.value: str = str(self._parsed["LL"]["value"])
        except (ValueError, KeyError, TypeError) as exc:
            raise ValueError(exc)

    @property
    def value_as_dict(self) -> dict:
        d = self._parsed["LL"]["value"]
        retval = {"value": self.value}
        if isinstance(d, dict):
            return {**retval, **d}
        return retval


class MessageHeader:
    def __init__(self, header: bytes):
        # From the Loxone API docs, the header is as follows
        # typedef struct {
        #   BYTE cBinType;     // fix 0x03
        #   BYTE cIdentifier;  // 8-Bit Unsigned Integer (little endian)
        #   BYTE cInfo;        // Info
        #   BYTE cReserved;    // reserved
        #   UINT nLen;         // 32-Bit Unsigned Integer (little endian)
        # } PACKED WsBinHdr;
        self.header = header
        if not header[0] == 3:
            self.message_type = MessageType.UNKNOWN
        else:
            try:
                unpacked_data = struct.unpack("<cBccI", header)
            except (struct.error, TypeError) as exc:
                raise LoxoneException(f"Invalid header received: {exc} - {header}")

            self.message_type: MessageType = MessageType(unpacked_data[1])
            # First bit indicates that length is only estimated
            self.estimated: bool = ord(unpacked_data[2]) >> 7 == 1
            self.payload_length: int = int(unpacked_data[4])


class BaseMessage:
    """The base class for all messages from the miniserver"""

    message_type = MessageType.UNKNOWN

    def __init__(self, message: bytes | str):
        self.message = message
        # For the base class, the dict is the message

    def as_dict(self) -> dict:
        """Return the contents of the message as a dict"""
        return {}


def clean_up_control(control):
    control = check_and_decode_if_needed(control)
    try:
        return re.sub(r"^salt/[0-9a-fA-F]+", "", control)
    except:
        return control


class TextMessage(BaseMessage):
    message_type = MessageType.TEXT

    def __init__(self, message: bytes | str):
        super().__init__(message)
        message = check_and_decode_if_needed(message)
        ll_message = LLResponse(message)
        self.code = ll_message.code
        self.control = ll_message.control
        self.value = ll_message.value
        self.value_as_dict = ll_message.value_as_dict

    def as_dict(self) -> dict:
        """Return the contents of the message as a dict"""
        cleaned_control = clean_up_control(self.control)
        return {"control": cleaned_control, "value": self.value, "Code": self.code}


class BinaryFile(BaseMessage):
    message_type = MessageType.BINARY

    # The message is a binary file. There is nothing parse
    def as_dict(self):
        return {}


class ValueStatesTable(BaseMessage):
    message_type = MessageType.VALUE_STATES

    # A value state is as follows:
    # typedef struct {
    #     PUUID uuid;   // 128-Bit uuid
    #     double dVal;  // 64-Bit Float (little endian) value
    # } PACKED EvData;

    def as_dict(self):
        event_dict = {}
        length = len(self.message)
        num = length / 24
        start = 0
        end = 24
        for _ in range(int(num)):
            packet = self.message[start:end]
            event_uuid = uuid.UUID(bytes_le=packet[0:16])
            fields = event_uuid.urn.replace("urn:uuid:", "").split("-")
            uuidstr = f"{fields[0]}-{fields[1]}-{fields[2]}-{fields[3]}{fields[4]}"
            value = struct.unpack("d", packet[16:24])[0]
            event_dict[uuidstr] = value
            start += 24
            end += 24
        return event_dict


class TextStatesTable(BaseMessage):
    message_type = MessageType.TEXT_STATES

    # A text event state is as follows:
    # typedef struct {                 // starts at multiple of 4
    #     PUUID uuid;                  // 128-Bit uuid
    #     PUUID uuidIcon;              // 128-Bit uuid of icon
    #     unsigned long textLength;    // 32-Bit Unsigned Integer (little endian)
    #     // text follows here
    #     } PACKED EvDataText;
    def as_dict(self):
        event_dict = {}
        start = 0

        def get_text(message: bytes, start: int, offset: int) -> int:
            first = start
            second = start + offset
            event_uuid = uuid.UUID(bytes_le=self.message[first:second])  # type: ignore
            first += offset
            second += offset

            icon_uuid_fields = event_uuid.urn.replace("urn:uuid:", "").split("-")
            uuidstr = "{}-{}-{}-{}{}".format(
                icon_uuid_fields[0],
                icon_uuid_fields[1],
                icon_uuid_fields[2],
                icon_uuid_fields[3],
                icon_uuid_fields[4],
            )

            icon_uuid = uuid.UUID(bytes_le=self.message[first:second])  # type: ignore
            icon_uuid_fields = icon_uuid.urn.replace("urn:uuid:", "").split("-")

            first = second
            second += 4

            text_length = struct.unpack("<I", message[first:second])[0]

            first = second
            second = first + text_length
            message_str = struct.unpack(f"{text_length}s", message[first:second])[0]
            start += (math.floor((4 + text_length + 16 + 16 - 1) / 4) + 1) * 4
            event_dict[uuidstr] = check_and_decode_if_needed(message_str)
            return start

        if not isinstance(self.message, bytes):
            raise LoxoneException("Expected bytes table, got str")
        while start < len(self.message):
            start = get_text(self.message, start, 16)
        return event_dict


class DaytimerStatesTable(BaseMessage):
    message_type = MessageType.DAYTIMER_STATES

    # We dont currently handle this.
    def as_dict(self):
        return {}


class OutOfServiceIndicator(BaseMessage):
    message_type = MessageType.OUT_OF_SERVICE
    # There can be no such message. If an out-of-service header is sent, the
    # miniserver will close the connection before sending a message.


class Keepalive(BaseMessage):
    message_type = MessageType.KEEPALIVE

    # Nothing to do. The dict is the message (which is b'keepalive')
    def as_dict(self):
        return {"keep_alive": "received"}


class WeatherStatesTable(BaseMessage):
    message_type = MessageType.WEATHER_STATES

    def as_dict(self):
        return {}


def parse_header(header: bytes) -> MessageHeader:
    return MessageHeader(header)


def parse_message(message: bytes | str, message_type: int) -> BaseMessage:
    """Return an instance of the appropriate BaseMessage subclass"""
    for klass in BaseMessage.__subclasses__():
        if klass.message_type == message_type:
            return klass(message)
    raise LoxoneException(f"Unknown message type {message_type}")
