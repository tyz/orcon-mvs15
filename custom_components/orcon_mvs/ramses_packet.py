import logging
import json
import inspect
from datetime import datetime

_LOGGER = logging.getLogger(__name__)


class RamsesPacketException(Exception):
    pass


class RamsesPacketData(str):
    def __len__(self):
        orig_len = super().__len__()
        if orig_len % 2 != 0:
            raise RamsesPacketException("Data has odd length")
        return orig_len // 2


class RamsesPacketDatetime:
    def __init__(self, dt):
        if isinstance(dt, datetime):
            self.t_datetime = dt
            self.t_str = datetime.isoformat(self.t_datetime)
        else:
            self.t_str = str(dt)
            self.t_datetime = datetime.fromisoformat(self.t_str)

    def __repr__(self):
        return self.t_str


class RamsesPacket:
    def __init__(self, raw_packet=None, src_id="--:------", dst_id="--:------", xxx_id="--:------"):
        self._timestamp = RamsesPacketDatetime(datetime.now())
        self.signal_strength = -1
        self.type = None
        self.src_id = src_id
        self.dst_id = dst_id
        self.xxx_id = xxx_id
        self.code = None
        self.length = 0
        self._data = None
        self._raw_packet = raw_packet
        if self._raw_packet:
            self.parse()

    def __repr__(self):
        all_attr = {k: v for k, v in vars(self).items() if not k.startswith("_")}
        all_prop = {k: getattr(self, k) for k, v in inspect.getmembers(type(self), lambda v: isinstance(v, property))}
        return str({**all_attr, **all_prop})

    @property
    def data(self):
        return self._data

    @data.setter
    def data(self, value):
        self._data = RamsesPacketData(value)
        self.length = len(self._data)

    def payload(self):
        return {"msg": f" {self.type} --- {self.src_id} {self.dst_id} {self.xxx_id} {self.code} {self.length:03d} {self.data}"}

    def json(self):
        return json.dumps(self.payload())

    def parse(self):
        fields = self._raw_packet["msg"].split()
        assert fields[2] == "---"
        self.timestamp = RamsesPacketDatetime(self._raw_packet["ts"])
        self.signal_strength = int(fields[0])
        self.type = fields[1]
        self.src_id = fields[3]
        self.dst_id = fields[4]
        self.xxx_id = fields[5]
        self.code = fields[6]
        self.data = fields[8]
        self.text = None
        assert int(fields[7]) == self.length
        text_func = getattr(self, f"_text_{self.code.lower()}", None)
        if callable(text_func):
            self.text = text_func()
        else:
            _LOGGER.warning(f"No _text_{self.code.lower()}")
        _LOGGER.debug(self.__repr__())

    def _hex_to_date(self, value):
        """From ramses_rf"""
        if value == "FFFFFFFF":
            return None
        return datetime(
            year=int(value[4:8], 16),
            month=int(value[2:4], 16),
            day=int(value[:2], 16) & 0b11111,  # 1st 3 bits: DayOfWeek
        ).strftime("%Y-%m-%d")

    def _text_31d9(self):
        presets = {  # FIXME: dup in ramses_esp
            "00": "Away",
            "01": "Low",
            "02": "Medium",
            "03": "High",
            "04": "Auto",
        }
        if self.length == 1:
            if self.type == "RQ":
                return "Fan state request"
        if self.length != 3:
            return "Unexpected length"
        state = self.data[4:6]
        bitmap = int(self.data[2:4], 16)
        info = str(
            {
                "fan_mode": presets.get(state, "UNKNOWN"),
                "passive": bool(bitmap & 0x02),
                "damper_only": bool(bitmap & 0x04),
                "filter_dirty": bool(bitmap & 0x20),
                "frost_cycle": bool(bitmap & 0x40),
                "has_fault": bool(bitmap & 0x80),
            }
        )
        if self.type == "RP":
            return f"Fan state response: {info}"
        if self.type == "I":
            return f"Fan state: {info}"
        return "Unknown type"

    def _text_1298(self):
        value = int(self.data, 16)
        return f"CO2: {value} ppm"

    def _text_22f1(self):
        return "TODO"

    def _text_22f3(self):
        return "TODO"

    def _text_31e0(self):
        value = int(int(self.data[4:6], 16) / 2)
        return f"Vent demand: {value}%"

    def _text_10e0(self):
        if self.length == 1:
            return "Device info request"
        if self.length == 38 or self.length == 29:
            description, _, _ = self.data[36:].partition("00")
            return str(
                {
                    "sz_oem_code": self.data[14:16],  # 00/FF is CH/DHW, 01/6x is HVAC
                    "manufacturer_group": self.data[2:6],  # 0001-HVAC, 0002-CH/DHW
                    "manufacturer_sub_id": self.data[6:8],
                    "product_id": self.data[8:10],  # if CH/DHW: matches device_type (sometimes)
                    "date_1": self._hex_to_date(self.data[28:36]),
                    "date_2": self._hex_to_date(self.data[20:28]),
                    "software_ver_id": self.data[10:12],
                    "list_ver_id": self.data[12:14],  # if FF/01 is CH/DHW, then 01/FF
                    "additional_ver_a": self.data[16:18],
                    "additional_ver_b": self.data[18:20],
                    "signature": self.data[2:20],
                    "description": bytearray.fromhex(description).decode(),
                }
            )
        return "Unexpected length"


class RamsesPacket_ReqFanState(RamsesPacket):
    def __init__(self, src_id="--:------", dst_id="--:------"):
        super().__init__(src_id=src_id, dst_id=dst_id)
        self.type = "RQ"
        self.code = "31D9"
        self.data = "00"


class RamsesPacket_ReqCO2State(RamsesPacket):
    def __init__(self, src_id="--:------", dst_id="--:------"):
        super().__init__(src_id=src_id, dst_id=dst_id)
        self.type = "RQ"
        self.code = "1298"
        self.data = "00"


class RamsesPacket_SetFanMode(RamsesPacket):
    _presets_data = {
        "Auto": "000404",
        "Low": "000104",
        "Medium": "000204",
        "High": "000304",
        "High (15m)": "00020F03040000",
        "High (30m)": "00021E03040000",
        "High (60m)": "00023C03040000",
        "Away": "000004",
    }

    def __init__(self, preset, src_id="--:------", dst_id="--:------"):
        super().__init__(src_id=src_id, dst_id=dst_id)
        if not self._presets_data.get(preset):
            raise RamsesPacketException(f"Invalid preset '{preset}'")
        self.type = "I"
        self.data = self._presets_data.get(preset)
        self.code = "22F1" if self.length == 3 else "22F3"

    @classmethod
    def presets(cls):
        return list(cls._presets_data.keys())


if __name__ == "__main__":
    packet = json.loads(
        '{"msg": "080  I --- 32:098366 --:------ 32:098366 1298 003 0001B2", "ts": "2025-05-14T17:35:56.828667+02:00"}'
    )
    r = RamsesPacket(packet)
    print(r.payload())
    rd = RamsesPacketDatetime(r.timestamp)
    r2 = RamsesPacketDatetime(rd)
    print(rd, r2)
    r = RamsesPacket()
    r.type = "RP"
    r.src_id = "18:123456"
    r.dst_id = "32:123456"
    r.code = "22F1"
    r.data = "000404"
    print(r.payload())
    r = RamsesPacket_ReqFanState(src_id="18:123456", dst_id="23:654321")
    print(r.payload())
    r = RamsesPacket_SetFanMode(src_id="18:123456", dst_id="23:654321", preset="Auto")
    print(r.presets())
    print(r.payload())
