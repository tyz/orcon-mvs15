"""Tests for the Home Assistant-free RAMSES session."""

from __future__ import annotations

import asyncio
import logging

from collections.abc import Callable
from unittest.mock import Mock

import pytest

from ramses.protocol import (
    Code12a0,
    RamsesID,
    RamsesPacket,
)
from ramses.session import PendingRequest, RamsesSession
from ramses.transport import (
    ConnectionState,
    TransportError,
)
from ramses.transport.loopback import LoopbackTransport

GATEWAY_ID = "18:149960"
FAN_ID = "29:224547"
TIMESTAMP = "2026-09-11T17:29:09+00:00"
HUMIDITY_RESPONSE = f"044 RP --- {FAN_ID} {GATEWAY_ID} --:------ 12A0 002 002F"


class FakeScheduler:
    """Record retry callbacks instead of waiting for real time."""

    def __init__(self) -> None:
        self.jobs: list[tuple[float, Callable[[], None]]] = []
        self.cancels: list[Mock] = []

    def __call__(self, delay: float, action: Callable[[], None]) -> Callable[[], None]:
        self.jobs.append((delay, action))
        cancel = Mock()
        self.cancels.append(cancel)
        return cancel


def envelope(msg: str) -> dict[str, str]:
    """Wrap a frame in the gateway receive envelope."""
    return {"ts": TIMESTAMP, "msg": msg}


async def settle() -> None:
    """Let the consumer task and its created tasks run."""
    for _ in range(20):
        await asyncio.sleep(0)


async def make_session(
    scheduler: FakeScheduler | None = None,
    *,
    transport: LoopbackTransport | None = None,
) -> tuple[RamsesSession, LoopbackTransport]:
    """Build and start a session over a loopback transport."""
    loopback = transport or LoopbackTransport(gateway_id=RamsesID(GATEWAY_ID))
    session = RamsesSession(loopback, scheduler=scheduler)
    await session.start()
    return session, loopback


def humidity_request() -> RamsesPacket:
    """Build a humidity request with its expected response."""
    return Code12a0.get(RamsesID(GATEWAY_ID), RamsesID(FAN_ID))


async def test_request_is_queued_before_it_is_published() -> None:
    """A fast response must find the request already pending."""

    class ObservingTransport(LoopbackTransport):
        """Record what the session knew when the packet was sent."""

        def __init__(self) -> None:
            super().__init__(gateway_id=RamsesID(GATEWAY_ID))
            self.pending_at_send: list[int] = []
            self.observe: Callable[[], int] = lambda: -1

        async def send(self, packet: RamsesPacket) -> None:
            self.pending_at_send.append(self.observe())
            await super().send(packet)

    transport = ObservingTransport()
    session = RamsesSession(transport)
    await session.start()
    transport.observe = lambda: len(session.pending_requests)

    await session.request(humidity_request())

    assert transport.pending_at_send == [1]
    assert len(session.pending_requests) == 1
    await session.stop()


async def test_a_response_removes_and_cancels_the_pending_request() -> None:
    """A matching response ends the retry and reaches the code subscriber."""
    scheduler = FakeScheduler()
    session, transport = await make_session(scheduler)
    seen: list[RamsesPacket] = []
    session.subscribe("12A0", lambda payload: seen.append(payload.packet))

    await session.request(humidity_request())
    await transport.receive_frame(HUMIDITY_RESPONSE, TIMESTAMP)
    await settle()

    assert session.pending_requests == ()
    scheduler.cancels[0].assert_called_once_with()
    assert [packet.code for packet in seen] == ["12A0"]
    await session.stop()


async def test_a_retry_timer_resends_the_request() -> None:
    """The pending request is published again and re-armed."""
    scheduler = FakeScheduler()
    session, transport = await make_session(scheduler)
    packet = humidity_request()

    await session.request(packet)
    scheduler.jobs[0][1]()
    await settle()

    assert transport.sent == [packet, packet]
    assert len(scheduler.jobs) == 2
    assert session.pending_requests[0].attempts == 1
    await session.stop()


async def test_retry_exhaustion_drops_the_request(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """After the last retry the request is reported and forgotten."""
    scheduler = FakeScheduler()
    session, transport = await make_session(scheduler)
    packet = humidity_request()
    assert packet.expected_response is not None
    packet.expected_response.max_retries = 0

    with caplog.at_level(logging.WARNING):
        await session.request(packet)
        scheduler.jobs[0][1]()
        await settle()

    assert "Request timed out" in caplog.text
    assert transport.sent == [packet]
    assert session.pending_requests == ()
    await session.stop()


async def test_a_late_retry_after_the_response_is_ignored() -> None:
    """A timer that already fired must not resend an answered request."""
    scheduler = FakeScheduler()
    session, transport = await make_session(scheduler)
    packet = humidity_request()

    await session.request(packet)
    await transport.receive_frame(HUMIDITY_RESPONSE, TIMESTAMP)
    await settle()
    scheduler.jobs[0][1]()
    await settle()

    assert transport.sent == [packet]
    await session.stop()


async def test_a_request_requires_an_expected_response() -> None:
    """A one-shot packet cannot be queued as a request."""
    session, _ = await make_session()
    packet = RamsesPacket(
        src_id=RamsesID(GATEWAY_ID),
        dst_id=RamsesID(FAN_ID),
        type="RQ",
        code="12A0",
        data="00",
    )

    with pytest.raises(ValueError, match="without an expected response"):
        await session.request(packet)

    await session.stop()


async def test_send_is_one_shot() -> None:
    """send() publishes once and does not wait for a response."""
    session, transport = await make_session()
    packet = humidity_request()

    await session.send(packet)

    assert transport.sent == [packet]
    assert session.pending_requests == ()
    await session.stop()


async def test_a_stopped_session_refuses_new_work() -> None:
    """A command after unload must fail instead of pretending to be sent."""
    session, _ = await make_session()
    await session.stop()

    with pytest.raises(TransportError, match="session is closed"):
        await session.send(humidity_request())

    with pytest.raises(TransportError, match="session is closed"):
        await session.request(humidity_request())


async def test_a_failing_retry_publish_drops_the_request() -> None:
    """A retry that cannot be published is not left pending forever."""

    class FailingTransport(LoopbackTransport):
        """A gateway that stops accepting packets after the first send."""

        fail = False

        async def send(self, packet: RamsesPacket) -> None:
            if self.fail:
                raise TransportError("broker down")
            await super().send(packet)

    scheduler = FakeScheduler()
    transport = FailingTransport(gateway_id=RamsesID(GATEWAY_ID))
    session = RamsesSession(transport, scheduler=scheduler)
    await session.start()
    packet = humidity_request()
    await session.request(packet)
    transport.fail = True

    scheduler.jobs[0][1]()
    await settle()

    assert session.pending_requests == ()
    await session.stop()


async def test_a_lowercase_code_reaches_its_handler() -> None:
    """A transport may deliver a lowercase code; subscribers still see it."""
    session, transport = await make_session()
    seen: list[str] = []
    session.subscribe("12A0", lambda payload: seen.append(payload.packet.code))

    await transport.receive_frame(HUMIDITY_RESPONSE.replace("12A0", "12a0"), TIMESTAMP)
    await settle()

    assert seen == ["12A0"]
    await session.stop()


async def test_code_and_raw_subscriptions_can_be_removed() -> None:
    """Every subscription returns its own unsubscribe callable."""
    session, transport = await make_session()
    code_calls: list[str] = []
    raw_calls: list[str] = []
    unsub_code = session.subscribe("12A0", lambda payload: code_calls.append("code"))
    unsub_raw = session.subscribe_raw(lambda item: raw_calls.append(item["msg"]))

    await transport.receive_frame(HUMIDITY_RESPONSE, TIMESTAMP)
    await settle()
    unsub_code()
    unsub_raw()
    await transport.receive_frame(HUMIDITY_RESPONSE, TIMESTAMP)
    await settle()

    assert code_calls == ["code"]
    assert raw_calls == [HUMIDITY_RESPONSE]
    assert session.subscribed_codes == set()
    await session.stop()


async def test_one_failing_subscriber_does_not_hide_the_others(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A broken callback is logged and the next callback still runs."""
    session, transport = await make_session()
    seen: list[str] = []

    def _broken(_payload: object) -> None:
        raise RuntimeError("boom")

    session.subscribe("12A0", _broken)
    session.subscribe("12A0", lambda _payload: seen.append("second"))

    with caplog.at_level(logging.ERROR):
        await transport.receive_frame(HUMIDITY_RESPONSE, TIMESTAMP)
        await settle()

    assert seen == ["second"]
    assert "subscriber failed" in caplog.text
    await session.stop()


async def test_unknown_codes_use_the_generic_decoder(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A code without a decoder still reaches its subscriber."""
    session, transport = await make_session()
    labels: list[object] = []
    session.subscribe("9999", lambda payload: labels.append(payload.values["_label"]))

    with caplog.at_level(logging.WARNING):
        await transport.receive_frame(
            f"044 RP --- {FAN_ID} {GATEWAY_ID} --:------ 9999 002 0000",
            TIMESTAMP,
        )
        await settle()

    assert labels == ["Unsupported code"]
    assert "There is no class for code 9999" in caplog.text
    await session.stop()


async def test_a_malformed_frame_is_logged_and_still_reaches_the_raw_tap(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The packet log sees malformed frames even though no codec runs."""
    session, transport = await make_session()
    raw: list[str] = []
    session.subscribe_raw(lambda item: raw.append(item["msg"]))

    with caplog.at_level(logging.ERROR):
        await transport.receive_frame("not a frame", TIMESTAMP)
        await settle()

    assert raw == ["not a frame"]
    assert "Error parsing a received frame" in caplog.text
    await session.stop()


async def test_connection_state_changes_reach_the_subscribers() -> None:
    """The transport's connection state is forwarded as one callback."""
    session, transport = await make_session()
    states: list[ConnectionState] = []
    session.subscribe_connection(states.append)

    transport.set_connection_state(ConnectionState.DISCONNECTED)
    await settle()

    assert states == [ConnectionState.DISCONNECTED]
    assert session.connection_state is ConnectionState.DISCONNECTED
    await session.stop()


async def test_gateway_versions_reach_the_subscribers() -> None:
    """The firmware version topic is forwarded to the subscribers."""
    session, transport = await make_session()
    versions: list[str] = []
    session.subscribe_version(versions.append)

    transport.receive_version("2026.10.1")
    await settle()

    assert versions == ["2026.10.1"]
    await session.stop()


async def test_frames_are_handled_in_arrival_order() -> None:
    """One consumer task serialises handling."""
    session, transport = await make_session()
    seen: list[str] = []
    session.subscribe("12A0", lambda payload: seen.append(payload.packet.data))

    await transport.receive_frame(HUMIDITY_RESPONSE, TIMESTAMP)
    await transport.receive_frame(
        f"044 RP --- {FAN_ID} {GATEWAY_ID} --:------ 12A0 002 0030", TIMESTAMP
    )
    await settle()

    assert seen == ["002F", "0030"]
    await session.stop()


async def test_stop_cancels_a_pending_retry() -> None:
    """An armed retry cannot publish after unload."""
    scheduler = FakeScheduler()
    session, transport = await make_session(scheduler)
    packet = humidity_request()
    await session.request(packet)

    await session.stop()
    scheduler.jobs[0][1]()
    await settle()

    assert transport.sent == [packet]
    assert session.pending_requests == ()


async def test_start_is_idempotent() -> None:
    """Starting an already running session does not add a second consumer."""
    session, _ = await make_session()
    consumer = session._consumer

    await session.start()

    assert session._consumer is consumer
    await session.stop()


async def test_a_pending_request_matches_through_its_expectation() -> None:
    """PendingRequest exposes the expectation used for matching."""
    packet = humidity_request()
    assert packet.expected_response is not None
    request = PendingRequest(packet, packet.expected_response)
    response = RamsesPacket(envelope=envelope(HUMIDITY_RESPONSE))

    assert request.matches(response)

    cancel = Mock()
    request.cancel_timer = cancel
    request.cancel()
    cancel.assert_called_once_with()
    assert request.cancel_timer is None


async def test_stopping_twice_is_safe() -> None:
    """Unloading an already stopped session is a no-op."""
    session, _ = await make_session()
    await session.stop()

    await session.stop()

    assert session.pending_requests == ()


async def test_the_consumer_logs_a_frame_that_raises(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A bug in the decode path is reported instead of killing the consumer."""
    session, transport = await make_session()
    session._handle_frame = Mock(side_effect=RuntimeError("boom"))  # type: ignore[method-assign]

    with caplog.at_level(logging.ERROR):
        await transport.receive_frame(HUMIDITY_RESPONSE, TIMESTAMP)
        await settle()

    assert "Failed to process Ramses-ESP message" in caplog.text
    await session.stop()


async def test_a_failing_raw_subscriber_is_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The raw tap isolates one broken subscriber."""
    session, transport = await make_session()

    def _broken(_envelope: object) -> None:
        raise RuntimeError("boom")

    session.subscribe_raw(_broken)

    with caplog.at_level(logging.ERROR):
        await transport.receive_frame(HUMIDITY_RESPONSE, TIMESTAMP)
        await settle()

    assert "subscriber failed" in caplog.text
    await session.stop()


async def test_async_code_subscribers_are_awaited() -> None:
    """A subscriber may be a coroutine function."""
    session, transport = await make_session()
    seen: list[int] = []

    async def _record(payload: object) -> None:
        await asyncio.sleep(0)
        seen.append(-59)

    session.subscribe("12A0", _record)

    await transport.receive_frame(HUMIDITY_RESPONSE, TIMESTAMP)
    await settle()

    assert seen == [-59]
    await session.stop()


async def test_async_and_failing_connection_and_version_subscribers(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Connection and version subscribers are awaited and isolated."""
    session, transport = await make_session()
    states: list[ConnectionState] = []
    versions: list[str] = []

    async def _record_state(state: ConnectionState) -> None:
        states.append(state)

    async def _record_version(version: str) -> None:
        versions.append(version)

    async def _broken(_argument: object) -> None:
        raise RuntimeError("boom")

    session.subscribe_connection(_record_state)
    session.subscribe_connection(_broken)
    session.subscribe_version(_record_version)
    session.subscribe_version(_broken)

    with caplog.at_level(logging.ERROR):
        transport.set_connection_state(ConnectionState.DISCONNECTED)
        transport.receive_version("2026.10.1")
        await settle()

    assert states == [ConnectionState.DISCONNECTED]
    assert versions == ["2026.10.1"]
    assert caplog.text.count("subscriber failed") == 2
    await session.stop()


async def test_a_resend_for_a_finished_request_is_ignored() -> None:
    """A resend that raced the response must not publish again."""
    scheduler = FakeScheduler()
    session, transport = await make_session(scheduler)
    packet = humidity_request()
    await session.request(packet)
    request = session.pending_requests[0]
    session._remove_request(request)

    await session._resend(request)

    assert transport.sent == [packet]
    await session.stop()
