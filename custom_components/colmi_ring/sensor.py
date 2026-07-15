from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, CONF_NAME, EntityCategory, PERCENTAGE, UnitOfLength
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DATA_COORDINATOR, DOMAIN


@dataclass(frozen=True, kw_only=True)
class ColmiSensorDescription(SensorEntityDescription):
    value_key: str


SENSORS: tuple[ColmiSensorDescription, ...] = (
    ColmiSensorDescription(
        key="battery",
        translation_key="battery",
        name="Battery",
        native_unit_of_measurement=PERCENTAGE,
        device_class="battery",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_key="battery",
    ),
    ColmiSensorDescription(
        key="heart_rate",
        translation_key="heart_rate",
        name="Heart Rate",
        native_unit_of_measurement="bpm",
        value_key="heart_rate",
    ),
    ColmiSensorDescription(
        key="spo2",
        translation_key="spo2",
        name="Blood Oxygen",
        native_unit_of_measurement=PERCENTAGE,
        value_key="spo2",
    ),
    ColmiSensorDescription(
        key="steps",
        translation_key="steps",
        name="Steps",
        native_unit_of_measurement="steps",
        value_key="steps",
    ),
    ColmiSensorDescription(
        key="distance",
        translation_key="distance",
        name="Distance",
        native_unit_of_measurement=UnitOfLength.METERS,
        value_key="distance",
    ),
    ColmiSensorDescription(
        key="calories",
        translation_key="calories",
        name="Calories",
        native_unit_of_measurement="kcal",
        value_key="calories",
    ),
    ColmiSensorDescription(
        key="last_sync",
        translation_key="last_sync",
        name="Last Sync",
        device_class="timestamp",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_key="last_sync",
    ),
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id][DATA_COORDINATOR]
    device_config = {**entry.data, **entry.options}
    async_add_entities([ColmiRingSensor(coordinator, device_config, description) for description in SENSORS])


class ColmiRingSensor(CoordinatorEntity, SensorEntity):
    entity_description: ColmiSensorDescription

    def __init__(self, coordinator: Any, device_config: dict[str, Any], description: ColmiSensorDescription) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        address = device_config[CONF_ADDRESS]
        title = device_config.get(CONF_NAME, address)
        self._attr_unique_id = f"{address.lower().replace(':', '_')}_{description.key}"
        self._attr_has_entity_name = True
        self._attr_device_info = {
            "identifiers": {(DOMAIN, address)},
            "name": title,
            "manufacturer": "Colmi",
            "model": "R02 family",
        }

    @property
    def native_value(self) -> Any:
        return self.coordinator.data.get(self.entity_description.value_key)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data
        attrs: dict[str, Any] = {}
        if self.entity_description.key == "battery":
            attrs["battery_info"] = data.get("battery_raw")
            attrs["device_info"] = data.get("device_info")
        if self.entity_description.key == "heart_rate":
            attrs["timestamp"] = data.get("heart_rate_timestamp")
        if self.entity_description.key == "spo2":
            attrs["timestamp"] = data.get("spo2_timestamp")
        if self.entity_description.key in {"steps", "distance", "calories"}:
            attrs["timestamp"] = data.get("steps_timestamp")
        if self.entity_description.key == "last_sync":
            attrs["start"] = data.get("last_sync_start")
            attrs["end"] = data.get("last_sync_end")
        return attrs