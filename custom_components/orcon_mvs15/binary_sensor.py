from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorDeviceClass,
)
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, CONF_FAN_ID


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data.coordinator
    fan_id = entry.data.get(CONF_FAN_ID)
    fan_fault_sensor = FaultBinarySensor(fan_id, coordinator, "fan")
    async_add_entities([fan_fault_sensor])


class FaultBinarySensor(CoordinatorEntity, BinarySensorEntity):
    def __init__(self, ramses_id, coordinator, device_type):
        super().__init__(coordinator)
        self.coordinator = coordinator
        self.device_type = device_type
        self._attr_name = f"Orcon MVS-15 {device_type} fault"
        self._attr_device_class = BinarySensorDeviceClass.PROBLEM
        self._attr_unique_id = f"orcon_mvs15_fault_{ramses_id}"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, ramses_id)})

    @property
    def is_on(self):
        return self.coordinator.data.get(f"{self.device_type.lower()}_fault")
