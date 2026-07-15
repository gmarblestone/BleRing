from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime, timedelta, timezone
import logging
from typing import Any

from bleak import BleakScanner
from colmi_r02_client import hr, real_time, steps
from colmi_r02_client.client import Client

from .storage import RingDataStore, SyncSummary

LOGGER = logging.getLogger(__name__)

DEVICE_NAME_PREFIXES = (
    "R01",
    "R02",
    "R03",
    "R04",
    "R05",
    "R06",
    "R07",
    "R09",
    "R10",
    "COLMI",
    "VK-5098",
    "MERLIN",
    "Hello Ring",
    "RING1",
    "boAtring",
    "TR-R02",
    "SE",
    "EVOLVEO",
    "GL-SR2",
    "Blaupunkt",
    "KSIX RING",
)


class ColmiRingApi:
    def __init__(self, address: str, store: RingDataStore) -> None:
        self._address = address
        self._store = store

    @property
    def address(self) -> str:
        return self._address

    @staticmethod
    async def scan() -> list[dict[str, str]]:
        devices = await BleakScanner.discover()
        results: list[dict[str, str]] = []
        for device in devices:
            name = device.name or ""
            if name and any(name.startswith(prefix) for prefix in DEVICE_NAME_PREFIXES):
                results.append({"name": name, "address": device.address})
        return sorted(results, key=lambda item: (item["name"], item["address"]))

    async def fetch_snapshot(self) -> dict[str, Any]:
        snapshot = self._store.get_recent_metrics(self._address)
        async with Client(self._address) as client:
            battery = await client.get_battery()
            info = await client.get_device_info()
        snapshot["battery"] = getattr(battery, "battery_level", None)
        snapshot["battery_raw"] = self._normalize(battery)
        snapshot["device_info"] = info
        return snapshot

    async def read_realtime(self, reading_name: str) -> dict[str, Any]:
        reading_type = real_time.REAL_TIME_MAPPING[reading_name]
        async with Client(self._address) as client:
            values = await client.get_realtime_reading(reading_type)
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

        async with Client(self._address) as client:
            full_data = await client.get_full_data(sync_start, sync_end)
            now = datetime.now(timezone.utc)
            await client.set_time(now)

        heart_rate_rows = self._flatten_heart_rates(full_data.heart_rates)
        sport_detail_rows = self._flatten_sport_details(full_data.sport_details)
        summary = self._store.write_sync(
            address=self._address,
            start=sync_start,
            end=sync_end,
            heart_rate_rows=heart_rate_rows,
            sport_detail_rows=sport_detail_rows,
        )
        LOGGER.info("Synced ring %s with %s HR rows and %s sport rows", self._address, summary.heart_rate_rows, summary.sport_detail_rows)
        return summary

    def _flatten_heart_rates(self, logs: list[hr.HeartRateLog | hr.NoData]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for log in logs:
            if isinstance(log, hr.HeartRateLog):
                for reading, timestamp in log.heart_rates_with_times():
                    if reading > 0:
                        rows.append({"reading": reading, "timestamp": timestamp.isoformat()})
        return rows

    def _flatten_sport_details(self, logs: list[list[steps.SportDetail] | steps.NoData]) -> list[dict[str, Any]]:
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