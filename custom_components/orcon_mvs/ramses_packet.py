import logging
from datetime import datetime

_LOGGER = logging.getLogger(__name__)


class RamsesPacket:
    def __init__(self, raw_packet):
        self.raw_packet = raw_packet
        self.parse()

    def __repr__(self):
        return str(vars(self))

    def parse(self):
        fields = self.raw_packet["msg"].split()
        self.timestamp = datetime.fromisoformat(self.raw_packet["ts"])
        self.signal_strength = int(fields[0])
        self.type = fields[1]
        assert fields[2] == "---"
        self.src_id = fields[3]
        self.dst_id = fields[4]
        self.xxx_id = fields[5]
        self.code = fields[6]
        self.length = int(fields[7])
        self.data = fields[8]
        assert self.length * 2 == len(self.data)
        _LOGGER.debug(self.__repr__())
