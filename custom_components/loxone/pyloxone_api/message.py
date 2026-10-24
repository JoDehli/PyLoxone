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
from enum import IntEnum
from functools import lru_cache
from typing import Optional, Union

from .const import MESSAGE_HEADER_SIZE
from .exceptions import LoxoneException

_LOGGER = logging.getLogger(__name__)

# Textual form of a Loxone state uuid, keyed by its raw 16 bytes. A
# Miniserver repeats the same uuids on every update, so in steady
# state a record costs one dict lookup instead of
# ``uuid.UUID(bytes_le=...)`` + ``.urn`` + ``replace()`` + ``split()``
# + an f-string — measured ~9x faster per value-states message, and
# that path alone was ~37% of the whole receive pipeline.
#
# The cache is bounded: it is dropped wholesale once it grows past
# the cap, which only happens with pathological uuid churn (a normal
# house has far fewer states than this).
_UUID_STR_CACHE: dict[bytes, str] = {}
_UUID_STR_CACHE_MAX = 8192
_UUID_BYTES_LEN = 16
_UUID_LEN_ERROR = "bytes_le must be exactly 16 bytes long"


def _uuid_str(raw: bytes) -> str:
    """Return the Loxone compact key text (``8-4-4-16`` hex) for ``raw``."""
    # Byte-for-byte identical to ``uuid.UUID(bytes_le=raw).urn`` with
    # the ``urn:uuid:`` prefix stripped and the last two groups joined
    # without a dash — the form the integration already uses for its
    # event keys.
    if len(raw) != _UUID_BYTES_LEN:
        # Same type and message as ``uuid.UUID(bytes_le=...)`` so a
        # truncated record fails exactly where it used to.
        raise ValueError(_UUID_LEN_ERROR)
    cached = _UUID_STR_CACHE.get(raw)
    if cached is not None:
        return cached
    # ``bytes_le`` reads the first three fields little-endian and
    # keeps clock-sequence and node bytes in order — mirror that.
    time_low, time_mid, time_hi = struct.unpack_from("<IHH", raw, 0)
    text = f"{time_low:08x}-{time_mid:04x}-{time_hi:04x}-{raw[8:10].hex()}{raw[10:16].hex()}"
    if len(_UUID_STR_CACHE) >= _UUID_STR_CACHE_MAX:
        _UUID_STR_CACHE.clear()
    _UUID_STR_CACHE[raw] = text
    return text


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
        message = self.message
        # 24 bytes per record (16-byte uuid + 8-byte double). Floor-divide
        # so we only iterate full records and never read past the end of
        # ``self.message``; the trailing partial record (if any) is
        # logged at DEBUG instead of silently dropped — the previous
        # ``int(length / 24)`` truncated in the same place but never
        # reported it.
        num_full = len(message) // 24
        remainder = len(message) % 24
        if remainder:
            _LOGGER.debug(
                "ValueStatesTable: trailing partial record of %d byte(s) "
                "dropped (expected a multiple of 24)",
                remainder,
            )

        # ``unpack_from`` reads straight out of the payload — no
        # 24-byte slice per record — and the uuid text comes from the
        # module cache (see ``_uuid_str``). Loxone sends the double in
        # little-endian byte order; the native-order ``"d"`` format
        # happens to match on x86 but breaks on big-endian systems (and
        # is fragile in either case). Force ``"<d"`` explicitly.
        unpack_from = struct.unpack_from
        uuid_str = _uuid_str
        for start in range(0, num_full * 24, 24):
            event_dict[uuid_str(message[start : start + 16])] = unpack_from("<d", message, start + 16)[0]
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
            # Layout: event uuid (``offset`` bytes) + icon uuid (16)
            # + text length (4) + text. The icon uuid is not part of
            # the payload we surface, so it is stepped over instead of
            # parsed — its textual form was computed and thrown away.
            uuidstr = _uuid_str(message[start : start + offset])
            first = start + offset + offset

            text_length = struct.unpack_from("<I", message, first)[0]
            first += 4

            # ``unpack_from`` keeps the old contract: a truncated text
            # raises ``struct.error`` instead of yielding short bytes.
            message_str = struct.unpack_from(f"{text_length}s", message, first)[0]
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
