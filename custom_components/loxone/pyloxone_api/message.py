"""Classes for handling messages from a Miniserver"""

from __future__ import annotations

import json
import math
import struct
import uuid
from enum import IntEnum
from typing import Any

from .exceptions import LoxoneException


class LoxoneResponse:
    """A class for parsing LL Responses from the miniserver.

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
            self._parsed: dict[Any, Any] = json.loads(response)
            # Sometimes, Loxone uses "Code", and sometimes "code"
            self.code: int = int(
                self._parsed.get("LL", {}).get("code", "")
                or self._parsed.get("LL", {}).get("Code", "")
            )
            self.control: str = self._parsed["LL"]["control"]
            self.value: str = str(self._parsed["LL"]["value"])
        except (ValueError, KeyError, TypeError) as exc:
            raise ValueError(exc) from exc

    @property
    def value_as_dict(self) -> dict[Any, Any]:
        d = self._parsed["LL"]["value"]
        retval = {"value": self.value}
        return {**retval, **d} if isinstance(d, dict) else retval


class MessageType(IntEnum):
    """The different types of message which the Miniserver might send."""

    TEXT = 0
    BINARY = 1
    VALUE_STATES = 2
    TEXT_STATES = 3
    DAYTIMER_STATES = 4
    OUT_OF_SERVICE = 5
    KEEPALIVE = 6
    WEATHER_STATES = 7
    UNKNOWN = -1


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
        if header[0] != 3:
            raise LoxoneException(r"Invalid header: first byte is not \0x03")
        try:
            unpacked_data = struct.unpack("<cBccI", header)
        except (struct.error, TypeError) as exc:
            raise LoxoneException(f"Invalid header: {exc}") from exc
        self.message_type: MessageType = MessageType(unpacked_data[1])
        # First bit indicates that length is only estimated
        self.estimated: bool = ord(unpacked_data[2]) >> 7 == 1
        self.payload_length: int = int(unpacked_data[4])


class BaseMessage:
    """The base class for all messages from the Miniserver."""

    message_type = MessageType.UNKNOWN

    def __init__(self, message: bytes | str):
        self.message = message
        # For the base class, the dict is the message

    def as_dict(self) -> dict[Any, Any]:
        """Return the contents of the message as a dict"""
        return {}


class TextMessage(BaseMessage):
    message_type = MessageType.TEXT

    def __init__(self, message: bytes | str):
        super().__init__(message)
        ll_message = LoxoneResponse(message)
        self.code = ll_message.code
        self.control = ll_message.control
        self.value = ll_message.value
        self.value_as_dict = ll_message.value_as_dict


class BinaryFile(BaseMessage):
    message_type = MessageType.BINARY

    # The message is a binary file. There is nothing to parse
    def as_dict(self) -> dict[Any, Any]:
        return {}


class ValueStatesTable(BaseMessage):
    message_type = MessageType.VALUE_STATES

    # A value state is as follows:
    # typedef struct {
    #     PUUID uuid;   // 128-Bit uuid
    #     double dVal;  // 64-Bit Float (little endian) value
    # } PACKED EvData;

    def as_dict(self) -> dict[str, Any]:
        event_dict = {}
        length = len(self.message)
        num = length / 24
        start = 0
        end = 24
        for _ in range(int(num)):
            assert isinstance(self.message, bytes)
            packet = self.message[start:end]
            event_uuid = uuid.UUID(bytes_le=packet[:16])
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
    def as_dict(self) -> dict[str, Any]:
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
            event_dict[uuidstr] = message_str.decode("utf-8")
            return start

        if not isinstance(self.message, bytes):
            raise LoxoneException("Expected bytes table, got str")
        while start < len(self.message):
            start = get_text(self.message, start, 16)
        return event_dict


class DaytimerStatesTable(BaseMessage):
    message_type = MessageType.DAYTIMER_STATES

    # We dont currently handle this.
    def as_dict(self) -> dict[str, Any]:
        return {}


class OutOfServiceIndicator(BaseMessage):
    message_type = MessageType.OUT_OF_SERVICE
    # There is no message body for an Out of Service message. The Miniserver
    # will close the connection immedately after sending the header


class Keepalive(BaseMessage):
    message_type = MessageType.KEEPALIVE
    # There is no message body for a KEEPALIVE message.


class WeatherStatesTable(BaseMessage):
    message_type = MessageType.WEATHER_STATES

    # We dont currently handle this.
    def as_dict(self) -> dict[str, Any]:
        return {}


Class_Table = {klass.message_type: klass for klass in BaseMessage.__subclasses__()}


def parse_header(header: bytes) -> MessageHeader:
    return MessageHeader(header)


def parse_message(message: bytes | str, message_type: MessageType) -> BaseMessage:
    """Return an instance of the appropriate BaseMessage subclass"""
    return Class_Table[message_type](message)
