import logging

_LOGGER = logging.getLogger(__name__)


class OrconSensor:
    def __init__(self, hass, async_add_entities, entry, ramses_id, label, entities):
        self.unsub_listener = {}
        self.async_add_entities = async_add_entities
        self.config = entry.data
        self.ramses_id = ramses_id
        self.label = label
        self.entities = entities
        self.coordinator = entry.runtime_data.coordinator
        if ramses_id is None:
            self.unsub_listener[label] = self.coordinator.async_add_listener(
                self._add_discovered_sensors
            )
            hass.async_create_task(self.coordinator.async_refresh())
        else:
            self._add_sensors()

    def _add_sensors(self):
        _LOGGER.info(
            f"Creating {len(self.entities)} {self.label} sensors ({self.ramses_id})"
        )
        new_entities = [
            x(self.ramses_id, self.config, self.coordinator, self.label)
            for x in self.entities
        ]
        self.async_add_entities(new_entities, True)

    def _add_discovered_sensors(self):
        self.ramses_id = self.coordinator.data.get(f"{self.label.lower()}_id")
        if not self.ramses_id:
            return
        self._add_sensors()
        self.unsub_listener[self.label]()  # done, unsubscribe from DataCoordinator
