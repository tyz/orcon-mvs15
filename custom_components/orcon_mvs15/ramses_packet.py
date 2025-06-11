import logging
import json
import uuid
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
        elif isinstance(dt, str):
            if len(dt) == 8:
                """YYYY-MM-DD hex date"""
                self.t_datetime = self._hex_to_date(dt)
                self.t_str = ""
                if self.t_datetime:
                    self.t_str = self.t_datetime.strftime("%Y-%m-%d")
            else:
                """ISO 8601"""
                self.t_str = str(dt)
                try:
                    self.t_datetime = datetime.fromisoformat(self.t_str)
                except ValueError as e:
                    raise RamsesPacketException(e)
        else:
            raise RamsesPacketException(f"Don't know how to convert date {dt}")

    def __repr__(self):
        return self.t_str

    def _hex_to_date(self, value):
        if value == "FFFFFFFF":
            return None
        return datetime(
            year=int(value[4:8], 16),
            month=int(value[2:4], 16),
            day=int(value[:2], 16) & 0b11111,  # 1st 3 bits: DayOfWeek
        )


class RamsesPacket:
    def __init__(
        self,
        raw_packet=None,
        src_id="--:------",
        dst_id="--:------",
        ann_id="--:------",
        type=None,
        code=None,
        data=None,
        expected_response=None,
    ):
        self._timestamp = RamsesPacketDatetime(datetime.now())
        self.signal_strength = -1
        self.type = type
        self.src_id = src_id
        self.dst_id = dst_id
        self.ann_id = ann_id
        self.code = code
        self.length = 0
        self.packet_id = uuid.uuid4().hex
        self.expected_response = expected_response
        self.data = data
        self._raw_packet = raw_packet
        if self._raw_packet:
            self.parse()

    def __repr__(self):
        all_attr = {k: v for k, v in vars(self).items() if not k.startswith("_")}
        all_prop = {
            k: getattr(self, k)
            for k, v in inspect.getmembers(
                type(self), lambda v: isinstance(v, property)
            )
        }
        return str({**all_attr, **all_prop})

    @property
    def data(self):
        return self._data

    @data.setter
    def data(self, value):
        if value:
            self._data = RamsesPacketData(value)
            self.length = len(self._data)
        else:
            self._data = None
            self.length = 0

    def ramses_esp_envelope(self):
        return {
            "msg": f" {self.type} --- {self.src_id} {self.dst_id} {self.ann_id} {self.code} {self.length:03d} {self.data}"
        }

    def json(self):
        return json.dumps(self.payload())

    def parse(self):
        fields = self._raw_packet["msg"].split()
        assert len(fields) == 9, "Wrong number of fields"
        assert fields[2] == "---", "Missing dashes"
        self.timestamp = RamsesPacketDatetime(self._raw_packet["ts"])
        try:
            self.signal_strength = int(fields[0])
        except ValueError:
            _LOGGER.warning(f"Signal strength == {fields[0]}")
            self.signal_strength = -1
        self.type = fields[1]
        self.src_id = fields[3]
        self.dst_id = fields[4]
        self.ann_id = fields[5]
        self.code = fields[6]
        self.data = fields[8]
        assert int(fields[7]) == self.length, (
            f"Wrong length ({fields[7]} vs {self.length})"
        )


class RamsesPacketResponse(RamsesPacket):
    def __init__(
        self,
        max_retries=2,
        timeout=2,
        cancel_retry_handler=None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.max_retries = max_retries
        self.timeout = timeout
        self.cancel_retry_handler = cancel_retry_handler

    def __eq__(self, b):
        """Compare expected response to response"""
        return (
            ((not self.type) or self.type == b.type)
            and ((not self.code) or self.code == b.code)
            and ((not self.src_id) or self.src_id == b.src_id)
            and ((not self.dst_id) or self.dst_id == b.dst_id)
        )
