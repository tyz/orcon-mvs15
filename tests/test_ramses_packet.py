"""Tests for Ramses packet parsing, ids and expected-response matching."""

from __future__ import annotations

from datetime import datetime

import pytest

from custom_components.orcon_mvs15.ramses_packet import (
    RamsesID,
    RamsesPacket,
    RamsesPacketData,
    RamsesPacketDatetime,
    RamsesPacketException,
    RamsesPacketResponse,
)

TIMESTAMP = "2026-09-11T17:29:09.534250+02:00"
FAN_ID = "29:224547"
GATEWAY_ID = "18:149960"


def envelope(msg: str, ts: str = TIMESTAMP) -> dict[str, str]:
    """Build a gateway receive envelope around a raw frame."""
    return {"ts": ts, "msg": msg}


def test_parse_received_frame() -> None:
    """A gateway frame is split into signal, ids, code, length and data."""
    packet = RamsesPacket(
        envelope=envelope("081  I --- 29:123456 29:654321 --:------ 22F1 003 000404")
    )

    assert packet.signal_strength == 81
    assert packet.type == "I"
    assert packet.src_id == "29:123456"
    assert packet.dst_id == "29:654321"
    assert packet.ann_id == "--:------"
    assert packet.code == "22F1"
    assert packet.length == 3
    assert packet.data == "000404"


def test_parse_frame_without_data_field() -> None:
    """A frame without data has length zero and no data."""
    packet = RamsesPacket(
        envelope=envelope(f"000  RQ --- {GATEWAY_ID} {FAN_ID} --:------ 1FC9 000")
    )

    assert packet.length == 0
    assert len(packet.data) == 0


@pytest.mark.parametrize(
    "msg",
    [
        # Declared length does not match the number of data bytes.
        f"081  I --- {FAN_ID} {GATEWAY_ID} --:------ 22F1 004 000404",
        # A non-zero length without a data field.
        f"081  I --- {FAN_ID} {GATEWAY_ID} --:------ 22F1 003",
        # Missing the --- separator.
        f"081  I {FAN_ID} {GATEWAY_ID} --:------ 22F1 003 000404",
    ],
)
def test_malformed_frame_raises(msg: str) -> None:
    """Malformed frames fail loudly instead of being half parsed."""
    with pytest.raises(AssertionError):
        RamsesPacket(envelope=envelope(msg))


def test_signal_strength_is_signed_on_the_wire() -> None:
    """The gateway sends a positive RSSI; the packet stores it as-is."""
    packet = RamsesPacket(
        envelope=envelope(f"044 RP --- {FAN_ID} {GATEWAY_ID} --:------ 12A0 002 002F")
    )

    assert packet.signal_strength == 44


def test_unknown_signal_strength_becomes_minus_one() -> None:
    """A non-numeric signal strength is logged and stored as -1."""
    packet = RamsesPacket(
        envelope=envelope(f"??  I --- {FAN_ID} {GATEWAY_ID} --:------ 12A0 002 002F")
    )

    assert packet.signal_strength == -1


def test_published_envelope_has_no_signal_strength() -> None:
    """Outgoing frames use the gateway's publish format.

    The type is padded to two characters, so a single character type is
    followed by two spaces before the separator: ``I  ---``.
    """
    packet = RamsesPacket(
        src_id=RamsesID(GATEWAY_ID),
        dst_id=RamsesID(FAN_ID),
        type="I",
        code="22F1",
        data="000404",
    )

    assert packet.ramses_esp_envelope() == {
        "msg": f"I  --- {GATEWAY_ID} {FAN_ID} --:------ 22F1 003 000404"
    }


def test_packet_data_length_is_bytes() -> None:
    """RamsesPacketData reports bytes, not hex characters."""
    data = RamsesPacketData("000404")

    assert len(data) == 3
    assert len(RamsesPacketData("")) == 0


def test_packet_data_rejects_odd_hex() -> None:
    """Half a byte is not a valid payload."""
    with pytest.raises(RamsesPacketException):
        len(RamsesPacketData("00040"))


def test_ramses_id_default_is_the_empty_address() -> None:
    """The default id is the empty address and is falsy."""
    empty = RamsesID()

    assert empty == "--:------"
    assert not empty


def test_ramses_id_is_truthy_when_set() -> None:
    """A real id is truthy; an empty string falls back to the empty address."""
    assert RamsesID(FAN_ID)
    assert not RamsesID("")


def test_datetime_parses_iso_timestamp() -> None:
    """The gateway timestamp is kept as ISO 8601."""
    stamp = RamsesPacketDatetime(TIMESTAMP)

    assert repr(stamp) == TIMESTAMP
    assert stamp.t_datetime is not None
    assert stamp.t_datetime.year == 2026


def test_datetime_parses_hex_date() -> None:
    """Hex dates are day, month, year, with day-of-week in the top bits."""
    stamp = RamsesPacketDatetime("050107E9")
    with_day_of_week = RamsesPacketDatetime("250107E9")

    assert stamp.t_str == "2025-01-05"
    assert stamp.t_datetime == datetime(2025, 1, 5)
    assert with_day_of_week.t_str == "2025-01-05"


def test_datetime_ffffffff_is_no_date() -> None:
    """FFFFFFFF means the field carries no date."""
    stamp = RamsesPacketDatetime("FFFFFFFF")

    assert stamp.t_datetime is None
    assert repr(stamp) == "FFFFFFFF"


def test_datetime_rejects_invalid_input() -> None:
    """Invalid timestamps and unsupported types raise a packet exception."""
    with pytest.raises(RamsesPacketException):
        RamsesPacketDatetime("not a timestamp")
    with pytest.raises(RamsesPacketException):
        RamsesPacketDatetime(123)


def test_response_matches_type_code_source_and_destination() -> None:
    """An expected response must match all four identifying fields."""
    expected = RamsesPacketResponse(
        src_id=RamsesID(FAN_ID),
        dst_id=RamsesID(GATEWAY_ID),
        type="RP",
        code="12A0",
    )
    response = RamsesPacket(
        envelope=envelope(f"044 RP --- {FAN_ID} {GATEWAY_ID} --:------ 12A0 002 002F")
    )

    assert expected == response


@pytest.mark.parametrize(
    "msg",
    [
        f"044 RP --- {FAN_ID} {GATEWAY_ID} --:------ 1298 002 002F",
        f"044 I --- {FAN_ID} {GATEWAY_ID} --:------ 12A0 002 002F",
        f"044 RP --- {GATEWAY_ID} {FAN_ID} --:------ 12A0 002 002F",
        f"044 RP --- {FAN_ID} 29:123456 --:------ 12A0 002 002F",
    ],
)
def test_response_does_not_match_other_packets(msg: str) -> None:
    """A different code, type, source or destination is not our response."""
    expected = RamsesPacketResponse(
        src_id=RamsesID(FAN_ID),
        dst_id=RamsesID(GATEWAY_ID),
        type="RP",
        code="12A0",
    )

    assert expected != RamsesPacket(envelope=envelope(msg))


def test_response_with_empty_fields_matches_anything() -> None:
    """An unspecified expected response matches any packet."""
    expected = RamsesPacketResponse()

    assert expected == RamsesPacket(
        envelope=envelope(f"044  I --- {FAN_ID} {GATEWAY_ID} --:------ 31D9 003 000004")
    )


def test_response_never_matches_a_non_packet() -> None:
    """Comparing with an unrelated object is not an error."""
    assert RamsesPacketResponse() != "not a packet"
