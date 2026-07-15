from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, SOURCE_IMPORT
from homeassistant.const import CONF_ADDRESS, CONF_NAME
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.helpers import config_validation as cv

from .api import ColmiRingApi
from .const import (
    ATTR_END,
    ATTR_READING,
    ATTR_START,
    CONF_DB_PATH,
    CONF_SCAN_INTERVAL,
    DATA_CLIENT,
    DATA_COORDINATOR,
    DATA_STORE,
    DEFAULT_DB_FILENAME,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    PLATFORMS,
    READING_HEART_RATE,
    READING_SPO2,
    SERVICE_READ_REALTIME,
    SERVICE_SCAN,
    SERVICE_SYNC,
)
from .coordinator import ColmiRingCoordinator
from .storage import RingDataStore

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.All(
            cv.ensure_list,
            [
                vol.Schema(
                    {
                        vol.Required(CONF_ADDRESS): cv.string,
                        vol.Optional(CONF_NAME): cv.string,
                        vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): cv.positive_int,
                        vol.Optional(CONF_DB_PATH): cv.string,
                    }
                )
            ],
        )
    },
    extra=vol.ALLOW_EXTRA,
)


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    hass.data.setdefault(DOMAIN, {})
    await _register_services(hass)

    for device_config in config.get(DOMAIN, []):
        hass.async_create_task(
            hass.config_entries.flow.async_init(
                DOMAIN,
                context={"source": SOURCE_IMPORT},
                data=device_config,
            )
        )

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    await _async_setup_device(hass, entry)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def _async_setup_device(hass: HomeAssistant, entry: ConfigEntry) -> None:
    data = {**entry.data, **entry.options}
    address = data[CONF_ADDRESS]
    db_path = data.get(CONF_DB_PATH)
    if db_path:
        resolved_db_path = Path(db_path)
    else:
        resolved_db_path = Path(hass.config.path(DEFAULT_DB_FILENAME))

    store = RingDataStore(resolved_db_path)
    api = ColmiRingApi(address=address, store=store)
    coordinator = ColmiRingCoordinator(hass, api, data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL))
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = {
        DATA_CLIENT: api,
        DATA_COORDINATOR: coordinator,
        DATA_STORE: store,
        "address": address,
        "name": data.get(CONF_NAME, address),
        "entry_id": entry.entry_id,
    }


async def _register_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_SCAN):
        return

    async def handle_scan(call: ServiceCall) -> ServiceResponse:
        return {"devices": await ColmiRingApi.scan()}

    async def handle_read_realtime(call: ServiceCall) -> ServiceResponse:
        entry_data = _resolve_target(hass, call)
        reading = call.data[ATTR_READING]
        coordinator: ColmiRingCoordinator = entry_data[DATA_COORDINATOR]
        result = await entry_data[DATA_CLIENT].read_realtime(reading)
        value_key = "heart_rate" if reading == READING_HEART_RATE else READING_SPO2
        timestamp_key = f"{value_key}_timestamp"
        coordinator.apply_partial_update(
            {
                value_key: result["value"],
                timestamp_key: result["timestamp"],
            }
        )
        return result

    async def handle_sync(call: ServiceCall) -> ServiceResponse:
        entry_data = _resolve_target(hass, call)
        coordinator: ColmiRingCoordinator = entry_data[DATA_COORDINATOR]
        start = _parse_dt(call.data.get(ATTR_START))
        end = _parse_dt(call.data.get(ATTR_END))
        summary = await entry_data[DATA_CLIENT].sync_history(start=start, end=end)
        coordinator.apply_partial_update(entry_data[DATA_STORE].get_recent_metrics(entry_data["address"]))
        return RingDataStore.summary_as_dict(summary)

    hass.services.async_register(
        DOMAIN,
        SERVICE_SCAN,
        handle_scan,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_READ_REALTIME,
        handle_read_realtime,
        schema=vol.Schema(
            {
                vol.Required(ATTR_READING): vol.In([READING_HEART_RATE, READING_SPO2]),
                vol.Optional(CONF_ADDRESS): cv.string,
            }
        ),
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SYNC,
        handle_sync,
        schema=vol.Schema(
            {
                vol.Optional(ATTR_START): cv.string,
                vol.Optional(ATTR_END): cv.string,
                vol.Optional(CONF_ADDRESS): cv.string,
            }
        ),
        supports_response=SupportsResponse.ONLY,
    )


def _parse_dt(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value)


def _resolve_target(hass: HomeAssistant, call: ServiceCall) -> dict[str, Any]:
    address = call.data.get(CONF_ADDRESS)
    if address:
        normalized = address.upper()
        for data in hass.data[DOMAIN].values():
            if data["address"].upper() == normalized:
                return data
    if len(hass.data[DOMAIN]) == 1:
        return next(iter(hass.data[DOMAIN].values()))
    raise vol.Invalid("Specify address when multiple rings are configured")