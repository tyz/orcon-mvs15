from __future__ import annotations


try:
    from .ramses_packet import RamsesPacket, RamsesPacketResponse, RamsesPacketDatetime
except ImportError:
    """for __main__"""
    from ramses_packet import RamsesPacket, RamsesPacketResponse, RamsesPacketDatetime

__all__ = [
    "Code",
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


class CodeException(Exception):
    pass


class Code:
    _code = "FFFF"

    def __init__(self, packet: RamsesPacket) -> None:
        self.packet = packet
        self.values = {}
        if self.packet:
            self._validate_packet()
            self._parse_packet()

    def _expected_length(self, length: int) -> bool:
        return True

    def _percent(self, value: str | int) -> int:
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

    def _validate_packet(self) -> bool:
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
    def get(cls, src_id: str, dst_id: str) -> RamsesPacket:
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
    def set(cls, src_id: str, dst_id: str, value: str) -> None:
        """Build a RamsesPacket object that sets a value"""
        raise NotImplementedError

    @classmethod
    def presets(cls) -> list:
        """Return a list of optional values for self.set"""
        raise NotImplementedError


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
            self.values.update({"level": int(self.packet.data, 16)})


class Code22f1(Code):
    """Fan mode, will act as 22F3 if needed"""

    _code = "22F1"

    _fan_modes = {
        "Auto": "000404",
        "Low": "000104",
        "Medium": "000204",
        "High": "000304",
        "High (15m)": "00020F03040000",
        "High (30m)": "00021E03040000",
        "High (60m)": "00023C03040000",
        "Away": "000004",
    }

    def _expected_length(self, length: int) -> bool:
        return length in [1, 3]

    def _parse_packet(self) -> None:
        self.values = {
            "_label": "Fan mode",
            "signal_strength": -self.packet.signal_strength,
            "fan_mode": None,
        }
        if self.packet.length != 1:
            try:
                preset = next(
                    k for k, v in self._fan_modes.items() if v == self.packet.data
                )
            except StopIteration:
                preset = self.packet.data
            self.values.update({"fan_mode": preset})

    @classmethod
    def set(cls, src_id: str, dst_id: str, value: str) -> None:
        if value not in cls._fan_modes:
            raise CodeException(f"Invalid preset '{value}'")
        p = RamsesPacket(
            src_id=src_id,
            dst_id=dst_id,
            type="I",
            data=cls._fan_modes[value],
        )
        p.expected_respons = RamsesPacketResponse(
            src_id=dst_id,
            dst_id="--:------",
            type="I",
            code="31D9",
        )
        p.code = "22F1" if p.length == 3 else "22F3"
        return p

    @classmethod
    def presets(cls) -> list:
        return list(cls._fan_modes.keys())


class Code22f3(Code22f1):
    """Fan mode with timer"""

    _code = "22F3"

    def _expected_length(self, length: int) -> bool:
        return length == 7

    @classmethod
    def get(cls, src_id: str, dst_id: str) -> RamsesPacket:
        raise NotImplementedError


class Code31d9(Code):
    """Fan state"""

    _code = "31D9"

    _presets = {
        "00": "Away",
        "01": "Low",
        "02": "Medium",
        "03": "High",
        "04": "Auto",
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
            state = self.packet.data[4:6]
            bitmap = int(self.packet.data[2:4], 16)
            self.values.update(
                {
                    "fan_mode": self._presets.get(state, state),
                    "has_fault": bool(bitmap & 0x80),
                }
            )

    @classmethod
    def presets(cls) -> list:
        return list(cls._presets.values())


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
            self.values.update(
                {
                    "percentage": self._percent(self.packet.data[4:6]),
                    "unknown": self.packet.data[12:14],  # 64, 1E or AA
                }
            )


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
            self.values.update({"device_id": self._dev_hex_to_id(self.packet.data)})


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
            self.values.update({"level": int(self.packet.data, 16)})


class Code1060(Code):
    """Battery state
    Not used by the RF15 remote, but I occasionally receive it
    from one of my neighbours with another Orcon system"""

    _code = "1060"

    def _expected_length(self, length: int) -> bool:
        return length in [1, 6]

    def _parse_packet(self) -> None:
        self.values = {
            "_label": "Battery status",
            "signal_strength": -self.packet.signal_strength,
            "level": self._percent(self.packet.data[2:4]),
            "low": self.packet.data[4:6] == "00",
        }

    @classmethod
    def get(cls, src_id: str, dst_id: str) -> RamsesPacket:
        raise NotImplementedError


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
        self.values = {
            "_label": "RF Bind",
            "signal_strength": -self.packet.signal_strength,
            "zone_idx": int(self.packet.data[:2], 16),
            "command": self.packet.data[2:6],
            "device_id": self._dev_hex_to_id(self.packet.data[6:]),
        }

    @classmethod
    def get(cls, src_id: str, dst_id: str) -> RamsesPacket:
        raise NotImplementedError


class Code042f(Code):
    """Unknown, broadcasted on startup
    23-5-2025: 042F 006 000042004200"""

    _code = "042F"

    def _expected_length(self, length: int) -> bool:
        return length == 6

    def _parse_packet(self) -> None:
        self.values = {
            "_label": "Unknown (042F)",
            "signal_strength": -self.packet.signal_strength,
            "counter_1": f"0x{self.packer.data[2:6]}",
            "counter_3": f"0x{self.packer.data[6:10]}",
            "counter_5": f"0x{self.packer.data[10:14]}",
            "unknown_7": f"0x{self.packer.data[14:]}",
        }

    @classmethod
    def get(cls, src_id: str, dst_id: str) -> RamsesPacket:
        raise NotImplementedError


if __name__ == "__main__":
    """Parse Ramses logfile, from stdin or 1st cli arg"""

    import sys

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
                packet = RamsesPacket(raw_packet={"ts": ts, "msg": msg})
            except AssertionError as e:
                print(f"!!! {e}: {ts} {msg}")
                continue
            except Exception as e:
                print(f"!!! {e}: {line}")

            try:
                if (code_class := globals().get(f"Code{packet.code.lower()}")) is None:
                    print(
                        f"WARNING: Class Code{packet.code.lower()} not imported, or does not exist"
                    )
                    code_class = Code
                print(
                    f"{ts} {packet.signal_strength:03d} {packet.type:>2} {packet.src_id} {packet.dst_id} "
                    f"{packet.ann_id} {packet.code} {packet.length:03d} {code_class(packet=packet)}"
                )
            except Exception as e:
                print(f"!!! {e}: {line}")
