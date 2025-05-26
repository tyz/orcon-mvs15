try:
    from .ramses_packet import RamsesPacket, RamsesPacketDatetime
except ImportError:
    """for __main__"""
    from ramses_packet import RamsesPacket, RamsesPacketDatetime


class CodeException(Exception):
    pass


class Code:
    _expected_length = []
    _code = "FFFF"

    def __init__(self, **kwargs):
        self.packet = kwargs.get("packet")
        self.values = {}
        if self.packet:
            self._validate_payload()
            self._parse_payload()

    def _percent(self, value):
        if int(value, 16) > 200:  # FE or FF
            return None
        return int(value, 16) // 2

    def _dev_hex_to_id(self, device_hex: str) -> str:
        """Convert (say) '06368E' to '01:145038' (or 'CTL:145038')."""
        if device_hex == "FFFFFF":  # aka '63:262143'
            return f"{'':9}"
        if not device_hex.strip():  # aka '--:------'
            return "--:------"
        _tmp = int(device_hex, 16)
        dev_type = (_tmp & 0xFC0000) >> 18
        return f"{dev_type:02d}:{_tmp & 0x03FFFF:06d}"

    def _validate_payload(self):
        """Validate the payload, raise CodeException if it fails"""
        if self._expected_length and self.packet.length not in self._expected_length:
            raise CodeException(f"Unexpected length: {self.packet}")

    def _parse_payload(self):
        """Parse the payload, put result in self.values"""
        self.values = {"_label": "Unsupported code", "packet": str(self.packet)}

    def __repr__(self):
        """Return a human readable string of self.values"""
        if self.packet.length == 1:
            return f"{self.values['_label']} state request"
        keyval = ", ".join([f"{k}: {v}" for k, v in self.values.items() if not k.startswith("_")])
        return f"{self.values['_label']}: {keyval}"

    @classmethod
    def get(cls, src_id, dst_id):
        """Build a RamsesPacket object that requests the current status"""
        p = RamsesPacket(src_id=src_id, dst_id=dst_id)
        p.type = "RQ"
        p.code = cls._code
        p.data = "00"
        return p

    @classmethod
    def set(cls, src_id, dst_id, value):
        """Build a RamsesPacket object that sets a value"""
        raise NotImplementedError

    @classmethod
    def presets(cls):
        """Return a list of optional values for self.set"""
        raise NotImplementedError


class Code1298(Code):
    """CO2"""

    _expected_length = [1, 3]
    _code = "1298"

    def _parse_payload(self):
        self.values = {"_label": "CO2 level"}
        if self.packet.length == 3:
            self.values.update({"level": int(self.packet.data, 16)})


class Code22f1(Code):
    """Fan mode"""

    _expected_length = [1, 3]
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

    def _parse_payload(self):
        self.values = {"_label": "Fan mode"}
        if self.packet.length != 1:
            try:
                preset = next(k for k, v in self._fan_modes.items() if v == self.packet.data)
            except StopIteration:
                preset = self.packet.data
            self.values.update({"fan_mode": preset})

    @classmethod
    def set(cls, src_id, dst_id, preset):
        if preset not in cls._fan_modes:
            raise CodeException(f"Invalid preset '{preset}'")
        cls.packet = RamsesPacket(src_id=src_id, dst_id=dst_id)
        cls.packet.type = "I"
        cls.packet.data = cls._fan_modes[preset]
        cls.packet.code = "22F1" if cls.packet.length == 3 else "22F3"
        return cls.packet

    @classmethod
    def presets(cls):
        return list(cls._fan_modes.keys())


class Code22f3(Code22f1):
    """Fan mode with timer"""

    _expected_length = [7]
    _code = "22F3"

    @classmethod
    def get(cls):
        raise NotImplementedError


class Code31d9(Code):
    """Fan state"""

    _expected_length = [1, 3]
    _code = "31D9"

    _presets = {
        "00": "Away",
        "01": "Low",
        "02": "Medium",
        "03": "High",
        "04": "Auto",
    }

    def _parse_payload(self):
        self.values = {"_label": "Fan state"}
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
    def presets(cls):
        return list(cls._presets.values())


class Code31e0(Code):
    """Vent demand"""

    _expected_length = [1, 8]
    _code = "31E0"

    def _parse_payload(self):
        self.values = {"_label": "Vent demand"}
        if self.packet.length == 8:
            self.values.update(
                {
                    "percentage": self._percent(self.packet.data[4:6]),
                    "unknown": self.packet.data[12:14],  # 64, 1E or AA
                }
            )


class Code10e0(Code):
    """Device info"""

    _expected_length = [1, 29, 38]
    _code = "10E0"

    def _parse_payload(self):
        self.values = {"_label": "Device info"}
        if self.packet.length == 1:
            return
        description, _, _ = self.packet.data[36:].partition("00")
        self.values.update(
            {
                "sz_oem_code": self.packet.data[14:16],  # 00/FF is CH/DHW, 01/6x is HVAC
                "manufacturer_group": self.packet.data[2:6],  # 0001-HVAC, 0002-CH/DHW
                "manufacturer_sub_id": self.packet.data[6:8],
                "product_id": self.packet.data[8:10],  # if CH/DHW: matches device_type (sometimes)
                "date_1": RamsesPacketDatetime(self.packet.data[28:36]),
                "date_2": RamsesPacketDatetime(self.packet.data[20:28]),
                "software_ver_id": self.packet.data[10:12],
                "list_ver_id": self.packet.data[12:14],  # if FF/01 is CH/DHW, then 01/FF
                "additional_ver_a": self.packet.data[16:18],
                "additional_ver_b": self.packet.data[18:20],
                "signature": self.packet.data[2:20],
                "description": bytearray.fromhex(description).decode(),
            }
        )


class Code10e1(Code):
    """Device ID"""

    _expected_length = [1, 4]
    _code = "10E1"

    def _parse_payload(self):
        self.values = {"_label": "Device ID"}
        if self.packet.length == 4:
            self.values.update({"device_id": self._dev_hex_to_id(self.packet.data)})


class Code12a0(Code):
    """Indoor humidity"""

    _expected_length = [1, 2]
    _code = "12A0"

    def _parse_payload(self):
        self.values = {"_label": "Indoor humidity"}
        if self.packet.length == 2:
            self.values.update({"level": int(self.packet.data, 16)})


class Code1060(Code):
    """Battery state"""

    _expected_length = [6]
    _code = "1060"

    def _parse_payload(self):
        self.values = {
            "_label": "Battery status",
            "level": self._percent(self.packet.data[2:4]),
            "low": self.packet.data[4:6] == "00",
        }

    @classmethod
    def get(cls):
        raise NotImplementedError


class Code1fc9(Code):
    """RF bind"""

    """ Could be a multiple of 6, not sure if that's ever the case with Orcon"""
    _expected_length = [6]
    _code = "1FC9"

    def _parse_payload(self):
        self.values = {
            "_label": "RF Bind",
            "zone_idx": int(self.packet.data[:2], 16),
            "command": self.packet.data[2:6],
            "device_id": self._dev_hex_to_id(self.packet.data[6:]),
        }

    @classmethod
    def get(cls):
        raise NotImplementedError


class Code042f(Code):
    """Unknown, broadcasted on startup
    23-5-2025: 042F 006 000042004200"""

    _expected_length = [6]
    _code = "042F"

    def _parse_payload(self):
        self.values = {
            "_label": "Unknown (042F)",
            "counter_1": f"0x{self.packer.data[2:6]}",
            "counter_3": f"0x{self.packer.data[6:10]}",
            "counter_5": f"0x{self.packer.data[10:14]}",
            "unknown_7": f"0x{self.packer.data[14:]}",
        }

    @classmethod
    def get(cls):
        raise NotImplementedError


if __name__ == "__main__":
    import sys

    path = sys.argv[1] if len(sys.argv) == 2 else "../../../config/packet.log"
    last_msg = ""
    with open(path) as f:
        while True:
            if (line := f.readline()) == "":
                break
            if line[26] == " ":  # ramses_rf packet.log
                ts = line[:26]
                msg = line[27:].strip()
            else:
                ts = line[:32]
                msg = line[33:].strip()
            if msg[4:] == last_msg:
                continue
            last_msg = msg[4:]
            try:
                packet = RamsesPacket(raw_packet={"ts": ts, "msg": msg})
            except Exception:
                print(f"{ts} {msg}")
                continue
            if (code_class := globals().get(f"Code{packet.code.lower()}")) is None:
                print(f"WARNING: Class Code{packet.code.lower()} not imported, or does not exist")
                code_class = Code
            print(
                f"{ts} {packet.signal_strength:03d} {packet.type:>2} {packet.src_id} {packet.dst_id} "
                f"{packet.ann_id} {packet.code} {packet.length:03d} {code_class(packet=packet)}"
            )
