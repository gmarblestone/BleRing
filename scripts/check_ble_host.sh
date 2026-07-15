#!/usr/bin/env sh
set -eu

echo "Checking Linux Bluetooth host prerequisites"

if [ ! -S /run/dbus/system_bus_socket ] && [ ! -S /var/run/dbus/system_bus_socket ]; then
  echo "DBus system bus socket not found"
  exit 1
fi

if command -v bluetoothctl >/dev/null 2>&1; then
  echo "bluetoothctl: available"
  bluetoothctl list || true
else
  echo "bluetoothctl: not installed"
fi

if command -v hciconfig >/dev/null 2>&1; then
  echo "hciconfig: available"
  hciconfig -a || true
elif command -v btmgmt >/dev/null 2>&1; then
  echo "btmgmt: available"
  btmgmt info || true
else
  echo "No bluetooth adapter inspection tool found (hciconfig or btmgmt)"
fi

echo "If no adapter is listed above, fix host Bluetooth access before debugging Home Assistant."