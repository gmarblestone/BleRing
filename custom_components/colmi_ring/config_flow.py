from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_ADDRESS, CONF_NAME
from homeassistant.helpers.selector import SelectOptionDict, SelectSelector, SelectSelectorConfig

from .api import ColmiRingApi
from .const import CONF_DB_PATH, CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL, DOMAIN

LOGGER = logging.getLogger(__name__)


def _normalize_address(address: str) -> str:
    return address.strip().upper()


def _build_schema(user_input: dict[str, Any] | None = None) -> vol.Schema:
    data = user_input or {}
    return vol.Schema(
        {
            vol.Required(CONF_NAME, default=data.get(CONF_NAME, "")): str,
            vol.Required(CONF_ADDRESS, default=data.get(CONF_ADDRESS, "")): str,
            vol.Optional(CONF_SCAN_INTERVAL, default=data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)): int,
            vol.Optional(CONF_DB_PATH, default=data.get(CONF_DB_PATH, "")): str,
        }
    )


def _build_scan_schema(
    user_input: dict[str, Any] | None,
    discovered_devices: list[dict[str, str]],
) -> vol.Schema:
    data = user_input or {}
    schema: dict[Any, Any] = {
        vol.Optional(CONF_ADDRESS, default=data.get(CONF_ADDRESS, "")): str,
        vol.Optional(CONF_NAME, default=data.get(CONF_NAME, "")): str,
        vol.Optional(CONF_SCAN_INTERVAL, default=data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)): int,
        vol.Optional(CONF_DB_PATH, default=data.get(CONF_DB_PATH, "")): str,
    }
    if discovered_devices:
        options = [
            SelectOptionDict(
                value=device[CONF_ADDRESS],
                label=_device_label(device),
            )
            for device in discovered_devices
        ]
        schema = {
            vol.Optional("discovered_address", default=data.get("discovered_address", "")): SelectSelector(
                SelectSelectorConfig(options=options, mode="dropdown")
            ),
            **schema,
        }
    return vol.Schema(schema)


def _build_options_schema(current: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_NAME, default=current.get(CONF_NAME, "")): str,
            vol.Optional(CONF_SCAN_INTERVAL, default=current.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)): int,
            vol.Optional(CONF_DB_PATH, default=current.get(CONF_DB_PATH, "")): str,
        }
    )


class ColmiRingConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1
    _discovered_devices: list[dict[str, str]]
    _showing_all_devices: bool

    def __init__(self) -> None:
        self._discovered_devices = []
        self._showing_all_devices = False

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> config_entries.ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is None:
            try:
                self._discovered_devices = await ColmiRingApi.scan()
                self._showing_all_devices = False
                if not self._discovered_devices:
                    all_devices = await ColmiRingApi.scan(include_all=True)
                    if all_devices:
                        self._discovered_devices = all_devices
                        self._showing_all_devices = True
            except Exception:
                LOGGER.exception("BLE scan failed while opening config flow")
                self._discovered_devices = []
                errors["base"] = "scan_failed"
            return self.async_show_form(
                step_id="user",
                data_schema=_build_scan_schema(None, self._discovered_devices),
                errors=errors
                or (
                    {"base": "showing_all_devices"}
                    if self._showing_all_devices
                    else ({"base": "no_devices_found"} if not self._discovered_devices else None)
                ),
            )

        cleaned = _merge_scan_input(user_input, self._discovered_devices)
        if not cleaned.get(CONF_ADDRESS):
            errors["base"] = "address_required"
            return self.async_show_form(
                step_id="user",
                data_schema=_build_scan_schema(user_input, self._discovered_devices),
                errors=errors,
            )

        cleaned = _clean_input(cleaned)
        await self.async_set_unique_id(cleaned[CONF_ADDRESS])
        self._abort_if_unique_id_configured()
        title = cleaned.get(CONF_NAME) or cleaned[CONF_ADDRESS]
        return self.async_create_entry(title=title, data=cleaned)

    @staticmethod
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> config_entries.OptionsFlow:
        return ColmiRingOptionsFlow(config_entry)


class ColmiRingOptionsFlow(config_entries.OptionsFlow):
    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self.config_entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> config_entries.ConfigFlowResult:
        if user_input is not None:
            cleaned = _clean_input({**self.config_entry.data, **self.config_entry.options, **user_input})
            options = {
                CONF_NAME: cleaned[CONF_NAME],
                CONF_SCAN_INTERVAL: cleaned[CONF_SCAN_INTERVAL],
                CONF_DB_PATH: cleaned.get(CONF_DB_PATH, ""),
            }
            self.hass.config_entries.async_update_entry(
                self.config_entry,
                title=cleaned.get(CONF_NAME) or cleaned[CONF_ADDRESS],
                options=options,
            )
            return self.async_create_entry(title="", data={})

        current = {**self.config_entry.data, **self.config_entry.options}
        return self.async_show_form(step_id="init", data_schema=_build_options_schema(current))


def _clean_input(user_input: dict[str, Any]) -> dict[str, Any]:
    cleaned = dict(user_input)
    cleaned[CONF_ADDRESS] = _normalize_address(cleaned[CONF_ADDRESS])
    cleaned[CONF_NAME] = cleaned[CONF_NAME].strip() or cleaned[CONF_ADDRESS]
    db_path = cleaned.get(CONF_DB_PATH, "").strip()
    cleaned[CONF_DB_PATH] = db_path
    cleaned[CONF_SCAN_INTERVAL] = int(cleaned[CONF_SCAN_INTERVAL])
    return cleaned


def _merge_scan_input(
    user_input: dict[str, Any],
    discovered_devices: list[dict[str, str]],
) -> dict[str, Any]:
    cleaned = dict(user_input)
    selected_address = cleaned.pop("discovered_address", "")
    if selected_address and not cleaned.get(CONF_ADDRESS):
        cleaned[CONF_ADDRESS] = selected_address

    if not cleaned.get(CONF_NAME) and selected_address:
        for device in discovered_devices:
            if device[CONF_ADDRESS] == selected_address:
                cleaned[CONF_NAME] = device.get(CONF_NAME) or _device_label(device)
                break

    return cleaned


def _device_label(device: dict[str, str]) -> str:
    name = device.get(CONF_NAME) or "Unknown"
    address = device[CONF_ADDRESS]
    return f"{name} ({address})"