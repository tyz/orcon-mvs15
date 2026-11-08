"""Codecs for the RAMSES II codes this integration understands."""

from __future__ import annotations

import logging

from .codes import CODE_REGISTRY, Code, CodeException, register_code
from .frame import (
    RamsesID,
    RamsesPacket,
    RamsesPacketDatetime,
    RamsesPacketResponse,
)

__all__ = [
    "Code042f",
    "Code1060",
    "Code10e0",
    "Code10e1",
    "Code1298",
    "Code12a0",
    "Code1fc9",
    "Code22f1",
    "Code22f3",
    "Code31d9",
    "Code31e0",
]

_LOGGER = logging.getLogger(__name__)

# The meaning of FFFFFF is unverified; ramses_rf renders it as nine spaces.
_UNVERIFIED_DEVICE_ID = " " * 9


def _percent(value: int) -> int | None:
    """Decode a half-percent byte; FE and FF mean no value."""
    if value > 200:  # FE or FF
        return None
    return value // 2


def _dev_hex_to_id(device_hex: str) -> str:
    """Convert (say) '06368E' to '01:145038'."""
    if device_hex == "FFFFFF":
        return _UNVERIFIED_DEVICE_ID
    if not device_hex.strip():  # aka '--:------'
        return "--:------"
    _tmp = int(device_hex, 16)
    dev_type = (_tmp & 0xFC0000) >> 18
    return f"{dev_type:02d}:{_tmp & 0x03FFFF:06d}"


@register_code("1298")
class Code1298(Code):
    """CO2"""

    _code = "1298"

    def _expected_length(self, length: int) -> bool:
        return length in [1, 3]

    def _parse_packet(self) -> None:
        self.values = {
            "_label": "CO2 level",
            "signal_strength": -self.packet.signal_strength,
            "level": None,
        }
        if self.packet.length == 3:
            payload = self.packet.payload
            self.values.update(
                {"level": int.from_bytes(payload, "big") if payload else None}
            )


@register_code("22F1")
class Code22f1(Code):
    """Fan mode, will act as 22F3 if needed"""

    _code = "22F1"

    # Preset identifiers are translation keys: lowercase slugs without spaces.
    _fan_modes = {
        "auto": b"\x00\x04\x04",
        "low": b"\x00\x01\x04",
        "medium": b"\x00\x02\x04",
        "high": b"\x00\x03\x04",
        "high_15m": b"\x00\x02\x0f\x03\x04\x00\x00",
        "high_30m": b"\x00\x02\x1e\x03\x04\x00\x00",
        "high_60m": b"\x00\x02\x3c\x03\x04\x00\x00",
        "away": b"\x00\x00\x04",
    }

    _timed_modes = {"high_15m": 15, "high_30m": 30, "high_60m": 60}

    def _expected_length(self, length: int) -> bool:
        return length in [1, 3]

    def _parse_packet(self) -> None:
        self.values = {
            "_label": "Fan mode",
            "signal_strength": -self.packet.signal_strength,
            "fan_mode": None,
            "timer_minutes": None,
        }
        if self.packet.length != 1:
            payload = self.packet.payload
            for k, v in self._fan_modes.items():
                if v == payload:
                    self.values.update(
                        {
                            "fan_mode": k,
                            "timer_minutes": self._timed_modes.get(k),
                        }
                    )
                    return
            _LOGGER.debug(f"Unknown preset for 22F1/22F3: {payload.hex().upper()}")

    @classmethod
    def _command(
        cls, src_id: RamsesID, dst_id: RamsesID, value: str, code: str
    ) -> RamsesPacket:
        data = cls._fan_modes[value].hex().upper()
        packet = RamsesPacket(
            src_id=src_id,
            dst_id=dst_id,
            type="I",
            code=code,
            data=data,
        )
        packet.expected_response = RamsesPacketResponse(
            src_id=dst_id,
            dst_id=RamsesID(),
            type="I",
            code="31D9",
        )
        _LOGGER.debug(f"{code}.set({value}) == {data} -> {packet}")
        return packet

    @classmethod
    def set(cls, src_id: RamsesID, dst_id: RamsesID, value: str) -> RamsesPacket:
        if value in cls._timed_modes:
            return Code22f3.set(src_id, dst_id, value)
        return cls._command(src_id, dst_id, value, cls._code)

    @classmethod
    def presets(cls) -> list[str]:
        return list(cls._fan_modes.keys())


@register_code("22F3")
class Code22f3(Code22f1):
    """Fan mode with timer"""

    _code = "22F3"

    def _expected_length(self, length: int) -> bool:
        return length == 7

    @classmethod
    def set(cls, src_id: RamsesID, dst_id: RamsesID, value: str) -> RamsesPacket:
        if value not in cls._timed_modes:
            raise CodeException(f"{value} is not a timed fan mode")
        return cls._command(src_id, dst_id, value, cls._code)

    @classmethod
    def get(cls, src_id: RamsesID, dst_id: RamsesID) -> RamsesPacket:
        raise NotImplementedError


@register_code("31D9")
class Code31d9(Code):
    """Fan state"""

    _code = "31D9"

    _presets = {
        0x00: "away",
        0x01: "low",
        0x02: "medium",
        0x03: "high",
        0x04: "auto",
    }

    def _expected_length(self, length: int) -> bool:
        return length in [1, 3]

    def _parse_packet(self) -> None:
        self.values = {
            "_label": "Fan state",
            "signal_strength": -self.packet.signal_strength,
            "fan_mode": None,
            "has_fault": None,
        }
        if self.packet.length == 3:
            payload = self.packet.payload
            state = payload[2]
            bitmap = payload[1]
            self.values.update(
                {
                    "fan_mode": self._presets.get(state, f"{state:02X}"),
                    "has_fault": bool(bitmap & 0x80),
                }
            )

    @classmethod
    def presets(cls) -> list[str]:
        return list(cls._presets.values())


@register_code("31E0")
class Code31e0(Code):
    """Vent demand"""

    _code = "31E0"

    def _expected_length(self, length: int) -> bool:
        return length in [1, 8]

    def _parse_packet(self) -> None:
        self.values = {
            "_label": "Vent demand",
            "signal_strength": -self.packet.signal_strength,
            "percentage": None,
            "unknown": None,
        }
        if self.packet.length == 8:
            payload = self.packet.payload
            self.values.update(
                {
                    "percentage": _percent(payload[2]),
                    "unknown": f"{payload[6]:02X}",  # 64, 1E or AA
                }
            )


@register_code("10E0")
class Code10e0(Code):
    """Device info"""

    _code = "10E0"

    def _expected_length(self, length: int) -> bool:
        return length == 1 or length >= 29

    def _parse_packet(self) -> None:
        self.values = {
            "_label": "Device info",
            "signal_strength": -self.packet.signal_strength,
        }
        if self.packet.length == 1:
            return
        payload = self.packet.payload
        description = payload[18:].split(b"\x00", 1)[0]
        self.values.update(
            {
                "sz_oem_code": payload[7:8].hex().upper(),  # 00/FF CH/DHW, 01/6x HVAC
                "manufacturer_group": payload[1:3].hex().upper(),  # 0001 HVAC
                "manufacturer_sub_id": payload[3:4].hex().upper(),
                "product_id": payload[4:5].hex().upper(),  # CH/DHW: device type
                "software_ver_id": payload[5:6].hex().upper(),
                "list_ver_id": payload[6:7].hex().upper(),  # FF/01: CH/DHW
                "unknown": payload[7:8].hex().upper(),
                "additional_ver_a": payload[8:9].hex().upper(),
                "additional_ver_b": payload[9:10].hex().upper(),
                "date_2": RamsesPacketDatetime(payload[10:14].hex().upper()),
                "date_1": RamsesPacketDatetime(payload[14:18].hex().upper()),
                "description": description.decode(errors="replace"),
            }
        )


@register_code("10E1")
class Code10e1(Code):
    """Device ID"""

    _code = "10E1"

    def _expected_length(self, length: int) -> bool:
        return length in [1, 4]

    def _parse_packet(self) -> None:
        self.values = {
            "_label": "Device ID",
            "signal_strength": -self.packet.signal_strength,
            "device_id": None,
        }
        if self.packet.length == 4:
            self.values.update(
                {"device_id": _dev_hex_to_id(self.packet.payload.hex().upper())}
            )


@register_code("12A0")
class Code12a0(Code):
    """Indoor humidity"""

    _code = "12A0"

    def _expected_length(self, length: int) -> bool:
        return length in [1, 2]

    def _parse_packet(self) -> None:
        self.values = {
            "_label": "Indoor humidity",
            "signal_strength": -self.packet.signal_strength,
            "level": None,
        }
        if self.packet.length == 2:
            self.values.update({"level": int.from_bytes(self.packet.payload, "big")})


@register_code("1060")
class Code1060(Code):
    """Battery state
    Not used by the 15RF wireless remote, but I occasionally receive it
    from one of my neighbours with another Orcon system"""

    _code = "1060"

    def _expected_length(self, length: int) -> bool:
        return length in [1, 6]

    def _parse_packet(self) -> None:
        self.values = {
            "_label": "Battery status",
            "signal_strength": -self.packet.signal_strength,
            "level": None,
            "low": None,
        }
        if self.packet.length == 6:
            payload = self.packet.payload
            self.values.update(
                {
                    "level": _percent(payload[1]),
                    "low": payload[2] == 0,
                }
            )

    @classmethod
    def get(cls, src_id: RamsesID, dst_id: RamsesID) -> RamsesPacket:
        raise NotImplementedError


@register_code("1FC9")
class Code1fc9(Code):
    """RF bind"""

    """
       Work in progress
       FIXME: Length could be a multiple of 6, not sure if that's ever the case with Orcon
    """
    _code = "1FC9"

    def _expected_length(self, length: int) -> bool:
        return length > 0 and length % 6 == 0

    def _parse_packet(self) -> None:
        payload = self.packet.payload
        self.values = {
            "_label": "RF Bind",
            "signal_strength": -self.packet.signal_strength,
            "zone_idx": payload[0],
            "command": payload[1:3].hex().upper(),
            "device_id": _dev_hex_to_id(payload[3:].hex().upper()),
        }

    @classmethod
    def get(cls, src_id: RamsesID, dst_id: RamsesID) -> RamsesPacket:
        raise NotImplementedError


@register_code("042F")
class Code042f(Code):
    """Counter that seem to increase on every power cycle. Broadcasted on startup"""

    _code = "042F"

    def _expected_length(self, length: int) -> bool:
        return length == 6

    def _parse_packet(self) -> None:
        payload = self.packet.payload
        self.values = {
            "_label": "Unknown (042F)",
            "signal_strength": -self.packet.signal_strength,
            "power_cycles": f"0x{payload[1:3].hex().upper()}",
            "power_cycles_2": f"0x{payload[3:5].hex().upper()}",
        }

    @classmethod
    def get(cls, src_id: RamsesID, dst_id: RamsesID) -> RamsesPacket:
        raise NotImplementedError


if __name__ == "__main__":
    import sys

    """Parse Ramses logfile, from stdin or 1st cli arg"""

    path = sys.argv[1] if len(sys.argv) == 2 else "/dev/stdin"
    last_msg = ""

    with open(path) as f:
        while True:
            if (line := f.readline()) == "":
                break

            try:
                if line[26] == " ":  # ramses_rf packet.log
                    ts = line[:26]
                    msg = line[27:].strip()
                else:
                    ts = line[:32]
                    msg = line[33:].strip()
            except IndexError:
                print(line, end="")
                continue

            if msg[4:] == last_msg:
                continue
            last_msg = msg[4:]

            try:
                packet = RamsesPacket(envelope={"ts": ts, "msg": msg})
            except Exception as e:
                print(f"!!! {e}: {ts} {msg}")
                continue

            try:
                if (code_class := CODE_REGISTRY.get(packet.code.upper())) is None:
                    print(
                        f"WARNING: There is no class for code {packet.code}, using the generic Code"
                    )
                    code_class = Code
                print(
                    f"{ts} {packet.signal_strength:03d} {packet.type:>2} {packet.src_id} {packet.dst_id} "
                    f"{packet.ann_id} {packet.code} {packet.length:03d} {code_class(packet=packet)}"
                )
            except Exception as e:
                print(f"!!! {e}: {line}")
