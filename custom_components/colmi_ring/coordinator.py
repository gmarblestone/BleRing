from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from bleak.exc import BleakError
from homeassistant.components.bluetooth import MONOTONIC_TIME, async_last_service_info
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .api import ColmiRingApi
from .const import RECENT_ADVERTISEMENT_SECONDS

LOGGER = logging.getLogger(__name__)


class ColmiRingCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    def __init__(self, hass: HomeAssistant, api: ColmiRingApi, scan_interval: int) -> None:
        super().__init__(
            hass,
            logger=LOGGER,
            name="colmi_ring",
            update_interval=timedelta(seconds=scan_interval) if scan_interval > 0 else None,
        )
        self.api = api
        self.realtime_values: dict[str, Any] = {}
        self.scan_interval = scan_interval

    async def _async_update_data(self) -> dict[str, Any]:
        if self.scan_interval <= 0:
            LOGGER.debug("Automatic polling disabled for ring %s; returning cached data only", self.api.address)
            return {**self._current_data(), **self.realtime_values}

        service_info = async_last_service_info(self.hass, self.api.address, connectable=True)
        if service_info is None:
            LOGGER.debug("Skipping live refresh for ring %s because no recent connectable advertisement is available", self.api.address)
            return {**self._current_data(), **self.realtime_values}

        advertisement_age = MONOTONIC_TIME() - service_info.time
        if advertisement_age > RECENT_ADVERTISEMENT_SECONDS:
            LOGGER.debug(
                "Skipping live refresh for ring %s because last advertisement is %.1fs old",
                self.api.address,
                advertisement_age,
            )
            return {**self._current_data(), **self.realtime_values}

        try:
            data = await self.api.fetch_snapshot()
        except (BleakError, RuntimeError, TimeoutError) as err:
            LOGGER.warning("Deferred refresh for ring until data can be read: %s", err)
            return {**self._current_data(), **self.realtime_values}
        except Exception:
            LOGGER.exception("Deferred refresh for ring after unexpected data read failure")
            return {**self._current_data(), **self.realtime_values}
        LOGGER.debug("Coordinator refresh succeeded for ring %s with keys=%s", self.api.address, sorted(data.keys()))
        return {**data, **self.realtime_values}

    def apply_partial_update(self, data: dict[str, Any]) -> None:
        for key, value in data.items():
            if key.startswith("heart_rate") or key.startswith("spo2"):
                self.realtime_values[key] = value
        self.async_set_updated_data({**self._current_data(), **data})

    def _current_data(self) -> dict[str, Any]:
        return self.data or {}