import logging

_LOGGER = logging.getLogger(__name__)


class RamsesPacketQueue:
    def __init__(self):
        self._queue = {}

    def __repr__(self):
        return f"{self.__class__.__name__}({self._queue})"

    def __len__(self):
        return len(self._queue)

    def __iter__(self):
        return iter(self._queue.values())

    def __contains__(self, packet):
        return packet.packet_id in self._queue

    def __setitem__(self, packet_id, packet):
        self._queue[packet_id] = packet

    def __delitem__(self, packet):
        if packet.packet_id in self._queue:
            self._call_cancel_retry_handler(self._queue[packet.packet_id])
            del self._queue[packet.packet_id]
        else:
            raise KeyError(f"__delitem__: Packet ID {packet.packet_id} not found")

    def _call_cancel_retry_handler(self, packet):
        if packet.expected_response is not None and callable(
            packet.expected_response.cancel_retry_handler
        ):
            packet.expected_response.cancel_retry_handler()
        else:
            _LOGGER.debug(
                f"_call_cancel_retry_handler: {packet.packet_id} has no cancel_retry_handler"
            )

    def add(self, packet):
        if packet not in self:
            self[packet.packet_id] = packet
        else:
            _LOGGER.debug(f"add: Already in queue: {packet.packet_id}")

    def get(self, packet):
        if not self:
            _LOGGER.debug("match: Queue is empty")
            return None
        match = next((q for q in self if q.expected_response == packet), None)
        if not match:
            _LOGGER.debug(f"match: Not found in queue: {packet}")
        return match

    def remove(self, packet):
        del self[packet]

    def clear(self):
        for packet_id in list(self._queue):
            del self._queue[packet_id]


if __name__ == "__main__":
    import sys
    from ramses_packet import RamsesPacket, RamsesPacketResponse

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
    rx = RamsesPacket(raw_packet=raw_response)
    rx_other = RamsesPacket(raw_packet=raw_response_other)

    tx = RamsesPacket(
        src_id="18:149960",
        dst_id="29:224547",
        type="RQ",
        code="12A0",
        data="00",
        expected_response=RamsesPacketResponse(
            src_id="29:224547",
            dst_id="18:149960",
            type="RP",
            code="12A0",
        ),
    )

    print("=== add (__contains__, __setitem__)")
    q.add(tx)
    q.add(tx)
    assert len(q) == 1, f"len after add is {len(q)}"

    print("=== get/del (__iter__, __getitem__, __delitem__)")
    p = q.get(rx_other)
    assert p is None, "matched"
    p = q.get(rx)
    assert p is not None, "no match"
    q.remove(p)
    assert len(q) == 0, f"len after del is {len(q)}"

    print("=== clear")
    q.clear()
    assert len(q) == 0, f"len after clear is {len(q)}"

    print("=== Done!")
