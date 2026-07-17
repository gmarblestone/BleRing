# Colmi Ring Home Assistant Integration

[![Open your Home Assistant instance and open this repository inside HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=gmarblestone&repository=BleRing&category=integration)

This repository contains a custom Home Assistant integration for Colmi R02-family smart rings, with the BLE protocol implemented directly inside the integration for Home Assistant compatibility.

Current release: `0.2.13`

## Debug logging

To turn on verbose logs in Home Assistant, add this to your `configuration.yaml`:

```yaml
logger:
  default: warning
  logs:
    custom_components.colmi_ring: debug
```

That will show BLE connection attempts, device resolution, packet flow, snapshot fetches, and coordinator refresh results for this integration.

## Polling behavior

Automatic polling now defaults to once per hour.

The integration will only attempt a live BLE refresh when Home Assistant has seen a recent connectable advertisement from the ring. If the ring is out of range or has not advertised recently, it keeps the cached values and avoids a noisy connection attempt.

Set the polling interval to `0` in the integration options to disable automatic polling completely. In that mode, use `colmi_ring.read_realtime` or `colmi_ring.sync` only when you want to talk to the ring.

## What it does

- Scans for nearby compatible BLE rings and returns their MAC addresses.
- Connects to a configured ring over BLE.
- Exposes Home Assistant sensors for battery, latest heart rate, latest SpO2, latest steps, distance, calories, and last sync time.
- Syncs historical heart-rate and activity data from the ring into a dedicated SQLite database stored under the Home Assistant config directory.
- Lets Home Assistant Recorder persist sensor state history automatically.

## Docker install

This is the cleanest path if you want Home Assistant to load the integration automatically from your filesystem instead of through HACS.

1. Start Home Assistant with `docker compose up -d`.
2. Check container health with `docker compose ps`.
3. In Home Assistant, open Settings > Devices & services > Add Integration.
4. Add `Colmi Ring`, scan for nearby devices, and pick the ring you want.
5. Restart Home Assistant after each integration update so it reloads the files and dependency version.

If no known ring names are detected, the setup flow now falls back to showing all nearby BLE devices so you can still pick the correct MAC address.

The compose file mounts this repository's [custom_components](custom_components) directory directly into `/config/custom_components`, so updates in the repo become updates in Home Assistant on restart.

If you want a second compose variant to edit locally without changing the committed one, [docker-compose.yml.example](docker-compose.yml.example) remains as a copyable template.

Example host layout:

```text
BleRing/
  custom_components/
  docker-compose.yml
  ha-config/
    configuration.yaml
```

Notes for BLE in Docker:

- The example uses `network_mode: host` and mounts `/run/dbus`, which is the typical Linux setup for Bluetooth access from Home Assistant.
- This is intended for a Linux Docker host with a local Bluetooth adapter.
- If Home Assistant runs elsewhere, the BLE adapter must be available on that host.

## Docker troubleshooting

- If the ring scan returns nothing, verify the Docker host itself can see the Bluetooth adapter before debugging Home Assistant.
- If Home Assistant starts but Bluetooth operations fail, confirm `/run/dbus` is mounted and that the container is running with `network_mode: host`.
- If you update the integration but Home Assistant still shows old behavior, restart the container so it reloads the bind-mounted files.
- If Python dependency installation fails during startup, check the Home Assistant container logs with `docker compose logs -f homeassistant`.
- If you run Docker on Windows or macOS without a Linux Bluetooth stack exposed into the container host, BLE access will usually fail. This setup is aimed at Linux.
- Run `./scripts/check_ble_host.sh` on the Linux Docker host to verify DBus and Bluetooth adapter visibility before debugging Home Assistant itself.
- If logs show `failed to discover services, device disconnected`, the integration reached the same failure point as the upstream Python client. In practice that usually means the ring is still connected to the phone app, too far away, asleep, or the local adapter/proxy cannot hold a stable GATT session.

## UI install

The integration is now UI-managed by default:

1. Start Home Assistant with the integration mounted.
2. Open Settings > Devices & services > Add Integration and add `Colmi Ring`.
3. Pick a discovered ring from the scan results, or enter the BLE MAC address manually.
4. Repeat the add-integration step for each additional user or ring.
5. If a ring's MAC address changes, remove that entry and add it again with the new address.

## Configuration

The preferred setup is through Home Assistant's UI config flow. Each configured ring is stored as its own config entry inside Home Assistant, which is the clean way to support multiple users.

If you want to discover the MAC address first, call the scan service from Developer Tools after Home Assistant has loaded the integration:

```yaml
action: colmi_ring.scan
```

No `colmi_ring:` YAML block is required for normal setup anymore.

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

## CI and assets

- GitHub Actions CI is defined in `.github/workflows/ci.yml` and validates JSON, YAML, Python syntax, and version consistency on pushes and pull requests.
- Local brand assets live in `custom_components/colmi_ring/brand/` so modern Home Assistant versions can show an integration icon and logo without relying on the central brands repository.

## Notes

- BLE access must be available to the Home Assistant host.
- The ring may need to be worn for live heart-rate or SpO2 measurements to succeed.
- Add one config entry per user or ring when multiple people share the Home Assistant instance.