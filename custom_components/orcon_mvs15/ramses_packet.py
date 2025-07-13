from __future__ import annotations

from typing import Callable

import logging
import uuid
import inspect

from datetime import datetime

_LOGGER = logging.getLogger(__name__)


class RamsesPacketException(Exception):
    pass


class RamsesPacketData(str):
    def __len__(self) -> int:
        orig_len = super().__len__()
        if orig_len % 2 != 0:
            raise RamsesPacketException("Data has odd length")
        return orig_len // 2


class RamsesPacketDatetime:
    def __init__(self, dt: datetime | str) -> None:
        self.t_datetime: datetime | None
        self.t_str: str
        if isinstance(dt, datetime):
            self.t_datetime = dt
            self.t_str = datetime.isoformat(self.t_datetime)
        elif isinstance(dt, str):
            if len(dt) == 8:
                """YYYY-MM-DD hex date"""
                self.t_datetime = self._hex_to_date(dt)
                self.t_str = dt
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

    def __repr__(self) -> str:
        return self.t_str

    def _hex_to_date(self, value: str) -> datetime | None:
        if value == "FFFFFFFF":
            return None
        return datetime(
            year=int(value[4:8], 16),
            month=int(value[2:4], 16),
            day=int(value[:2], 16) & 0b11111,  # 1st 3 bits: DayOfWeek
        )


class RamsesID(str):
    """str with a default"""

    empty_address = "--:------"

    def __new__(cls, value: str | None = empty_address) -> RamsesID:
        if not value:
            value = cls.empty_address
        return super().__new__(cls, value)

    def __bool__(self) -> bool:
        return self != self.empty_address


class RamsesPacket:
    def __init__(
        self,
        envelope: dict = {},
        src_id: RamsesID = RamsesID(),
        dst_id: RamsesID = RamsesID(),
        ann_id: RamsesID = RamsesID(),
        type: str = "",
        code: str = "",
        data: str = "",
    ) -> None:
        self._timestamp = RamsesPacketDatetime(datetime.now())
        self.signal_strength = -1
        self.type = type
        self.src_id = src_id
        self.dst_id = dst_id
        self.ann_id = ann_id
        self.code = code
        self.expected_response: RamsesPacketResponse | None = None
        self.length: int = 0
        self.packet_id = uuid.uuid4().hex
        self.data = data
        self._envelope = envelope
        if self._envelope:
            self.parse()

    def __repr__(self) -> str:
        all_attr = {k: v for k, v in vars(self).items() if not k.startswith("_")}
        all_prop = {
            k: getattr(self, k)
            for k, v in inspect.getmembers(
                type(self), lambda v: isinstance(v, property)
            )
        }
        return str({**all_attr, **all_prop})

    @property
    def data(self) -> str | RamsesPacketData | None:
        return self._data

    @data.setter
    def data(self, value: str) -> None:
        if not value:
            self.length = 0
            self._data = RamsesPacketData()
            return
        self._data = RamsesPacketData(value)
        self.length = len(self._data)

    def ramses_esp_envelope(self) -> dict:
        return {
            "msg": f"{self.type:2s} --- {self.src_id} {self.dst_id} {self.ann_id} {self.code} {self.length:03d} {self.data}"
        }

    def parse(self) -> None:
        fields = self._envelope["msg"].split()
        assert fields[2] == "---", "Missing dashes"
        self.timestamp = RamsesPacketDatetime(self._envelope["ts"])
        try:
            self.signal_strength = int(fields[0])
        except ValueError:
            _LOGGER.warning(f"Signal strength == {fields[0]}")
            self.signal_strength = -1
        self.type = fields[1]
        self.src_id = RamsesID(fields[3])
        self.dst_id = RamsesID(fields[4])
        self.ann_id = RamsesID(fields[5])
        self.code = fields[6]
        if int(fields[7]) > 0:
            assert len(fields) == 9, "Wrong number of fields"
            self.data = fields[8]
            assert int(fields[7]) == self.length, (
                f"Wrong length ({fields[7]} vs {self.length})"
            )
        else:
            assert len(fields) == 8, "No data expected!"
            self.data = ""


class RamsesPacketResponse(RamsesPacket):
    def __init__(
        self,
        src_id: RamsesID = RamsesID(),
        dst_id: RamsesID = RamsesID(),
        ann_id: RamsesID = RamsesID(),
        type: str = "",
        code: str = "",
        max_retries: int = 2,
        timeout: int = 2,
    ) -> None:
        super().__init__(
            src_id=src_id, dst_id=dst_id, ann_id=ann_id, type=type, code=code
        )
        self.max_retries: int = max_retries
        self.timeout: int = timeout
        self.cancel_retry_handler: Callable[[], None] | None = None

    def __eq__(self, b: object) -> bool:
        """Compare expected response to response"""
        if not isinstance(b, RamsesPacket):
            return NotImplemented
        return (
            ((not self.type) or self.type == b.type)
            and ((not self.code) or self.code == b.code)
            and ((not self.src_id) or self.src_id == b.src_id)
            and ((not self.dst_id) or self.dst_id == b.dst_id)
        )
