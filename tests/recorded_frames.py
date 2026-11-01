"""Helpers for replaying the gateway frames in ``tests/fixtures``."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from custom_components.orcon_mvs15.codes import CODE_REGISTRY, Code
from custom_components.orcon_mvs15.ramses_packet import RamsesPacket

FIXTURES = Path(__file__).parent / "fixtures"
FIRST_TIMESTAMP = datetime(2026, 9, 11, 11, 47, 55, tzinfo=UTC)


def frames(name: str) -> list[str]:
    """Return the frames recorded in a fixture file."""
    return (FIXTURES / name).read_text().splitlines()


def envelope(frame: str, offset: int = 0) -> dict[str, str]:
    """Wrap a recorded frame in the gateway receive envelope."""
    timestamp = FIRST_TIMESTAMP + timedelta(seconds=offset)
    return {"ts": timestamp.isoformat(), "msg": frame}


def envelopes(name: str) -> list[dict[str, str]]:
    """Wrap every frame in a fixture file in an envelope, one second apart."""
    return [envelope(frame, offset) for offset, frame in enumerate(frames(name))]


def packets(name: str) -> list[RamsesPacket]:
    """Parse every frame in a fixture file."""
    return [RamsesPacket(envelope=item) for item in envelopes(name)]


def decode(packet: RamsesPacket) -> Code:
    """Decode a packet the way the session does."""
    return CODE_REGISTRY[packet.code](packet=packet)


def frame_with_data(name: str, data: str) -> str:
    """Return the first recorded frame whose payload is ``data``."""
    for frame in frames(name):
        if frame.split()[-1] == data:
            return frame
    raise LookupError(f"No frame with data {data} in {name}")


def packet_with_data(name: str, data: str) -> RamsesPacket:
    """Parse the first recorded frame whose payload is ``data``."""
    return RamsesPacket(envelope=envelope(frame_with_data(name, data)))


def packet_from(name: str, src_id: str, code: str) -> RamsesPacket:
    """Parse the first recorded frame with a source device and a code."""
    for packet in packets(name):
        if packet.src_id == src_id and packet.code == code:
            return packet
    raise LookupError(f"No {code} frame from {src_id} in {name}")
