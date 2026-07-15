# Colmi Ring Home Assistant Integration

This repository contains a custom Home Assistant integration for Colmi R02-family smart rings using the upstream BLE client at <https://github.com/tahnok/colmi_r02_client>.

Current release: `0.1.0`

## What it does

- Scans for nearby compatible BLE rings and returns their MAC addresses.
- Connects to a configured ring over BLE.
- Exposes Home Assistant sensors for battery, latest heart rate, latest SpO2, latest steps, distance, calories, and last sync time.
- Syncs historical heart-rate and activity data from the ring into a dedicated SQLite database stored under the Home Assistant config directory.
- Lets Home Assistant Recorder persist sensor state history automatically.

## Install

1. Copy `custom_components/colmi_ring` into your Home Assistant `config/custom_components` directory.
2. Restart Home Assistant so it installs the `colmi-r02-client` Python dependency.
3. In Home Assistant, open Settings > Devices & services > Add Integration and add `Colmi Ring`.
4. Pick a discovered ring from the scan results, or enter the BLE MAC address manually.
5. Repeat the add-integration step for each additional user or ring.
6. If a ring's MAC address changes, remove that entry and add it again with the new address.

## Configuration

The preferred setup is through Home Assistant's UI config flow. Each configured ring is stored as its own config entry inside Home Assistant, which is the clean way to support multiple users.

If you want to discover the MAC address first, call the scan service from Developer Tools after Home Assistant has loaded the integration:

```yaml
action: colmi_ring.scan
```

If you still want to seed entries from YAML, the integration can import them on startup:

```yaml
colmi_ring:
  - address: "70:CB:0D:D0:34:1C"
    name: "Bedroom Ring"
    scan_interval: 900
    db_path: "/config/colmi_ring_history.sqlite3"
```

## Services

### `colmi_ring.scan`

Returns nearby supported devices with BLE names and MAC addresses.

Example Developer Tools call:

```yaml
action: colmi_ring.scan
```

### `colmi_ring.read_realtime`

Triggers a realtime measurement and updates the matching sensor.

```yaml
action: colmi_ring.read_realtime
data:
  address: "70:CB:0D:D0:34:1C"
  reading: heart-rate
```

Supported `reading` values:

- `heart-rate`
- `spo2`

### `colmi_ring.sync`

Reads history from the ring and writes it to the SQLite database.

```yaml
action: colmi_ring.sync
data:
  address: "70:CB:0D:D0:34:1C"
  start: "2026-07-01T00:00:00+00:00"
  end: "2026-07-15T00:00:00+00:00"
```

If `start` is omitted, the integration continues from the most recent sync end time. If nothing has been synced before, it defaults to the last 7 days.
If only one ring is configured, `address` can be omitted from the service call.

## Data storage

The integration stores detailed ring history in its own SQLite database. That is intentional: Home Assistant Recorder owns its own schema and should not be written to directly by custom integrations. Entity state changes still go into Home Assistant's Recorder database automatically.

The custom SQLite database includes these tables:

- `rings`
- `syncs`
- `heart_rates`
- `sport_details`

## Notes

- BLE access must be available to the Home Assistant host.
- The ring may need to be worn for live heart-rate or SpO2 measurements to succeed.
- Add one config entry per user or ring when multiple people share the Home Assistant instance.