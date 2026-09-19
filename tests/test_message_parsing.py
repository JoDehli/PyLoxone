"""Tests for parsing text messages sent by the Miniserver."""

from __future__ import annotations

from custom_components.loxone.pyloxone_api.message import (
    LLResponse,
    MessageType,
    TextMessage,
    parse_message,
)


def test_ll_response_accepts_raw_control_characters():
    """The Miniserver may send literal newlines/tabs inside JSON string values."""
    response = '{"LL": {"control": "dev/sps/io/abc/notify", "value": "line 1\nline 2\tend", "Code": "200"}}'

    parsed = LLResponse(response)

    assert parsed.code == 200
    assert parsed.control == "dev/sps/io/abc/notify"
    assert parsed.value == "line 1\nline 2\tend"


def test_text_message_with_raw_control_characters_is_parsed():
    """A TEXT message with raw control characters must not break the listening loop."""
    message = '{"LL": {"control": "jdev/sps/io/abc", "value": "a\nb", "code": "200"}}'

    parsed = parse_message(message, MessageType.TEXT)

    assert isinstance(parsed, TextMessage)
    assert parsed.as_dict() == {"control": "jdev/sps/io/abc", "value": "a\nb", "Code": 200}
