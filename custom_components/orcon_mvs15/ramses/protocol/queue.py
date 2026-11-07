"""Outgoing packets waiting for their expected response."""

from __future__ import annotations

import logging

from collections.abc import Iterator

from .frame import RamsesPacket

_LOGGER = logging.getLogger(__name__)


class RamsesPacketQueueException(Exception):
    pass


class RamsesPacketQueue:
    def __init__(self) -> None:
        self._queue: dict[str, RamsesPacket] = {}

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self._queue})"

    def __len__(self) -> int:
        return len(self._queue)

    def __iter__(self) -> Iterator[RamsesPacket]:
        return iter(self._queue.values())

    def __contains__(self, packet: RamsesPacket) -> bool:
        return packet.packet_id in self._queue

    def __setitem__(self, packet_id: str, packet: RamsesPacket) -> None:
        self._queue[packet_id] = packet

    def __delitem__(self, packet: RamsesPacket) -> None:
        if packet.packet_id in self._queue:
            self._call_cancel_retry_handler(self._queue[packet.packet_id])
            del self._queue[packet.packet_id]
        else:
            raise KeyError(f"__delitem__: Packet ID {packet.packet_id} not found")

    def _call_cancel_retry_handler(self, packet: RamsesPacket) -> None:
        if packet.expected_response is not None and callable(
            packet.expected_response.cancel_retry_handler
        ):
            packet.expected_response.cancel_retry_handler()
        else:
            _LOGGER.debug(
                f"_call_cancel_retry_handler: {packet.packet_id} has no cancel_retry_handler"
            )

    def add(self, packet: RamsesPacket) -> None:
        assert packet.expected_response, (
            f"Adding packet w/o expected_response: {packet}"
        )
        if packet not in self:
            self[packet.packet_id] = packet
        else:
            _LOGGER.debug(f"add: Already in queue: {packet.packet_id}")

    def get(self, packet: RamsesPacket) -> RamsesPacket | None:
        if not self:
            _LOGGER.debug("get: Queue is empty")
            return None
        for q in self:
            if q.expected_response == packet:
                return q
        _LOGGER.debug(
            f"get: Not found in queue: {packet.type} {packet.code} {packet.src_id}->{packet.dst_id}"
        )
        return None

    def remove(self, packet: RamsesPacket) -> None:
        del self[packet]

    def discard(self, packet: RamsesPacket) -> None:
        """Remove a packet if it is still queued.

        A response and a retry timer can race: the response cancels the timer,
        but a timer that already fired still runs its callback. Whoever runs
        second must not raise for a packet that is already gone.
        """
        if packet in self:
            self.remove(packet)

    def clear(self) -> None:
        for packet_id in list(self._queue):
            del self._queue[packet_id]
