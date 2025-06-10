from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.const import (
    CONCENTRATION_PARTS_PER_MILLION,
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
)

from .const import DOMAIN, CONF_FAN_ID, CONF_GATEWAY_ID, CONF_CO2_ID


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data.coordinator
    fan_id = entry.data.get(CONF_FAN_ID)
    gateway_id = entry.data.get(CONF_GATEWAY_ID)
    co2_id = entry.data.get(CONF_CO2_ID)
    hum_sensor = HumiditySensor(fan_id, coordinator)
    fan_rssi_sensor = SignalStrengthSensor(fan_id, coordinator, "fan")
    async_add_entities([hum_sensor, fan_rssi_sensor])
    if co2_id is not None:
        """Found in config, previously discovered"""
        co2_sensor = Co2Sensor(co2_id, gateway_id, coordinator)
        co2_rssi_sensor = SignalStrengthSensor(co2_id, coordinator, "CO2")
        async_add_entities([co2_sensor, co2_rssi_sensor])


class Co2Sensor(CoordinatorEntity, SensorEntity):
    def __init__(self, co2_id, gateway_id, coordinator):
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
            via_device=(DOMAIN, gateway_id),
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


class SignalStrengthSensor(CoordinatorEntity, SensorEntity):
    def __init__(self, ramses_id, coordinator, device_type):
        super().__init__(coordinator)
        self.coordinator = coordinator
        self.device_type = device_type
        self._attr_name = f"Orcon MVS-15 {device_type} RSSI"
        self._attr_native_unit_of_measurement = SIGNAL_STRENGTH_DECIBELS_MILLIWATT
        self._attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_unique_id = f"orcon_mvs15_rssi_{ramses_id}"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, ramses_id)})

    @property
    def native_value(self):
        if not self.coordinator.data:
            return None
        return self.coordinator.data.get(f"{self.device_type.lower()}_rssi")
