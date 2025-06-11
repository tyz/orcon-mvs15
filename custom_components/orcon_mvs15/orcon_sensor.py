import logging

_LOGGER = logging.getLogger(__name__)


class OrconSensor:
    def __init__(
        self, hass, async_add_entities, config, coordinator, ramses_id, label, entities
    ):
        self.unsub_listener = {}
        self.async_add_entities = async_add_entities
        self.config = config
        self.ramses_id = ramses_id
        self.label = label
        self.entities = entities
        self.coordinator = coordinator
        self.discovery_key = f"discovered_{label.lower()}_id"
        if ramses_id is None:
            _LOGGER.debug(
                f"Setting up discovery for {label} sensors on '{self.discovery_key}'"
            )
            self.unsub_listener[label] = self.coordinator.async_add_listener(
                self._add_discovered_sensors
            )
            hass.async_create_task(self.coordinator.async_refresh())
        else:
            self._add_sensors()

    def _add_sensors(self):
        _LOGGER.debug(
            f"Creating {len(self.entities)} {self.label} sensors ({self.ramses_id})"
        )
        new_entities = [
            x(self.ramses_id, self.config, self.coordinator, self.label)
            for x in self.entities
        ]
        self.async_add_entities(new_entities, True)

    def _add_discovered_sensors(self):
        self.ramses_id = self.coordinator.data.get(self.discovery_key)
        if not self.ramses_id:
            return
        _LOGGER.debug(f"Creating discovered {self.label} sensors")
        self._add_sensors()
        self.unsub_listener[self.label]()  # done, unsubscribe from DataCoordinator
