"""Header/body framing in ``LoxoneClientConnection.recv_message``."""

from __future__ import annotations

from unittest.mock import AsyncMock

from custom_components.loxone.pyloxone_api.message import MessageType
from custom_components.loxone.pyloxone_api.websocket_protocol import (
    LoxoneClientConnection,
)

KEEPALIVE_HEADER = b"\x03\x06\x00\x00\x00\x00\x00\x00"
VALUE_STATES_HEADER = b"\x03\x02\x00\x00\x18\x00\x00\x00"
ESTIMATED_VALUE_STATES_HEADER = b"\x03\x02\x80\x00\x18\x00\x00\x00"
VALUE_STATES_BODY = bytes(16) + b"\x00\x00\x00\x00\x00\x00\xf0\x3f"  # one record, 1.0


def _connection(*frames: bytes) -> LoxoneClientConnection:
    connection = object.__new__(LoxoneClientConnection)
    connection._last_header = None
    connection.recv = AsyncMock(side_effect=list(frames))
    return connection


async def test_a_keepalive_header_is_not_followed_by_a_body() -> None:
    connection = _connection(KEEPALIVE_HEADER, VALUE_STATES_HEADER, VALUE_STATES_BODY)

    keepalive = await connection.recv_message()
    value_states = await connection.recv_message()

    assert keepalive.message_type is MessageType.KEEPALIVE
    assert value_states.message_type is MessageType.VALUE_STATES
    assert list(value_states.as_dict().values()) == [1.0]


async def test_an_estimated_header_is_followed_by_the_exact_header() -> None:
    connection = _connection(ESTIMATED_VALUE_STATES_HEADER, VALUE_STATES_HEADER, VALUE_STATES_BODY)

    value_states = await connection.recv_message()

    assert value_states.message_type is MessageType.VALUE_STATES
    assert list(value_states.as_dict().values()) == [1.0]
