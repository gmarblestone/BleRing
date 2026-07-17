from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
import struct
from typing import Any

from bleak import BleakClient, BleakScanner
from bleak_retry_connector import BleakClientWithServiceCache, close_stale_connections_by_address, establish_connection
from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import BluetoothReachabilityIntent
from homeassistant.core import HomeAssistant

LOGGER = logging.getLogger(__name__)

UART_SERVICE_UUID = "6E40FFF0-B5A3-F393-E0A9-E50E24DCCA9E"
UART_RX_CHAR_UUID = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"
UART_TX_CHAR_UUID = "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"

DEVICE_INFO_UUID = "0000180A-0000-1000-8000-00805F9B34FB"
DEVICE_HW_UUID = "00002A27-0000-1000-8000-00805F9B34FB"
DEVICE_FW_UUID = "00002A26-0000-1000-8000-00805F9B34FB"

CMD_SET_TIME = 0x01
CMD_BATTERY = 0x03
CMD_READ_HEART_RATE = 0x15
CMD_GET_STEP_SOMEDAY = 0x43
CMD_START_REAL_TIME = 0x69
CMD_STOP_REAL_TIME = 0x6A

READING_TYPES = {
    "heart-rate": 1,
    "spo2": 3,
}

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


@dataclass
class BatteryInfo:
    battery_level: int
    charging: bool


@dataclass
class HeartRateLog:
    heart_rates: list[int]
    timestamp: datetime

    def heart_rates_with_times(self) -> list[tuple[int, datetime]]:
        points: list[tuple[int, datetime]] = []
        current = datetime(self.timestamp.year, self.timestamp.month, self.timestamp.day, tzinfo=timezone.utc)
        for reading in self.heart_rates:
            points.append((reading, current))
            current += timedelta(minutes=5)
        return points


@dataclass
class SportDetail:
    year: int
    month: int
    day: int
    time_index: int
    calories: int
    steps: int
    distance: int

    @property
    def timestamp(self) -> datetime:
        return datetime(
            year=self.year,
            month=self.month,
            day=self.day,
            hour=self.time_index // 4,
            minute=(self.time_index % 4) * 15,
            tzinfo=timezone.utc,
        )


class NoData:
    pass


class HeartRateParser:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._raw: list[int] = []
        self.timestamp: datetime | None = None
        self.size = 0
        self.index = 0
        self.range = 5

    def parse(self, packet: bytearray) -> HeartRateLog | NoData | None:
        sub_type = packet[1]
        if sub_type == 255:
            self.reset()
            return NoData()
        if sub_type == 0:
            self.size = packet[2]
            self.range = packet[3]
            self._raw = [-1] * (self.size * 13)
            self.index = 0
            return None
        if sub_type == 1:
            ts = struct.unpack_from("<l", packet, offset=2)[0]
            self.timestamp = datetime.fromtimestamp(ts, timezone.utc)
            self._raw[0:9] = list(packet[6:-1])
            self.index = 9
            return None

        self._raw[self.index : self.index + 13] = list(packet[2:15])
        self.index += 13
        if sub_type != self.size - 1:
            return None

        assert self.timestamp is not None
        values = self._normalized_heart_rates()
        result = HeartRateLog(heart_rates=values, timestamp=self.timestamp)
        self.reset()
        return result

    def _normalized_heart_rates(self) -> list[int]:
        values = self._raw.copy()
        if len(values) > 288:
            values = values[:288]
        elif len(values) < 288:
            values.extend([0] * (288 - len(values)))

        if self.timestamp is not None and self.timestamp.date() == datetime.now(timezone.utc).date():
            current_slot = ((datetime.now(timezone.utc).hour * 60) + datetime.now(timezone.utc).minute) // 5
            values[current_slot:] = [0] * len(values[current_slot:])
        return values


class SportDetailParser:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.new_calorie_protocol = False
        self.index = 0
        self.details: list[SportDetail] = []

    def parse(self, packet: bytearray) -> list[SportDetail] | NoData | None:
        if self.index == 0 and packet[1] == 255:
            self.reset()
            return NoData()

        if self.index == 0 and packet[1] == 240:
            self.new_calorie_protocol = packet[3] == 1
            self.index += 1
            return None

        calories = packet[7] | (packet[8] << 8)
        if self.new_calorie_protocol:
            calories *= 10
        detail = SportDetail(
            year=bcd_to_decimal(packet[1]) + 2000,
            month=bcd_to_decimal(packet[2]),
            day=bcd_to_decimal(packet[3]),
            time_index=packet[4],
            calories=calories,
            steps=packet[9] | (packet[10] << 8),
            distance=packet[11] | (packet[12] << 8),
        )
        self.details.append(detail)
        if packet[5] == packet[6] - 1:
            result = self.details
            self.reset()
            return result

        self.index += 1
        return None


class ColmiRingClient:
    def __init__(self, hass: HomeAssistant, address: str) -> None:
        self.hass = hass
        self.address = address
        self._client: BleakClient = BleakClient(address)
        self._queues: dict[int, asyncio.Queue[Any]] = {
            CMD_BATTERY: asyncio.Queue(),
            CMD_READ_HEART_RATE: asyncio.Queue(),
            CMD_GET_STEP_SOMEDAY: asyncio.Queue(),
            CMD_START_REAL_TIME: asyncio.Queue(),
            CMD_SET_TIME: asyncio.Queue(),
        }
        self._hr_parser = HeartRateParser()
        self._steps_parser = SportDetailParser()
        self._rx_char: Any = None

    async def __aenter__(self) -> ColmiRingClient:
        await self.connect()
        return self

    async def __aexit__(self, exc_type: type[BaseException] | None, exc_val: BaseException | None, exc_tb: Any) -> None:
        await self.disconnect()

    async def connect(self) -> None:
        await close_stale_connections_by_address(self.address)
        await bluetooth.async_request_active_scan(self.hass)
        device = bluetooth.async_ble_device_from_address(self.hass, self.address, connectable=True)
        if device is None:
            device = bluetooth.async_ble_device_from_address(self.hass, self.address, connectable=True)
        if device is None:
            reason = bluetooth.async_address_reachability_diagnostics(
                self.hass,
                self.address,
                BluetoothReachabilityIntent.CONNECTION,
            )
            raise RuntimeError(f"Ring {self.address} not found during connect: {reason}")
        self._client = await establish_connection(
            BleakClientWithServiceCache,
            device,
            device.name or self.address,
            max_attempts=3,
            services=[UART_SERVICE_UUID, DEVICE_INFO_UUID],
        )
        services = await self._resolve_services()
        uart_service = services.get_service(UART_SERVICE_UUID)
        if uart_service is None:
            raise RuntimeError("Ring UART service not found")
        self._rx_char = uart_service.get_characteristic(UART_RX_CHAR_UUID)
        if self._rx_char is None:
            raise RuntimeError("Ring RX characteristic not found")
        await self._client.start_notify(UART_TX_CHAR_UUID, self._handle_notification)

    async def disconnect(self) -> None:
        if self._client.is_connected:
            await self._client.disconnect()

    async def get_battery(self) -> BatteryInfo:
        await self._send_packet(make_packet(CMD_BATTERY))
        result = await asyncio.wait_for(self._queues[CMD_BATTERY].get(), timeout=5)
        return result

    async def get_device_info(self) -> dict[str, str]:
        services = await self._resolve_services()
        service = services.get_service(DEVICE_INFO_UUID)
        if service is None:
            return {}

        info: dict[str, str] = {}
        hw_char = service.get_characteristic(DEVICE_HW_UUID)
        if hw_char is not None:
            info["hw_version"] = (await self._client.read_gatt_char(hw_char)).decode("utf-8", errors="ignore")
        fw_char = service.get_characteristic(DEVICE_FW_UUID)
        if fw_char is not None:
            info["fw_version"] = (await self._client.read_gatt_char(fw_char)).decode("utf-8", errors="ignore")
        return info

    async def _resolve_services(self) -> Any:
        services = getattr(self._client, "services", None)
        if services is not None:
            return services

        get_services = getattr(self._client, "get_services", None)
        if get_services is None:
            raise RuntimeError("Connected BLE client does not expose GATT services")

        return await get_services()

    async def get_realtime_reading(self, reading_name: str) -> list[int] | None:
        reading_type = READING_TYPES[reading_name]
        await self._send_packet(make_packet(CMD_START_REAL_TIME, bytearray([reading_type, 1])))

        values: list[int] = []
        tries = 0
        while len(values) < 6 and tries < 20:
            try:
                data = await asyncio.wait_for(self._queues[CMD_START_REAL_TIME].get(), timeout=2)
            except TimeoutError:
                tries += 1
                continue

            if data["error"]:
                values = []
                break
            if data["value"] != 0:
                values.append(data["value"])

        await self._send_packet(make_packet(CMD_STOP_REAL_TIME, bytearray([reading_type, 0, 0])))
        return values or None

    async def set_time(self, target: datetime) -> None:
        await self._send_packet(set_time_packet(target))

    async def get_heart_rate_log(self, target: datetime) -> HeartRateLog | NoData:
        midnight = datetime(target.year, target.month, target.day, tzinfo=timezone.utc)
        await self._send_packet(read_heart_rate_packet(midnight))
        return await asyncio.wait_for(self._queues[CMD_READ_HEART_RATE].get(), timeout=5)

    async def get_steps(self, target: datetime) -> list[SportDetail] | NoData:
        target_utc = target.astimezone(timezone.utc) if target.tzinfo else target.replace(tzinfo=timezone.utc)
        today = datetime.now(timezone.utc)
        day_offset = max((today.date() - target_utc.date()).days, 0)
        await self._send_packet(read_steps_packet(day_offset))
        return await asyncio.wait_for(self._queues[CMD_GET_STEP_SOMEDAY].get(), timeout=5)

    async def get_full_data(self, start: datetime, end: datetime) -> tuple[list[HeartRateLog | NoData], list[list[SportDetail] | NoData]]:
        heart_rates: list[HeartRateLog | NoData] = []
        sport_details: list[list[SportDetail] | NoData] = []
        for day in iter_dates(start, end):
            heart_rates.append(await self.get_heart_rate_log(day))
            sport_details.append(await self.get_steps(day))
        return heart_rates, sport_details

    async def _send_packet(self, packet: bytearray) -> None:
        if self._rx_char is None:
            raise RuntimeError("BLE client not connected")
        await self._client.write_gatt_char(self._rx_char, packet, response=False)

    def _handle_notification(self, _sender: Any, packet: bytearray) -> None:
        if len(packet) != 16:
            LOGGER.debug("Ignoring unexpected packet length: %s", packet)
            return

        packet_type = packet[0]
        if packet_type == CMD_BATTERY:
            self._queues[CMD_BATTERY].put_nowait(BatteryInfo(battery_level=packet[1], charging=bool(packet[2])))
            return
        if packet_type == CMD_START_REAL_TIME:
            self._queues[CMD_START_REAL_TIME].put_nowait(
                {"error": packet[2] != 0, "value": packet[3]}
            )
            return
        if packet_type == CMD_READ_HEART_RATE:
            result = self._hr_parser.parse(packet)
            if result is not None:
                self._queues[CMD_READ_HEART_RATE].put_nowait(result)
            return
        if packet_type == CMD_GET_STEP_SOMEDAY:
            result = self._steps_parser.parse(packet)
            if result is not None:
                self._queues[CMD_GET_STEP_SOMEDAY].put_nowait(result)
            return
        if packet_type == CMD_SET_TIME:
            self._queues[CMD_SET_TIME].put_nowait(True)


async def scan_devices(include_all: bool = False) -> list[dict[str, str]]:
    devices = await BleakScanner.discover()
    results: list[dict[str, str]] = []
    for device in devices:
        name = device.name or ""
        if include_all:
            results.append({"name": name or "Unknown BLE Device", "address": device.address})
            continue
        if name and any(name.startswith(prefix) for prefix in DEVICE_NAME_PREFIXES):
            results.append({"name": name, "address": device.address})
    return sorted(results, key=lambda item: (item["name"], item["address"]))


def make_packet(command: int, sub_data: bytearray | None = None) -> bytearray:
    packet = bytearray(16)
    packet[0] = command
    if sub_data is not None:
        packet[1 : 1 + len(sub_data)] = sub_data
    packet[-1] = sum(packet) & 255
    return packet


def read_heart_rate_packet(target: datetime) -> bytearray:
    return make_packet(CMD_READ_HEART_RATE, bytearray(struct.pack("<L", int(target.timestamp()))))


def read_steps_packet(day_offset: int) -> bytearray:
    sub_data = bytearray(b"\x00\x0f\x00\x5f\x01")
    sub_data[0] = day_offset
    return make_packet(CMD_GET_STEP_SOMEDAY, sub_data)


def set_time_packet(target: datetime) -> bytearray:
    if target.tzinfo != timezone.utc:
        target = target.astimezone(timezone.utc)
    data = bytearray(7)
    data[0] = to_bcd(target.year % 2000)
    data[1] = to_bcd(target.month)
    data[2] = to_bcd(target.day)
    data[3] = to_bcd(target.hour)
    data[4] = to_bcd(target.minute)
    data[5] = to_bcd(target.second)
    data[6] = 1
    return make_packet(CMD_SET_TIME, data)


def to_bcd(value: int) -> int:
    return ((value // 10) << 4) | (value % 10)


def bcd_to_decimal(value: int) -> int:
    return (((value >> 4) & 0x0F) * 10) + (value & 0x0F)


def iter_dates(start: datetime, end: datetime) -> Iterable[datetime]:
    current = datetime(start.year, start.month, start.day, tzinfo=timezone.utc)
    final = datetime(end.year, end.month, end.day, tzinfo=timezone.utc)
    while current <= final:
        yield current
        current += timedelta(days=1)