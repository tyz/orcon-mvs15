from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.const import CONCENTRATION_PARTS_PER_MILLION, PERCENTAGE

from .const import DOMAIN


async def async_setup_entry(hass, entry, async_add_entities):
    co2_id = hass.data[DOMAIN][entry.entry_id]["co2_id"]
    fan_id = hass.data[DOMAIN][entry.entry_id]["fan_id"]
    pull_coordinator = entry.runtime_data.pull_coordinator
    push_coordinator = entry.runtime_data.push_coordinator
    co2_sensor = Co2Sensor(co2_id, fan_id, push_coordinator)
    hum_sensor = HumiditySensor(fan_id, pull_coordinator)
    async_add_entities([co2_sensor, hum_sensor])


class Co2Sensor(CoordinatorEntity, SensorEntity):
    def __init__(self, co2_id, fan_id, coordinator):
        super().__init__(coordinator)
        self.coordinator = coordinator
        self._state = None
        self._attr_name = "Orcon MVS-15 CO2"
        self._attr_native_unit_of_measurement = CONCENTRATION_PARTS_PER_MILLION
        self._attr_device_class = SensorDeviceClass.CO2
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_unique_id = f"orcon_mvs15_co2_{co2_id}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, co2_id)},
            manufacturer="Orcon",
            model="MVS-15RH CO2B",
            name=f"Orcon CO2 remote 15RF ({co2_id})",
            via_device=(DOMAIN, fan_id),
        )

    @property
    def native_value(self):
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get("co2")


class HumiditySensor(CoordinatorEntity, SensorEntity):
    def __init__(self, fan_id, coordinator):
        super().__init__(coordinator)
        self.coordinator = coordinator
        self._attr_name = "Orcon MVS-15 Relative Humidity"
        self._attr_native_unit_of_measurement = PERCENTAGE
        self._attr_device_class = SensorDeviceClass.HUMIDITY
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_unique_id = f"orcon_mvs15_humidity_{fan_id}"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, fan_id)})

    @property
    def native_value(self):
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get("relative_humidity")
