from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.device_registry import DeviceEntryType
from datetime import datetime
from .const import DOMAIN

async def async_setup_entry(hass, config_entry, async_add_entities):
    coordinator = hass.data[DOMAIN][config_entry.entry_id]
    base = config_entry.data.get("name", "Home")
    entities = [
        DtekSensor(coordinator, base, "Schedule", "schedule", None, True),
        DtekSensor(coordinator, base, "Status", "current_power", "mdi:power-plug"),
        DtekSensor(coordinator, base, "Group", "current_group", "mdi:account-group"),
        DtekSensor(coordinator, base, "Outage Type", "outage_type", "mdi:alert-circle"),
        DtekSensor(coordinator, base, "Message Start", "message_start", "mdi:calendar-alert"),
        DtekSensor(coordinator, base, "Message End", "message_end", "mdi:calendar-check"),
        DtekSensor(coordinator, base, "Last Update", "last_update", "mdi:update"),
    ]
    for i in range(1, 5):
        entities.append(DtekEventSensor(coordinator, base, "outage", i))
        entities.append(DtekEventSensor(coordinator, base, "connection", i))
    async_add_entities(entities)

class DtekSensor(CoordinatorEntity, SensorEntity):
    def __init__(self, coordinator, name, suffix, key, icon, is_attr=False):
        super().__init__(coordinator)
        self._key, self._icon, self._is_attr = key, icon, is_attr
        self._name = f"{name} {suffix}"
        self._attr_unique_id = f"{coordinator.config.get('name')}_{suffix.lower().replace(' ', '_')}"
    @property
    def name(self): return self._name
    @property
    def unique_id(self): return self._attr_unique_id
    @property
    def state(self):
        val = getattr(self.coordinator.data, self._key)
        if self._is_attr: 
            if self.coordinator.data.outage_type == "Emergency": return "Inactive"
            return "Active" if val else "No Data"
        if self._key == "outage_type":
             if val == "Scheduled": return "Scheduled"
             if val == "Emergency": return "Emergency"
             if "Екстренні" in str(val): return "Emergency"
             return val 
        return val if val else "Unknown"
    @property
    def icon(self): 
        if self._key == "current_power": return "mdi:power-plug" if self.state == "On" else "mdi:power-plug-off"
        return self._icon
    @property
    def extra_state_attributes(self): return {"schedule": getattr(self.coordinator.data, self._key)} if self._is_attr else {}
    @property
    def device_info(self): return {"identifiers": {(DOMAIN, self.coordinator.config.get("name"))}, "name": self.coordinator.config.get("name", "DTEK"), "manufacturer": "DTEK", "model": self.coordinator.region_code, "entry_type": DeviceEntryType.SERVICE}

class DtekEventSensor(CoordinatorEntity, SensorEntity):
    def __init__(self, coordinator, name, event_type, index):
        super().__init__(coordinator)
        self._type, self._idx = event_type, index
        self._name = f"{name} Next {event_type.capitalize()} {index}"
        self._attr_unique_id = f"{coordinator.config.get('name')}_{event_type}_{index}"
    @property
    def name(self): return self._name
    @property
    def unique_id(self): return self._attr_unique_id
    @property
    def state(self):
        lst = self.coordinator.data.next_outages if self._type == "outage" else self.coordinator.data.next_connections
        if (self._idx - 1) < len(lst): return datetime.fromisoformat(lst[self._idx-1]).strftime("%H:%M %d.%m")
        return "Unknown"
    @property
    def icon(self): return "mdi:flash-off" if self._type == "outage" else "mdi:flash"
    @property
    def device_info(self): return {"identifiers": {(DOMAIN, self.coordinator.config.get("name"))}, "name": self.coordinator.config.get("name", "DTEK"), "manufacturer": "DTEK", "model": self.coordinator.region_code, "entry_type": DeviceEntryType.SERVICE}