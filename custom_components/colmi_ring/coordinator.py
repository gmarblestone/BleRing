from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from bleak.exc import BleakError
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .api import ColmiRingApi

LOGGER = logging.getLogger(__name__)


class ColmiRingCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    def __init__(self, hass: HomeAssistant, api: ColmiRingApi, scan_interval: int) -> None:
        super().__init__(
            hass,
            logger=LOGGER,
            name="colmi_ring",
            update_interval=timedelta(seconds=scan_interval),
        )
        self.api = api
        self.realtime_values: dict[str, Any] = {}

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            data = await self.api.fetch_snapshot()
        except (BleakError, RuntimeError, TimeoutError) as err:
            LOGGER.warning("Deferred refresh for ring until data can be read: %s", err)
            return {**self._current_data(), **self.realtime_values}
        except Exception:
            LOGGER.exception("Deferred refresh for ring after unexpected data read failure")
            return {**self._current_data(), **self.realtime_values}
        return {**data, **self.realtime_values}

    def apply_partial_update(self, data: dict[str, Any]) -> None:
        for key, value in data.items():
            if key.startswith("heart_rate") or key.startswith("spo2"):
                self.realtime_values[key] = value
        self.async_set_updated_data({**self._current_data(), **data})

    def _current_data(self) -> dict[str, Any]:
        return self.data or {}