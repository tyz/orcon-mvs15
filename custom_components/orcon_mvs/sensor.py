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
        self._state = None
        self._attr_name = "Orcon CO2"
        self._attr_native_unit_of_measurement = CONCENTRATION_PARTS_PER_MILLION
        self._attr_device_class = SensorDeviceClass.CO2
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_unique_id = f"orcon_co2_{config['co2_id']}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, config["co2_id"])},
            manufacturer="Orcon",
            model="MVS-15RH CO2B",
            name=f"Orcon CO2 remote 15RF ({config['co2_id']})",
            via_device=(DOMAIN, config["fan_id"]),
        )

    @property
    def native_value(self):
        return self._state

    def update_state(self, value):
        self._state = value
        self.async_write_ha_state()


class HumiditySensor(SensorEntity):
    def __init__(self, config):
        self._state = None
        self._attr_name = "Orcon Relative Humidity"
        self._attr_native_unit_of_measurement = PERCENTAGE
        self._attr_device_class = SensorDeviceClass.HUMIDITY
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_unique_id = f"orcon_humidity_{config['fan_id']}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, config["fan_id"])},
            name=f"Orcon MVS-15 fan ({config['fan_id']})",
        )

    @property
    def native_value(self):
        return self._state

    def update_state(self, value):
        self._state = value
        self.async_write_ha_state()
