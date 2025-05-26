from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.const import CONCENTRATION_PARTS_PER_MILLION, PERCENTAGE

from .const import DOMAIN


async def async_setup_entry(hass, entry, async_add_entities):
    data = hass.data[DOMAIN][entry.entry_id]
    sensor = Co2Sensor(data)
    hass.data[DOMAIN]["co2_sensor"] = sensor
    async_add_entities([sensor])
    sensor = HumiditySensor(data)
    hass.data[DOMAIN]["humidity_sensor"] = sensor
    async_add_entities([sensor])


class Co2Sensor(SensorEntity):
    def __init__(self, config):
        self.config = config
        self._attr_name = "Orcon CO2"
        self._attr_native_unit_of_measurement = CONCENTRATION_PARTS_PER_MILLION
        self._attr_device_class = SensorDeviceClass.CO2
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_unique_id = f"orcon_co2_{config['co2_id']}"
        self._state = None

    @property
    def native_value(self):
        return self._state

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.config["co2_id"])},
            manufacturer="Orcon",
            model="MVS-15RH CO2B",
            name="Orcon CO2 bedieningssensor 15RF",
            via_device=(DOMAIN, self.config["fan_id"]),
        )

    def update_state(self, value):
        self._state = value
        self.async_write_ha_state()


class HumiditySensor(SensorEntity):
    def __init__(self, config):
        self.config = config
        self._attr_name = "Orcon Relative Humidity"
        self._attr_native_unit_of_measurement = PERCENTAGE
        self._attr_device_class = SensorDeviceClass.HUMIDITY
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_unique_id = f"orcon_humidity_{config['fan_id']}"
        self._state = None

    @property
    def native_value(self):
        return self._state

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.config["fan_id"])},
            manufacturer="Orcon",
            model="MVS-15RH CO2B",
            name="Orcon fan humidty sensor",
            via_device=(DOMAIN, self.config["gateway_id"]),
        )

    def update_state(self, value):
        self._state = value
        self.async_write_ha_state()
