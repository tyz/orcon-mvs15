from .ramses_packet import RamsesPacket, RamsesPacketDatetime


class CodeException(Exception):
    pass


class Code:
    def __init__(self, **kwargs):
        self.packet = kwargs.get("packet")
        self.values = {}
        callback = kwargs.get("callback")
        if self.packet:
            self._validate_payload()
            self._parse_payload()
            if callback:
                callback(self.values)

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
        pass

    def _parse_payload(self):
        """Parse the payload, put result in self.values"""
        self.values = {"level": None, "_packet": str(self.packet)}

    def __repr__(self):
        """Return a human readable string of self.values"""
        return f"Unsupported code: {self.values}"

    @classmethod
    def get(cls, src_id, dst_id):
        """Build a RamsesPacket object that requests the current status"""
        raise NotImplementedError

    @classmethod
    def set(cls, src_id, dst_id, value):
        """Build a RamsesPacket object that sets a value"""
        raise NotImplementedError

    @classmethod
    def values(cls):
        """Return a list of optional values for self.set"""
        raise NotImplementedError


class Code1298(Code):
    """CO2"""

    def _validate_payload(self):
        if self.packet.length not in [1, 3]:
            raise CodeException(f"Unexpected length: {self.packet}")

    def _parse_payload(self):
        self.values = {}
        if self.packet.length == 3:
            self.values = {"level": int(self.packet.data, 16)}

    def __repr__(self):
        if "level" not in self.values:
            return "CO2 state request"
        return f"CO2: {self.values['level']} ppm"

    @classmethod
    def get(cls, src_id, dst_id):
        p = RamsesPacket(src_id=src_id, dst_id=dst_id)
        p.type = "RQ"
        p.code = "1298"
        p.data = "00"
        return p


class Code22f1(Code):
    """Fan mode"""

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

    def _validate_payload(self):
        if self.packet.length not in [1, 3]:
            raise CodeException(f"Unexpected length: {self.packet}")

    def _parse_payload(self):
        self.values = {}
        if self.packet.length == 3:
            preset = next(k for k, v in self._fan_modes.items() if v == self.packet.data)
            self.values = {"fan_mode": preset}

    def __repr__(self):
        if "fan_mode" not in self.values:
            return "Fan mode state request"
        return f"Fan mode: {self.values.get('fan_mode')}"

    @classmethod
    def get(cls, src_id, dst_id):
        cls.packet = RamsesPacket(src_id=src_id, dst_id=dst_id)
        cls.packet.type = "RQ"
        cls.packet.code = "22F1"
        cls.packet.data = "00"
        return cls.packet

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


class Code31d9(Code):
    """Fan state"""

    _presets = {
        "00": "Away",
        "01": "Low",
        "02": "Medium",
        "03": "High",
        "04": "Auto",
    }

    def _validate_payload(self):
        if self.packet.length not in [1, 3]:
            raise CodeException(f"Unexpected length: {self.packet}")

    def _parse_payload(self):
        self.values = {}
        if self.packet.length == 3:
            state = self.packet.data[4:6]
            bitmap = int(self.packet.data[2:4], 16)
            self.values = {
                "fan_mode": self._presets.get(state, "UNKNOWN"),
                "passive": bool(bitmap & 0x02),
                "damper_only": bool(bitmap & 0x04),
                "filter_dirty": bool(bitmap & 0x20),
                "frost_cycle": bool(bitmap & 0x40),
                "has_fault": bool(bitmap & 0x80),
            }

    def __repr__(self):
        if "fan_mode" not in self.values:
            return "Fan mode state request"
        return f"Fan mode: {self.values.get('fan_mode')}"

    @classmethod
    def get(cls, src_id, dst_id):
        cls.packet = RamsesPacket(src_id=src_id, dst_id=dst_id)
        cls.packet.type = "RQ"
        cls.packet.code = "31D9"
        cls.packet.data = "00"
        return cls.packet

    @classmethod
    def presets(cls):
        return list(cls._presets.values())


class Code22f3(Code22f1):
    """Fan mode with timer"""

    def _validate_payload(self):
        if self.packet.length != 7:
            raise CodeException(f"Unexpected length: {self.packet}")


class Code31e0(Code):
    """Vent demand"""

    def _validate_payload(self):
        if self.packet.length not in [1, 8]:
            raise CodeException(f"Unexpected length: {self.packet}")

    def _parse_payload(self):
        self.values = {}
        if self.packet.length == 8:
            self.values = {
                "percentage": self._percent(self.packet.data[4:6]),
                "flags": self.packet.data[2:4],
                "_unknown": self.packet.data[6:],
            }

    def __repr__(self):
        if "percentage" not in self.values:
            return "Vent demand state request"
        return f"Vent demand: {self.values['percentage']}%, "

    @classmethod
    def get(self, src_id, dst_id):
        p = RamsesPacket(src_id=src_id, dst_id=dst_id)
        p.type = "RQ"
        p.code = "31E0"
        p.data = "00"
        return p


class Code10e0(Code):
    """Device info"""

    def _validate_payload(self):
        if self.packet.length not in [1, 29, 38]:
            raise CodeException(f"Unexpected length: {self.packet}")

    def _parse_payload(self):
        if self.packet.length == 1:
            self.values = {}
            return
        description, _, _ = self.packet.data[36:].partition("00")
        self.values = {
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

    def __repr__(self):
        if "sz_oem_code" not in self.values:
            return "Device info request"
        return f"Device info: {self.values}"

    @classmethod
    def get(cls, src_id, dst_id):
        p = RamsesPacket(src_id=src_id, dst_id=dst_id)
        p.type = "RQ"
        p.code = "10E0"
        p.data = "00"
        return p


class Code10e1(Code):
    """Device ID"""

    def _validate_payload(self):
        if self.packet.length not in [1, 4]:
            raise CodeException(f"Unexpected length: {self.packet}")

    def _parse_payload(self):
        self.values = {}
        if self.packet.length == 4:
            self.values = {
                "device_id": self._dev_hex_to_id(self.packet.data),
            }

    def __repr__(self):
        if "device_id" not in self.values:
            return "Device ID request"
        return f"Device ID: {self.values['device_id']}"

    @classmethod
    def get(cls, src_id, dst_id):
        p = RamsesPacket(src_id=src_id, dst_id=dst_id)
        p.type = "RQ"
        p.code = "10E1"
        p.data = "00"
        return p


class Code12a0(Code):
    """Indoor humidity"""

    def _validate_payload(self):
        if self.packet.length not in [1, 2]:
            raise CodeException(f"Unexpected length: {self.packet}")

    def _parse_payload(self):
        self.values = {}
        if self.packet.length == 2:
            self.values = {"level": int(self.packet.data, 16)}

    def __repr__(self):
        if "level" not in self.values:
            return "Indoor humidity state request"
        return f"Indoor humidity: {self.values['level']}%"

    @classmethod
    def get(cls, src_id, dst_id):
        p = RamsesPacket(src_id=src_id, dst_id=dst_id)
        p.type = "RQ"
        p.code = "12A0"
        p.data = "00"
        return p


class Code1060(Code):
    """Battery state"""

    def _validate_payload(self):
        if self.packet.length not in [1, 6]:
            raise CodeException(f"Unexpected length: {self.packet}")

    def _parse_payload(self):
        self.values = {}
        if self.packet.length == 6:
            self.values = {
                "level": self._percent(self.packet.data[2:4]),
                "low": self.packet.data[4:6] == "00",
            }

    def __repr__(self):
        if "level" not in self.values:
            return "Battery state request"
        return f"Battery level: {self.values['level']}%, low: {self.values['low']}"

    @classmethod
    def get(cls, src_id, dst_id):
        p = RamsesPacket(src_id=src_id, dst_id=dst_id)
        p.type = "RQ"
        p.code = "1060"
        p.data = "00"
        return p


class Code1fc9(Code):
    """RF bind"""

    def _validate_payload(self):
        if self.packet.length != 6:  # Could be a multiple of 6, not sure if that's ever the case with Orcon
            raise CodeException(f"Unexpected length: {self.packet}")

    def _parse_payload(self):
        self.values = {
            "zone_idx": int(self.packet.data[:2], 16),
            "command": self.packet.data[2:6],
            "device_id": self._dev_hex_to_id(self.packet.data[6:]),
        }


class Code042f(Code):
    """Unknown, broadcasted on startup"""

    """23-5-2025: 042F 006 000042004200"""

    def _validate_payload(self):
        if self.packet.length != 6:
            raise CodeException(f"Unexpected length: {self.packet}")

    def _parse_payload(self):
        self.values = {
            "counter_1": f"0x{self.packer.data[2:6]}",
            "counter_3": f"0x{self.packer.data[6:10]}",
            "counter_5": f"0x{self.packer.data[10:14]}",
            "unknown_7": f"0x{self.packer.data[14:]}",
        }
