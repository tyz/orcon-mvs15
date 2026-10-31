"""Tests for the expected-response retry queue."""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from custom_components.orcon_mvs15.ramses_packet import (
    RamsesID,
    RamsesPacket,
    RamsesPacketResponse,
)
from custom_components.orcon_mvs15.ramses_packet_queue import RamsesPacketQueue

TIMESTAMP = "2026-09-11T17:29:09.534250+02:00"
FAN_ID = "29:224547"
GATEWAY_ID = "18:149960"


def received(msg: str) -> RamsesPacket:
    """Build a packet the way the gateway delivers it."""
    return RamsesPacket(envelope={"ts": TIMESTAMP, "msg": msg})


def humidity_request() -> RamsesPacket:
    """Build a 12A0 status request with its expected response."""
    packet = RamsesPacket(
        src_id=RamsesID(GATEWAY_ID),
        dst_id=RamsesID(FAN_ID),
        type="RQ",
        code="12A0",
        data="00",
    )
    packet.expected_response = RamsesPacketResponse(
        src_id=RamsesID(FAN_ID),
        dst_id=RamsesID(GATEWAY_ID),
        type="RP",
        code="12A0",
    )
    return packet


def test_add_requires_an_expected_response() -> None:
    """A packet without an expected response can never be matched."""
    queue = RamsesPacketQueue()
    packet = RamsesPacket(
        src_id=RamsesID(GATEWAY_ID),
        dst_id=RamsesID(FAN_ID),
        type="RQ",
        code="12A0",
        data="00",
    )

    with pytest.raises(AssertionError):
        queue.add(packet)


def test_add_is_idempotent() -> None:
    """Adding the same packet twice keeps one queue entry."""
    queue = RamsesPacketQueue()
    packet = humidity_request()

    queue.add(packet)
    queue.add(packet)

    assert len(queue) == 1
    assert packet in queue


def test_get_matches_the_expected_response() -> None:
    """A response is matched by type, code, source and destination."""
    queue = RamsesPacketQueue()
    request = humidity_request()
    queue.add(request)

    response = received(f"044 RP --- {FAN_ID} {GATEWAY_ID} --:------ 12A0 002 002F")

    assert queue.get(response) is request


def test_get_ignores_other_codes() -> None:
    """A different code does not satisfy an outstanding request."""
    queue = RamsesPacketQueue()
    queue.add(humidity_request())

    other = received(f"044 RP --- {FAN_ID} {GATEWAY_ID} --:------ 1298 003 0001CD")

    assert queue.get(other) is None


def test_get_on_empty_queue_returns_none() -> None:
    """An empty queue has nothing to match."""
    queue = RamsesPacketQueue()
    response = received(f"044 RP --- {FAN_ID} {GATEWAY_ID} --:------ 12A0 002 002F")

    assert queue.get(response) is None


def test_remove_calls_the_cancel_retry_handler() -> None:
    """Removing a matched packet stops its retry timer."""
    queue = RamsesPacketQueue()
    request = humidity_request()
    expected = request.expected_response
    assert expected is not None
    cancel = Mock()
    expected.cancel_retry_handler = cancel
    queue.add(request)

    queue.remove(request)

    cancel.assert_called_once_with()
    assert len(queue) == 0


def test_remove_without_cancel_handler() -> None:
    """A packet without a retry timer can still be removed."""
    queue = RamsesPacketQueue()
    request = humidity_request()
    queue.add(request)

    queue.remove(request)

    assert len(queue) == 0


def test_remove_unknown_packet_raises() -> None:
    """Removing a packet that is not queued is an error."""
    queue = RamsesPacketQueue()

    with pytest.raises(KeyError):
        queue.remove(humidity_request())


def test_clear_empties_the_queue() -> None:
    """Clearing drops every outstanding request."""
    queue = RamsesPacketQueue()
    queue.add(humidity_request())

    queue.clear()

    assert len(queue) == 0
    assert (
        queue.get(received(f"044 RP --- {FAN_ID} {GATEWAY_ID} --:------ 12A0 002 002F"))
        is None
    )


def test_iteration_yields_queued_packets() -> None:
    """Iterating yields the packets themselves, not their ids."""
    queue = RamsesPacketQueue()
    request = humidity_request()
    queue.add(request)

    assert list(queue) == [request]


def test_repr_shows_the_queued_packet_ids() -> None:
    """The queue is inspectable while debugging retries."""
    queue = RamsesPacketQueue()
    request = humidity_request()
    queue.add(request)

    text = repr(queue)

    assert text.startswith("RamsesPacketQueue({")
    assert request.packet_id in text
