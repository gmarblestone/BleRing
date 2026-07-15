from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime, timedelta, timezone
import logging
from typing import Any

from .ring_client import ColmiRingClient, HeartRateLog, NoData, SportDetail, scan_devices
from .storage import RingDataStore, SyncSummary

LOGGER = logging.getLogger(__name__)


class ColmiRingApi:
    def __init__(self, address: str, store: RingDataStore) -> None:
        self._address = address
        self._store = store

    @property
    def address(self) -> str:
        return self._address

    @staticmethod
    async def scan(include_all: bool = False) -> list[dict[str, str]]:
        return await scan_devices(include_all=include_all)

    async def fetch_snapshot(self) -> dict[str, Any]:
        snapshot = self._store.get_recent_metrics(self._address)
        async with ColmiRingClient(self._address) as client:
            battery = await client.get_battery()
            info = await client.get_device_info()
        snapshot["battery"] = battery.battery_level
        snapshot["battery_raw"] = self._normalize(battery)
        snapshot["device_info"] = info
        return snapshot

    async def read_realtime(self, reading_name: str) -> dict[str, Any]:
        async with ColmiRingClient(self._address) as client:
            values = await client.get_realtime_reading(reading_name)
        return {
            "reading": reading_name,
            "values": values or [],
            "value": values[-1] if values else None,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    async def sync_history(
        self,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> SyncSummary:
        sync_start = start or self._store.get_last_sync(self._address) or (datetime.now(timezone.utc) - timedelta(days=7))
        sync_end = end or datetime.now(timezone.utc)
        if sync_start.tzinfo is None:
            sync_start = sync_start.replace(tzinfo=timezone.utc)
        if sync_end.tzinfo is None:
            sync_end = sync_end.replace(tzinfo=timezone.utc)

        async with ColmiRingClient(self._address) as client:
            heart_logs, step_logs = await client.get_full_data(sync_start, sync_end)
            await client.set_time(datetime.now(timezone.utc))

        heart_rate_rows = self._flatten_heart_rates(heart_logs)
        sport_detail_rows = self._flatten_sport_details(step_logs)
        summary = self._store.write_sync(
            address=self._address,
            start=sync_start,
            end=sync_end,
            heart_rate_rows=heart_rate_rows,
            sport_detail_rows=sport_detail_rows,
        )
        LOGGER.info(
            "Synced ring %s with %s HR rows and %s sport rows",
            self._address,
            summary.heart_rate_rows,
            summary.sport_detail_rows,
        )
        return summary

    def _flatten_heart_rates(self, logs: list[HeartRateLog | NoData]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for log in logs:
            if isinstance(log, hr.HeartRateLog):
                for reading, timestamp in log.heart_rates_with_times():
                    if reading > 0:
                        rows.append({"reading": reading, "timestamp": timestamp.isoformat()})
        return rows

    def _flatten_sport_details(self, logs: list[list[SportDetail] | NoData]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for log in logs:
            if isinstance(log, list):
                for detail in log:
                    rows.append(
                        {
                            "calories": detail.calories,
                            "steps": detail.steps,
                            "distance": detail.distance,
                            "timestamp": detail.timestamp.isoformat(),
                        }
                    )
        return rows

    def _normalize(self, value: Any) -> Any:
        if is_dataclass(value):
            return asdict(value)
        return value