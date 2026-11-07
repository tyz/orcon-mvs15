"""RAMSES II codec base class and open codec registry.

Codecs are registered by code when their module is imported, so a new device
code is a new module that calls :func:`register_code`, not an edit to a closed
list.
"""

from __future__ import annotations

import logging

from collections.abc import Callable

from .frame import (
    RamsesID,
    RamsesPacket,
    RamsesPacketDatetime,
    RamsesPacketResponse,
)

_LOGGER = logging.getLogger(__name__)

__all__ = [
    "CODE_REGISTRY",
    "Code",
    "CodeException",
    "register_code",
]


class CodeException(Exception):
    """Raised when a packet cannot be decoded by its codec."""


class Code:
    _code = "FFFF"

    def __init__(self, packet: RamsesPacket) -> None:
        self.packet = packet
        self.values: dict[str, str | int | bool | RamsesPacketDatetime | None] = {}
        if self.packet:
            self._validate_packet()
            self._parse_packet()

    def _expected_length(self, length: int) -> bool:
        return True

    def _percent(self, value: str) -> int | None:
        if int(value, 16) > 200:  # FE or FF
            return None
        return int(value, 16) // 2

    def _dev_hex_to_id(self, device_hex: str) -> str:
        """Convert (say) '06368E' to '01:145038'"""
        if device_hex == "FFFFFF":  # aka '63:262143'
            return f"{'':9}"
        if not device_hex.strip():  # aka '--:------'
            return "--:------"
        _tmp = int(device_hex, 16)
        dev_type = (_tmp & 0xFC0000) >> 18
        return f"{dev_type:02d}:{_tmp & 0x03FFFF:06d}"

    def _validate_packet(self) -> None:
        """Validate the RamsesPacket, raise CodeException if it fails"""
        if not self._expected_length(self.packet.length):
            raise CodeException(f"Unexpected length: {self.packet}")

    def _parse_packet(self) -> None:
        """Parse the RamsesPacket, put result in self.values"""
        self.values = {"_label": "Unsupported code", "packet": str(self.packet)}

    def __repr__(self) -> str:
        """Return a human readable string of self.values"""
        if self.packet.length == 1:
            return f"{self.values['_label']} state request"
        keyval = ", ".join(
            [f"{k}: {v}" for k, v in self.values.items() if not k.startswith("_")]
        )
        return f"{self.values['_label']}: {keyval}"

    @classmethod
    def get(cls, src_id: RamsesID, dst_id: RamsesID) -> RamsesPacket:
        """Build a RamsesPacket object that requests the current status"""
        p = RamsesPacket(
            src_id=src_id,
            dst_id=dst_id,
            type="RQ",
            code=cls._code,
            data="00",
        )
        p.expected_response = RamsesPacketResponse(
            src_id=dst_id,
            dst_id=src_id,
            type="RP",
            code=cls._code,
        )
        return p

    @classmethod
    def set(cls, src_id: RamsesID, dst_id: RamsesID, value: str) -> RamsesPacket:
        """Build a RamsesPacket object that sets a value"""
        raise NotImplementedError

    @classmethod
    def presets(cls) -> list[str]:
        """Return a list of optional values for self.set"""
        raise NotImplementedError


CODE_REGISTRY: dict[str, type[Code]] = {}


def register_code(code: str) -> Callable[[type[Code]], type[Code]]:
    """Register a codec class for a RAMSES code."""

    def _register(cls: type[Code]) -> type[Code]:
        CODE_REGISTRY[code.upper()] = cls
        return cls

    return _register
