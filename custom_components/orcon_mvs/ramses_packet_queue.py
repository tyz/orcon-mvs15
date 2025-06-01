import asyncio
import logging

_LOGGER = logging.getLogger(__name__)


class RamsesPacketQueue:
    def __init__(self):
        self._queue_lock = asyncio.Lock()
        self._queue = {}

    def __repr__(self):
        return str(self._queue)

    def __len__(self):
        return len(self._queue)

    def _call_cancel_retry_handler(self, packet):
        if packet.expected_response is not None and callable(packet.expected_response.cancel_retry_handler):
            packet.expected_response.cancel_retry_handler()
            _LOGGER.debug(f"_call_cancel_retry_handler: Cancelled retry handler: {packet.packet_id}")
        else:
            _LOGGER.debug(f"_call_cancel_retry_handler: {packet.packet_id} has no cancel_retry_handler")

    async def add(self, packet):
        async with self._queue_lock:
            if packet.packet_id not in self._queue:
                self._queue[packet.packet_id] = packet
                _LOGGER.debug(f"add: Added to queue: {packet.packet_id}")
            else:
                _LOGGER.debug(f"add: Already in queue: {packet.packet_id}")

    async def match(self, packet):
        async with self._queue_lock:
            if not self._queue:
                _LOGGER.debug("match: Empty queue")
                return
            match = next((q for q in self._queue.values() if q.expected_response == packet), None)
            if match:
                _LOGGER.debug(f"match: Found in queue: {match.packet_id}")
                return match
            _LOGGER.debug(f"match: Not found in queue: {packet}")
            return None

    async def remove(self, packet):
        async with self._queue_lock:
            if packet.packet_id in self._queue:
                self._call_cancel_retry_handler(packet)
                del self._queue[packet.packet_id]
                _LOGGER.debug(f"remove: Removed from queue: {packet.packet_id}")
            else:
                _LOGGER.debug(f"remove: Not in queue: {packet.packet_id}")

    async def empty(self):
        async with self._queue_lock:
            if not self._queue:
                return
            for q_id, q_packet in self._queue.items():
                self._call_cancel_retry_handler(q_packet)
                _LOGGER.debug(f"empty: Removed {q_id}")
            self._queue = {}
            _LOGGER.debug("empty: Emptied queue")


if __name__ == "__main__":
    import sys
    from ramses_packet import RamsesPacket, RamsesPacketResponse

    async def main():

        q = RamsesPacketQueue()

        raw_response = {
            "ts": "2025-06-01T17:10:49.271376+02:00",
            "msg": "044 RP --- 29:224547 18:149960 --:------ 12A0 002 002F",
        }
        rx = RamsesPacket(raw_packet=raw_response)

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
        await q.add(tx)
        print(len(q))
        if (p := await q.match(rx)) is not None:
            await q.remove(p)
        print(len(q))
        await q.add(rx)
        await q.add(tx)
        print(len(q))
        await q.empty()
        print(len(q))

    _LOGGER = logging.getLogger()
    _LOGGER.setLevel(logging.DEBUG)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(levelname)s - %(message)s"))
    _LOGGER.addHandler(handler)

    asyncio.run(main())
