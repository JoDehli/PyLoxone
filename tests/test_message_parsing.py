"""Tests for parsing text messages sent by the Miniserver."""

from __future__ import annotations

import logging
import struct
from types import SimpleNamespace

import pytest

from custom_components.loxone.pyloxone_api.connection import LoxoneConnection
from custom_components.loxone.pyloxone_api.exceptions import (
    LoxoneException,
    LoxoneOutOfServiceException,
)
from custom_components.loxone.pyloxone_api.message import (
    BinaryFile,
    DaytimerStatesTable,
    Keepalive,
    LLResponse,
    MessageHeader,
    MessageType,
    OutOfServiceIndicator,
    TextMessage,
    TextStatesTable,
    ValueStatesTable,
    WeatherStatesTable,
    _MESSAGE_CLASSES,
    check_and_decode_if_needed,
    parse_header,
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


# Fixed UUID prefix used across the ValueStatesTable tests. The exact
# value is irrelevant — we only need a stable uuid for round-tripping.
_UUID_BYTES = bytes.fromhex(
    "00112233445566778899aabbccddeeff"
)


def _value_record(uuid_bytes: bytes, value: float) -> bytes:
    """Build one 24-byte ValueStatesTable record: 16-byte uuid + 8-byte LE double."""
    return uuid_bytes + struct.pack("<d", value)


class TestValueStatesTable:
    """ValueStatesTable parses little-endian doubles correctly
    and tolerates a trailing partial record with a DEBUG log (not
    silent drop, not a crash).
    """

    def test_single_record_little_endian_double(self):
        payload = _value_record(_UUID_BYTES, 21.5)
        table = ValueStatesTable(payload)

        result = table.as_dict()

        assert len(result) == 1
        # The exact uuid string format is the Loxone compact form
        # (no dashes between the third/fourth and the trailing split).
        # uuid.UUID(bytes_le=...).urn gives ``urn:uuid:...`` — strip it.
        uuid_obj = __import__("uuid").UUID(bytes_le=_UUID_BYTES)
        fields = uuid_obj.urn.replace("urn:uuid:", "").split("-")
        expected_key = (
            f"{fields[0]}-{fields[1]}-{fields[2]}-{fields[3]}{fields[4]}"
        )
        assert expected_key in result
        assert result[expected_key] == 21.5

    def test_multiple_records(self):
        payload = (
            _value_record(bytes.fromhex("00112233445566778899aabbccddeeff"), 1.0)
            + _value_record(bytes.fromhex("ffeeddccbbaa99887766554433221100"), -3.5)
            + _value_record(bytes.fromhex("11111111111111111111111111111111"), 100.125)
        )
        table = ValueStatesTable(payload)

        result = table.as_dict()

        assert len(result) == 3
        assert all(isinstance(v, float) for v in result.values())
        # Spot-check one round-trip
        u = __import__("uuid").UUID(bytes_le=bytes.fromhex("11111111111111111111111111111111"))
        fields = u.urn.replace("urn:uuid:", "").split("-")
        expected_key = (
            f"{fields[0]}-{fields[1]}-{fields[2]}-{fields[3]}{fields[4]}"
        )
        assert result[expected_key] == 100.125

    def test_little_endian_format_used_not_native(self):
        """Sanity check: the parser actually uses ``<d``. If a future
        refactor regresses to ``"d"``, this test still passes on
        little-endian hosts but at least documents the contract.
        """
        # 1.0 in IEEE-754 double is 0x3FF0000000000000.
        # Little-endian bytes: 00 00 00 00 00 00 F0 3F
        # Big-endian bytes:    3F F0 00 00 00 00 00 00
        le_payload = _value_record(_UUID_BYTES, 1.0)
        assert le_payload[16:] == bytes.fromhex("000000000000F03F")

        table = ValueStatesTable(le_payload)
        result = table.as_dict()
        uuid_obj = __import__("uuid").UUID(bytes_le=_UUID_BYTES)
        fields = uuid_obj.urn.replace("urn:uuid:", "").split("-")
        expected_key = (
            f"{fields[0]}-{fields[1]}-{fields[2]}-{fields[3]}{fields[4]}"
        )
        # If the parser were reading big-endian, this would be a very
        # small number (~1.4e-313), not 1.0.
        assert result[expected_key] == 1.0

    def test_trailing_partial_record_does_not_crash(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A trailing partial record (less than 24 bytes) is dropped
        and a DEBUG log line is emitted (not silent drop, not crash).
        """
        payload = (
            _value_record(_UUID_BYTES, 42.0)
            + b"\x00\x01\x02\x03\x04\x05\x06\x07\x08\x09"  # 10 trailing bytes
        )
        assert len(payload) == 34

        table = ValueStatesTable(payload)

        with caplog.at_level(logging.DEBUG, logger="custom_components.loxone.pyloxone_api.message"):
            result = table.as_dict()

        # Only the first full record is parsed; the trailing 10 bytes
        # are dropped.
        assert len(result) == 1
        uuid_obj = __import__("uuid").UUID(bytes_le=_UUID_BYTES)
        fields = uuid_obj.urn.replace("urn:uuid:", "").split("-")
        expected_key = (
            f"{fields[0]}-{fields[1]}-{fields[2]}-{fields[3]}{fields[4]}"
        )
        assert result[expected_key] == 42.0

        # The DEBUG log announces the drop.
        assert any(
            "trailing partial record of 10 byte" in r.message
            for r in caplog.records
        )

    def test_empty_message(self):
        table = ValueStatesTable(b"")
        assert table.as_dict() == {}

    def test_only_partial_record(self, caplog: pytest.LogCaptureFixture) -> None:
        """A payload that is entirely a partial record yields an empty
        dict and a DEBUG log line.
        """
        table = ValueStatesTable(b"\x00\x01\x02")

        with caplog.at_level(logging.DEBUG, logger="custom_components.loxone.pyloxone_api.message"):
            result = table.as_dict()

        assert result == {}
        assert any(
            "trailing partial record of 3 byte" in r.message
            for r in caplog.records
        )


class TestCheckAndDecodeIfNeeded:
    """Decode utf-8 first, fall back to latin-1.

    Replaces the previous multi-stage detector + SHA-256 cache. Every
    byte 0-255 has a valid latin-1 code point, so the fallback is
    total and loss-free — no ``U+FFFD`` replacement characters, no
    expensive detector, no cache.
    """

    def test_str_passthrough(self):
        assert check_and_decode_if_needed("hello") == "hello"

    def test_bytes_utf8_round_trip(self):
        # Plain ASCII / UTF-8: the happy path
        assert check_and_decode_if_needed(b"hello") == "hello"
        # Multibyte UTF-8 sequences (e.g. German umlaut)
        assert check_and_decode_if_needed("Ége".encode("utf-8")) == "Ége"
        # 3-byte UTF-8: CJK
        assert check_and_decode_if_needed("日本語".encode("utf-8")) == "日本語"

    def test_bytearray_accepted(self):
        # ``bytes(bytearray(...))`` is the conversion path used by
        # ``check_and_decode_if_needed``; ensure bytearray input works.
        assert check_and_decode_if_needed(bytearray(b"hello")) == "hello"

    def test_non_utf8_falls_back_to_latin1(self):
        # 0xC3 alone is not valid UTF-8 (it's a lead byte without a
        # continuation). latin-1 maps it to U+00C3 ("Ã"), so the
        # fallback returns a clean string with no replacement chars.
        result = check_and_decode_if_needed(b"\xc3")
        assert result == "Ã"
        # Confirm no U+FFFD was inserted
        assert "\ufffd" not in result

    def test_non_utf8_high_bytes(self):
        # A sequence of bytes that is invalid UTF-8 but valid latin-1.
        # 0xA0 = NBSP in latin-1, 0xE9 = "é" in latin-1.
        result = check_and_decode_if_needed(b"\xa0\xe9\xff")
        assert result == "\u00a0\u00e9\u00ff"
        assert "\ufffd" not in result

    def test_empty_bytes(self):
        assert check_and_decode_if_needed(b"") == ""

    def test_no_replacement_chars_anywhere(self):
        """Sweep every byte value 0x00..0xFF — latin-1 must never
        raise and must never insert ``U+FFFD``.
        """
        for byte_val in range(256):
            b = bytes([byte_val])
            result = check_and_decode_if_needed(b)
            # latin-1 maps each byte to itself as a code point.
            assert result == chr(byte_val), (
                f"byte 0x{byte_val:02x} decoded to {result!r}, expected "
                f"{chr(byte_val)!r}"
            )
            assert "\ufffd" not in result

    def test_no_caching_side_effects(self):
        """The previous implementation had a module-level
        ``_encoding_cache`` that grew without limit. The simplified
        version must not have any such state.
        """
        import custom_components.loxone.pyloxone_api.message as message_mod

        assert not hasattr(message_mod, "_encoding_cache")
        assert not hasattr(message_mod, "detect_encoding")


class TestParseMessageDispatch:
    """``parse_message`` uses an explicit dispatch table
    (``{MessageType.X: HandlerClass}``) instead of the previous
    ``BaseMessage.__subclasses__()`` introspection loop.
    """

    @pytest.mark.parametrize(
        ("message_type", "expected_class"),
        [
            (MessageType.TEXT, TextMessage),
            (MessageType.BINARY, BinaryFile),
            (MessageType.VALUE_STATES, ValueStatesTable),
            (MessageType.TEXT_STATES, TextStatesTable),
            (MessageType.DAYTIMER_STATES, DaytimerStatesTable),
            (MessageType.OUT_OF_SERVICE, OutOfServiceIndicator),
            (MessageType.KEEPALIVE, Keepalive),
            (MessageType.WEATHER_STATES, WeatherStatesTable),
        ],
    )
    def test_dispatch_table_covers_every_known_type(
        self, message_type: MessageType, expected_class: type
    ) -> None:
        # Every non-UNKNOWN MessageType must have an entry.
        assert _MESSAGE_CLASSES[message_type] is expected_class

    def test_unknown_type_is_not_in_dispatch(self) -> None:
        # UNKNOWN is intentionally absent — there is no handler class
        # for it and ``parse_message`` must raise.
        assert MessageType.UNKNOWN not in _MESSAGE_CLASSES

    @pytest.mark.parametrize(
        ("message_type", "expected_class", "payload"),
        [
            # TEXT goes through ``LLResponse`` at construction, so
            # its payload must be valid LL JSON.
            (
                MessageType.TEXT,
                TextMessage,
                b'{"LL": {"control": "jdev/sps/io/x", "value": "1", "code": "200"}}',
            ),
            # All other handlers only stash the bytes and parse on
            # ``as_dict()`` — empty bytes are enough for the
            # ``isinstance`` check.
            (MessageType.BINARY, BinaryFile, b""),
            (MessageType.VALUE_STATES, ValueStatesTable, b""),
            (MessageType.TEXT_STATES, TextStatesTable, b""),
            (MessageType.DAYTIMER_STATES, DaytimerStatesTable, b""),
            (MessageType.OUT_OF_SERVICE, OutOfServiceIndicator, b""),
            (MessageType.KEEPALIVE, Keepalive, b""),
            (MessageType.WEATHER_STATES, WeatherStatesTable, b""),
        ],
    )
    def test_parse_message_returns_dispatched_class(
        self,
        message_type: MessageType,
        expected_class: type,
        payload: bytes,
    ) -> None:
        msg = parse_message(payload, message_type.value)
        assert isinstance(msg, expected_class)

    def test_parse_message_int_enum_value(self) -> None:
        # The dispatch table is keyed on the IntEnum but the public
        # API accepts a raw int — this is what the websocket header
        # gives us.
        msg = parse_message(
            b'{"LL": {"control": "jdev/sps/io/x", "value": "1", "code": "200"}}',
            MessageType.TEXT.value,
        )
        assert isinstance(msg, TextMessage)

    def test_parse_message_unknown_int_raises(self) -> None:
        # 9999 is not a valid MessageType — should raise
        # ``LoxoneException``.
        with pytest.raises(LoxoneException):
            parse_message(b"x", 9999)

    def test_parse_message_unknown_enum_member_raises(self) -> None:
        # Same intent via a synthesised enum value.
        with pytest.raises(LoxoneException):
            parse_message(b"x", 42)

    def test_dispatch_does_not_depend_on_import_order(self) -> None:
        # The previous ``__subclasses__()`` introspection was sensitive
        # to import order — re-importing ``message`` and re-creating
        # subclasses would have missed any subclass registered *after*
        # the original parse. The dict-based dispatch is static; this
        # test asserts it has exactly the eight expected entries and
        # nothing more.
        assert len(_MESSAGE_CLASSES) == 8
        assert set(_MESSAGE_CLASSES.keys()) == {
            MessageType.TEXT,
            MessageType.BINARY,
            MessageType.VALUE_STATES,
            MessageType.TEXT_STATES,
            MessageType.DAYTIMER_STATES,
            MessageType.OUT_OF_SERVICE,
            MessageType.KEEPALIVE,
            MessageType.WEATHER_STATES,
        }


class TestMessageHeaderDefaults:
    """``MessageHeader`` always populates ``message_type``,
    ``estimated`` and ``payload_length``. For non-0x03 frames all
    three are well-defined defaults (``UNKNOWN`` / ``False`` / ``0``)
    so the recv state machine in ``_do_start_listening`` can index
    them without conditional guards.

    Also covers the ``estimated`` bit-set/clear semantics and the
    short-header guard.
    """

    def test_non_03_frame_defaults(self):
        """A frame whose first byte is not ``0x03`` is treated as a
        bodyless unknown event — type UNKNOWN, no body, not
        estimated. This is the fix: the previous code left
        ``estimated`` / ``payload_length`` unset, raising
        ``AttributeError`` when the state machine tried to index
        them.
        """
        hdr = MessageHeader(b"\x04\x00\x00\x00\x00\x00\x00\x00")
        assert hdr.message_type == MessageType.UNKNOWN
        assert hdr.estimated is False
        assert hdr.payload_length == 0

    def test_short_header_treated_as_bodyless(self):
        """A header shorter than 8 bytes is treated as bodyless
        unknown. The previous code raised ``IndexError`` on the
        ``header[0]`` check.
        """
        hdr = MessageHeader(b"\x03\x00")
        assert hdr.message_type == MessageType.UNKNOWN
        assert hdr.estimated is False
        assert hdr.payload_length == 0

    def test_empty_header_treated_as_bodyless(self):
        hdr = MessageHeader(b"")
        assert hdr.message_type == MessageType.UNKNOWN
        assert hdr.estimated is False
        assert hdr.payload_length == 0

    def test_03_frame_unpacks_fields(self):
        """Standard ``0x03``-prefixed header unpacks message_type,
        estimated bit, payload_length. ``estimated`` is the high
        bit of byte index 2.
        """
        # Build a known header by hand:
        #   byte 0: 0x03 (binary marker)
        #   byte 1: MessageType.TEXT (0)
        #   byte 2: 0x00 (estimated bit clear)
        #   byte 3: 0x00 (reserved)
        #   bytes 4-7: payload_length = 1234 (LE)
        hdr_bytes = (
            b"\x03"
            + bytes([MessageType.TEXT])
            + b"\x00"
            + b"\x00"
            + (1234).to_bytes(4, "little")
        )
        hdr = MessageHeader(hdr_bytes)
        assert hdr.message_type == MessageType.TEXT
        assert hdr.estimated is False
        assert hdr.payload_length == 1234

    def test_estimated_bit_set(self):
        """``estimated`` is the high bit of byte index 2."""
        hdr_bytes = (
            b"\x03"
            + bytes([MessageType.VALUE_STATES])
            + b"\x80"  # high bit set
            + b"\x00"
            + (5678).to_bytes(4, "little")
        )
        hdr = MessageHeader(hdr_bytes)
        assert hdr.message_type == MessageType.VALUE_STATES
        assert hdr.estimated is True
        assert hdr.payload_length == 5678

    def test_parse_header_equivalent_to_constructor(self):
        """``parse_header`` is the module-level convenience
        constructor — must agree with ``MessageHeader(...)``.
        """
        hdr_bytes = (
            b"\x03"
            + bytes([MessageType.TEXT_STATES])
            + b"\x00"
            + b"\x00"
            + (100).to_bytes(4, "little")
        )
        hdr_via_ctor = MessageHeader(hdr_bytes)
        hdr_via_helper = parse_header(hdr_bytes)
        assert (
            hdr_via_ctor.message_type == hdr_via_helper.message_type
        )
        assert hdr_via_ctor.estimated == hdr_via_helper.estimated
        assert (
            hdr_via_ctor.payload_length == hdr_via_helper.payload_length
        )


def _loxone_header(message_type: int, payload_length: int, estimated: bool = False) -> bytes:
    """Build an 8-byte Loxone binary header.

    Layout (little-endian):
      byte 0: 0x03
      byte 1: message_type (uint8)
      byte 2: cInfo (bit 7 = estimated)
      byte 3: reserved
      bytes 4-7: payload_length (uint32 LE)
    """
    info_byte = b"\x80" if estimated else b"\x00"
    return (
        b"\x03"
        + bytes([message_type])
        + info_byte
        + b"\x00"
        + payload_length.to_bytes(4, "little")
    )


class TestDoStartListeningStateMachine:
    """``_do_start_listening`` strict header-to-body frame
    sequencing.

    Driven by a fake ``LoxoneClientConnection`` that yields a
    scripted sequence of bytes — covering bodyless headers, body
    chunk concatenation, estimated-header termination by the next
    8-byte frame, and orphan-chunk rejection.
    """

    @pytest.fixture
    def fake_connection_factory(self):
        """Return a factory ``(yielded_frames) → FakeConnection``."""
        from collections.abc import AsyncIterator

        class _FakeConnection:
            def __init__(self, frames):
                self._frames = list(frames)
                self.protocol = SimpleNamespace(
                    state=SimpleNamespace(name="OPEN")
                )
                # The state machine in ``_do_start_listening``
                # checks ``connection.state == connection.state.CLOSED``
                # — give it a ``state`` whose ``CLOSED`` is a
                # distinct sentinel so the OPEN/CLOSED comparison
                # always returns False.
                self.state = SimpleNamespace(
                    CLOSED="CLOSED", OPEN="OPEN", name="OPEN"
                )

            async def __aiter__(self) -> AsyncIterator[bytes]:
                for frame in self._frames:
                    yield frame

            def __aenter__(self):
                return self

            def __aexit__(self, *args):
                return None

            async def send(self, *args, **kwargs):
                return None

            async def close(self, *args, **kwargs):
                return None

        return _FakeConnection

    @pytest.mark.asyncio
    async def test_keepalive_header_dispatches_no_body(
        self, fake_connection_factory
    ):
        """An 8-byte KEEPALIVE header (payload_length=0) fires the
        keepalive callback with no body consumed. State machine
        returns to "no header in progress" and can accept the
        next frame.
        """
        from custom_components.loxone.pyloxone_api.message import (
            MessageHeader as _MessageHeader,
        )

        # The keepalive callback receives a ``Keepalive("")``
        # whose ``as_dict()`` returns ``{"control": ..., ...}``.
        # We don't care about the dict shape — only that the
        # callback fires.
        fired: list[bool] = []

        async def callback(_data: dict) -> None:
            fired.append(True)

        keepalive_hdr = _loxone_header(MessageType.KEEPALIVE, 0)
        second_hdr = _loxone_header(MessageType.OUT_OF_SERVICE, 0)

        conn = fake_connection_factory([keepalive_hdr, second_hdr])

        connection = LoxoneConnection(
            host="192.0.2.1",
            username="user",
            password="password",
            port=8080,
        )
        # The OUT_OF_SERVICE second header should raise
        # LoxoneOutOfServiceException — that's how we know the
        # state machine returned to "no header in progress"
        # cleanly after the keepalive.
        with pytest.raises(LoxoneOutOfServiceException):
            await connection._do_start_listening(callback, conn)

        assert fired == [True]

    @pytest.mark.asyncio
    async def test_text_body_in_one_chunk(self, fake_connection_factory):
        """A TEXT header with payload_length=N followed by an
        N-byte body in a single chunk dispatches the parsed
        TextMessage and fires the callback.
        """
        fired: list[dict] = []

        async def callback(data: dict) -> None:
            fired.append(data)

        text_body = (
            b'{"LL": {"control": "jdev/sps/io/abc", "value": "1", "code": "200"}}'
        )
        text_hdr = _loxone_header(MessageType.TEXT, len(text_body))

        conn = fake_connection_factory([text_hdr, text_body])
        connection = LoxoneConnection(
            host="192.0.2.1",
            username="user",
            password="password",
            port=8080,
        )
        await connection._do_start_listening(callback, conn)

        assert len(fired) == 1
        assert fired[0]["control"] == "jdev/sps/io/abc"

    @pytest.mark.asyncio
    async def test_body_chunked_across_multiple_frames(
        self, fake_connection_factory
    ):
        """Body bytes split across several websocket frames are
        concatenated into the message queue. The dispatch fires
        once ``len(body_buffer) >= payload_length``.
        """
        fired: list[dict] = []

        async def callback(data: dict) -> None:
            fired.append(data)

        text_body = (
            b'{"LL": {"control": "jdev/sps/io/abc", "value": "1", "code": "200"}}'
        )
        # Split the body in three chunks: 20 + 30 + remainder.
        chunks = [text_body[:20], text_body[20:50], text_body[50:]]
        text_hdr = _loxone_header(MessageType.TEXT, len(text_body))

        conn = fake_connection_factory([text_hdr, *chunks])
        connection = LoxoneConnection(
            host="192.0.2.1",
            username="user",
            password="password",
            port=8080,
        )
        await connection._do_start_listening(callback, conn)

        assert len(fired) == 1
        assert fired[0]["control"] == "jdev/sps/io/abc"

    @pytest.mark.asyncio
    async def test_estimated_header_dispatches_on_next_header(
        self, fake_connection_factory
    ):
        """An ``estimated=True`` header's body length is
        approximate. The body terminates when the *next* 8-byte
        header arrives — everything accumulated up to (but
        excluding) that header is the body.
        """
        text_body = (
            b'{"LL": {"control": "jdev/sps/io/abc", "value": "1", "code": "200"}}'
        )
        first_hdr = _loxone_header(
            MessageType.TEXT, len(text_body), estimated=True
        )
        # Second header (terminator + start of next event):
        # KEEPALIVE. ``payload_length=0`` means it's bodyless.
        second_hdr = _loxone_header(MessageType.KEEPALIVE, 0)

        fired: list[dict] = []
        keepalive_fired: list[bool] = []

        async def callback(data: dict) -> None:
            if data.get("control") == "jdev/sps/io/abc":
                fired.append(data)
            elif data.get("keep_alive") == "received":
                keepalive_fired.append(True)

        conn = fake_connection_factory(
            [first_hdr, text_body, second_hdr]
        )
        connection = LoxoneConnection(
            host="192.0.2.1",
            username="user",
            password="password",
            port=8080,
        )
        await connection._do_start_listening(callback, conn)

        assert len(fired) == 1
        assert fired[0]["control"] == "jdev/sps/io/abc"
        assert keepalive_fired == [True]

    @pytest.mark.asyncio
    async def test_orphan_body_chunk_is_logged(
        self, fake_connection_factory, caplog: pytest.LogCaptureFixture
    ):
        """A non-8-byte frame arriving with no header in progress
        is logged at ERROR and ignored — the state machine does
        not crash and does not dispatch.
        """
        fired: list[dict] = []

        async def callback(data: dict) -> None:
            fired.append(data)

        # No header — just an orphan body chunk, then a
        # KEEPALIVE header to terminate.
        orphan = b"some body bytes that arrived first"
        keepalive_hdr = _loxone_header(MessageType.KEEPALIVE, 0)

        conn = fake_connection_factory([orphan, keepalive_hdr])
        connection = LoxoneConnection(
            host="192.0.2.1",
            username="user",
            password="password",
            port=8080,
        )

        await connection._do_start_listening(callback, conn)

        # The orphan was ignored; the KEEPALIVE fires (with empty
        # value).
        assert any(
            "Orphan body chunk" in r.message
            for r in caplog.records
        )

    @pytest.mark.asyncio
    async def test_non_03_header_dispatches_as_bodyless(
        self, fake_connection_factory
    ):
        """An 8-byte frame whose first byte is not ``0x03`` is
        treated as a bodyless UNKNOWN — no body consumed, state
        machine continues cleanly and the next frame is parsed
        normally.
        """
        keepalive_fired: list[bool] = []

        async def callback(data: dict) -> None:
            if data.get("keep_alive") == "received":
                keepalive_fired.append(True)

        non_03_frame = b"\x04\x00\x00\x00\x00\x00\x00\x00"
        # Followed by a normal KEEPALIVE so we know the loop
        # continued past the non-0x03 frame.
        keepalive_hdr = _loxone_header(MessageType.KEEPALIVE, 0)

        conn = fake_connection_factory([non_03_frame, keepalive_hdr])
        connection = LoxoneConnection(
            host="192.0.2.1",
            username="user",
            password="password",
            port=8080,
        )
        # No exception means the state machine continued past the
        # non-0x03 frame.
        await connection._do_start_listening(callback, conn)

        # The keepalive fired — the state machine survived the
        # non-0x03 frame.
        assert keepalive_fired == [True]
