from __future__ import annotations

import logging

from typing import Iterator

try:
    from .ramses_packet import RamsesPacket
except ImportError:
    pass  # for __main__

_LOGGER = logging.getLogger(__name__)


class RamsesPacketQueueException(Exception):
    pass


class RamsesPacketQueue:
    def __init__(self) -> None:
        self._queue: dict = {}

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self._queue})"

    def __len__(self) -> int:
        return len(self._queue)

    def __iter__(self) -> Iterator:
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

    def clear(self) -> None:
        for packet_id in list(self._queue):
            del self._queue[packet_id]


if __name__ == "__main__":
    import sys
    from ramses_packet import RamsesPacket, RamsesPacketResponse, RamsesID  # type: ignore[no-redef]

    _LOGGER = logging.getLogger()
    _LOGGER.setLevel(logging.DEBUG)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(levelname)s - %(message)s"))
    _LOGGER.addHandler(handler)

    q = RamsesPacketQueue()

    raw_response = {
        "ts": "2025-06-01T17:10:49.271376+02:00",
        "msg": "044 RP --- 29:224547 18:149960 --:------ 12A0 002 002F",
    }
    raw_response_other = {
        "ts": "2025-06-01T17:10:50.271376+02:00",
        "msg": "044 RP --- 29:224547 18:149960 --:------ 1298 003 0001CD",
    }
    rx = RamsesPacket(envelope=raw_response)
    rx_other = RamsesPacket(envelope=raw_response_other)

    tx = RamsesPacket(
        src_id=RamsesID("18:149960"),
        dst_id=RamsesID("29:224547"),
        type="RQ",
        code="12A0",
        data="00",
    )
    tx.expected_response = RamsesPacketResponse(
        src_id=RamsesID("29:224547"),
        dst_id=RamsesID("18:149960"),
        type="RP",
        code="12A0",
    )

    print("=== add (__contains__, __setitem__)")
    q.add(tx)
    q.add(tx)
    assert len(q) == 1, f"len after add is {len(q)}"

    print("=== get/del (__iter__, __getitem__, __delitem__)")
    p = q.get(rx_other)
    assert p is None, (
        "matched where it should not for {rx_other_other.type} {rx_other.code} {rx_other.src_id} {rx_other.dst_id} in {q._queue}"
    )
    p = q.get(rx)
    assert p is not None, (
        f"no match where it should for {rx.type} {rx.code} {rx.src_id} {rx.dst_id} in {q._queue}"
    )
    q.remove(p)
    assert len(q) == 0, f"len after del is {len(q)}"

    print("=== clear")
    q.clear()
    assert len(q) == 0, f"len after clear is {len(q)}"

    print("=== Done!")
