from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorDeviceClass,
)
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, CONF_FAN_ID
from .orcon_sensor import OrconSensor


async def async_setup_entry(hass, entry, async_add_entities):
    OrconSensor(
        hass=hass,
        async_add_entities=async_add_entities,
        entry=entry,
        ramses_id=entry.data.get(CONF_FAN_ID),
        label="fan",
        entities=[FaultBinarySensor],
    )


class FaultBinarySensor(CoordinatorEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, ramses_id, config, coordinator, label):
        super().__init__(coordinator)
        self.coordinator = coordinator
        self.label = label
        self._attr_name = f"Orcon MVS-15 {label} fault"
        self._attr_unique_id = f"orcon_mvs15_{label}_fault_{ramses_id}"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, ramses_id)})

    @property
    def is_on(self):
        return self.coordinator.data.get(f"{self.label.lower()}_fault")
