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
from functools import lru_cache
from typing import Optional, Union

from .const import MESSAGE_HEADER_SIZE
from .exceptions import LoxoneException

_LOGGER = logging.getLogger(__name__)


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


def check_and_decode_if_needed(message):
    """Decode ``message`` (bytes / bytearray / str) to ``str``.

    - ``str`` input is returned as-is.
    - Bytes are decoded as UTF-8 first; if that fails (the bytes are
      not valid UTF-8) the fallback is **latin-1**, which is defined
      to map every byte 0-255 to a valid code point, so it can never
      raise and never inserts ``U+FFFD`` replacement characters.

    The latin-1 fallback replaces the previous multi-stage detector
    that tried a dozen encodings and cached results by SHA-256 sample
    hash. The detector was expensive on the recv path and the latin-1
    fallback is byte-faithful — every byte is preserved exactly as
    code point ``0x__``. ASCII bytes (which is what most Loxone
    strings are) round-trip identically through UTF-8 and latin-1.
    """
    if isinstance(message, str):
        return message

    # ``bytes(...)`` accepts both ``bytes`` and ``bytearray``; the
    # explicit cast keeps the rest of the function uniform.
    b: bytes = bytes(message)

    try:
        return b.decode("utf-8")
    except UnicodeDecodeError:
        # UTF-8 failed — every byte has a valid latin-1 code point, so
        # this fallback is total and loss-free.
        return b.decode("latin-1")


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
            self._parsed: dict = json.loads(response, strict=False)
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
        #
        # ``MessageHeader`` always populates ``message_type``,
        # ``estimated`` and ``payload_length``. For non-0x03
        # frames (text-only or out-of-band events some Miniservers
        # emit) the three are set to ``UNKNOWN`` / ``False`` /
        # ``0`` so the recv state machine in ``_do_start_listening``
        # can index them unconditionally.
        self.header = header
        # Defaults for non-0x03 frames. These also cover the
        # "header too short to unpack" guard below.
        self.message_type: MessageType = MessageType.UNKNOWN
        self.estimated: bool = False
        self.payload_length: int = 0

        if header is None or len(header) < MESSAGE_HEADER_SIZE:
            # Nothing to parse — treat as a bodyless unknown.
            return
        if header[0] != 3:
            # Non-Loxone binary header. Some Miniserver firmware
            # versions send short text-only events that begin with
            # other bytes; treat them as bodyless UNKNOWN.
            return

        try:
            # ``header[:8]`` would copy; hand the buffer to
            # ``struct.unpack`` as-is when it is exactly 8 bytes
            # wide (it accepts any bytes-like object, and anything
            # else — e.g. ``str`` — raises ``TypeError``, which is
            # converted to ``LoxoneException`` below).
            source = header if len(header) == MESSAGE_HEADER_SIZE else bytes(header[:MESSAGE_HEADER_SIZE])
            unpacked_data = struct.unpack("<cBccI", source)
        except (struct.error, TypeError) as exc:
            raise LoxoneException(
                f"Invalid header received: {exc} - {header!r}"
            ) from exc

        self.message_type = MessageType(unpacked_data[1])
        # First bit of ``cInfo`` indicates that length is only
        # estimated. ``unpacked_data[2]`` is a 1-byte ``bytes``
        # object — index it to get the int value.
        self.estimated = bool((unpacked_data[2][0] >> 7) & 0x01)
        self.payload_length = unpacked_data[4]


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
        # 24 bytes per record (16-byte uuid + 8-byte double). Floor-divide
        # so we only iterate full records and never slice past the end of
        # ``self.message``; the trailing partial record (if any) is
        # logged at DEBUG instead of silently dropped — the previous
        # ``int(length / 24)`` truncated in the same place but never
        # reported it.
        num_full = length // 24
        remainder = length % 24
        if remainder:
            _LOGGER.debug(
                "ValueStatesTable: trailing partial record of %d byte(s) "
                "dropped (expected a multiple of 24)",
                remainder,
            )

        start = 0
        end = 24
        for _ in range(num_full):
            packet = self.message[start:end]
            event_uuid = uuid.UUID(bytes_le=packet[0:16])
            fields = event_uuid.urn.replace("urn:uuid:", "").split("-")
            uuidstr = f"{fields[0]}-{fields[1]}-{fields[2]}-{fields[3]}{fields[4]}"
            # Loxone sends the double in little-endian byte order; the
            # native-order ``"d"`` format happens to match on x86 but
            # breaks on big-endian systems (and is fragile in either
            # case). Force ``"<d"`` explicitly.
            value = struct.unpack("<d", packet[16:24])[0]
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


# Explicit per-``MessageType`` dispatch table. Replaces the previous
# ``BaseMessage.__subclasses__()`` introspection — which was O(n),
# relied on import-ordering quirks to register every subclass, and
# silently dropped types for which no subclass existed (e.g.
# ``MessageType.UNKNOWN``). The dict is built once at module load and
# ``parse_message`` does an O(1) lookup against ``MessageType``.
_MESSAGE_CLASSES: dict[MessageType, type[BaseMessage]] = {
    MessageType.TEXT: TextMessage,
    MessageType.BINARY: BinaryFile,
    MessageType.VALUE_STATES: ValueStatesTable,
    MessageType.TEXT_STATES: TextStatesTable,
    MessageType.DAYTIMER_STATES: DaytimerStatesTable,
    MessageType.OUT_OF_SERVICE: OutOfServiceIndicator,
    MessageType.KEEPALIVE: Keepalive,
    MessageType.WEATHER_STATES: WeatherStatesTable,
}


def parse_message(message: bytes | str, message_type: int) -> BaseMessage:
    """Return an instance of the ``BaseMessage`` subclass for ``message_type``.

    ``MessageType.UNKNOWN`` (and any value not in
    :data:`_MESSAGE_CLASSES`) raises :class:`LoxoneException`.
    """
    # ``MessageType(x)`` on an already-converted member is a wasted
    # enum call: the recv loop hands over the header's
    # ``MessageType`` directly, so only raw ints take the slow path.
    mtype = message_type
    if not isinstance(mtype, MessageType):
        try:
            mtype = MessageType(mtype)
        except ValueError as exc:
            raise LoxoneException(f"Unknown message type {message_type}") from exc

    try:
        return _MESSAGE_CLASSES[mtype](message)
    except KeyError as exc:
        raise LoxoneException(f"Unknown message type {mtype.name}") from exc
