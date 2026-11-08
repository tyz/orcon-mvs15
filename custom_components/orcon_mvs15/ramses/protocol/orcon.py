"""Codecs for the RAMSES II codes this integration understands."""

from __future__ import annotations

import logging

from .codes import CODE_REGISTRY, Code, register_code
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
            if self.packet.data:
                self.values.update({"level": int(self.packet.data, 16)})
            else:
                self.values.update({"level": None})


@register_code("22F1")
class Code22f1(Code):
    """Fan mode, will act as 22F3 if needed"""

    _code = "22F1"

    # Preset identifiers are translation keys: lowercase slugs without spaces.
    _fan_modes = {
        "auto": "000404",
        "low": "000104",
        "medium": "000204",
        "high": "000304",
        "high_15m": "00020F03040000",
        "high_30m": "00021E03040000",
        "high_60m": "00023C03040000",
        "away": "000004",
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
            for k, v in self._fan_modes.items():
                if v == self.packet.data:
                    self.values.update(
                        {
                            "fan_mode": k,
                            "timer_minutes": self._timed_modes.get(k),
                        }
                    )
                    return
            _LOGGER.debug(f"Unknown preset for 22F1/22F3: {self.packet.data}")

    @classmethod
    def set(cls, src_id: RamsesID, dst_id: RamsesID, value: str) -> RamsesPacket:
        p = RamsesPacket(
            src_id=src_id,
            dst_id=dst_id,
            type="I",
            data=cls._fan_modes[value],
        )
        p.expected_response = RamsesPacketResponse(
            src_id=dst_id,
            dst_id=RamsesID(),
            type="I",
            code="31D9",
        )
        p.code = "22F1" if p.length == 3 else "22F3"
        _LOGGER.debug(f"Code22f1.set({value}) == {cls._fan_modes[value]} -> {p}")
        return p

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
    def get(cls, src_id: RamsesID, dst_id: RamsesID) -> RamsesPacket:
        raise NotImplementedError


@register_code("31D9")
class Code31d9(Code):
    """Fan state"""

    _code = "31D9"

    _presets = {
        "00": "away",
        "01": "low",
        "02": "medium",
        "03": "high",
        "04": "auto",
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
        assert self.packet.data is not None
        if self.packet.length == 3:
            state = self.packet.data[4:6]
            bitmap = int(self.packet.data[2:4], 16)
            self.values.update(
                {
                    "fan_mode": self._presets.get(state, state),
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
        assert self.packet.data is not None
        if self.packet.length == 8:
            self.values.update(
                {
                    "percentage": self._percent(self.packet.data[4:6]),
                    "unknown": self.packet.data[12:14],  # 64, 1E or AA
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
        assert self.packet.data is not None
        description, _, _ = self.packet.data[36:].partition("00")
        self.values.update(
            {
                "sz_oem_code": self.packet.data[
                    14:16
                ],  # 00/FF is CH/DHW, 01/6x is HVAC
                "manufacturer_group": self.packet.data[2:6],  # 0001-HVAC, 0002-CH/DHW
                "manufacturer_sub_id": self.packet.data[6:8],
                "product_id": self.packet.data[
                    8:10
                ],  # if CH/DHW: matches device_type (sometimes)
                "software_ver_id": self.packet.data[10:12],
                "list_ver_id": self.packet.data[
                    12:14
                ],  # if FF/01 is CH/DHW, then 01/FF
                "unknown": self.packet.data[14:16],
                "additional_ver_a": self.packet.data[16:18],
                "additional_ver_b": self.packet.data[18:20],
                "date_2": RamsesPacketDatetime(self.packet.data[20:28]),
                "date_1": RamsesPacketDatetime(self.packet.data[28:36]),
                "description": bytearray.fromhex(description).decode(),
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
        assert self.packet.data is not None
        if self.packet.length == 4:
            self.values.update({"device_id": self._dev_hex_to_id(self.packet.data)})


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
        assert self.packet.data is not None
        if self.packet.length == 2:
            self.values.update({"level": int(self.packet.data, 16)})


@register_code("1060")
class Code1060(Code):
    """Battery state
    Not used by the 15RF wireless remote, but I occasionally receive it
    from one of my neighbours with another Orcon system"""

    _code = "1060"

    def _expected_length(self, length: int) -> bool:
        return length in [1, 6]

    def _parse_packet(self) -> None:
        assert self.packet.data is not None
        self.values = {
            "_label": "Battery status",
            "signal_strength": -self.packet.signal_strength,
            "level": None,
            "low": None,
        }
        if self.packet.length == 6:
            self.values.update(
                {
                    "level": self._percent(self.packet.data[2:4]),
                    "low": self.packet.data[4:6] == "00",
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
        return length % 6 == 0

    def _parse_packet(self) -> None:
        assert self.packet.data is not None
        self.values = {
            "_label": "RF Bind",
            "signal_strength": -self.packet.signal_strength,
            "zone_idx": int(self.packet.data[:2], 16),
            "command": self.packet.data[2:6],
            "device_id": self._dev_hex_to_id(self.packet.data[6:]),
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
        assert self.packet.data is not None
        self.values = {
            "_label": "Unknown (042F)",
            "signal_strength": -self.packet.signal_strength,
            "power_cycles": f"0x{self.packet.data[2:6]}",
            "power_cycles_2": f"0x{self.packet.data[6:10]}",
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
