# Copyright (c) 2026 Samuel Myers. All rights reserved.
# Proprietary - see LICENSE. Unauthorised use, copying, or distribution prohibited.

"""Repairs flow for Clever Caravan: Power.

When a Victron device advertises over Bluetooth without a key (issue raised by
the discovery watcher in __init__.py), the fix flow offers two choices:

  * Add key  — paste the Instant Readout key; it's folded onto the matching MQTT
               device and BLE fallback goes live.
  * Ignore   — record the MAC so it's never nagged about again (sticky across
               restarts). Un-ignore later under Options -> Victron Bluetooth
               fallback.
  * Stop discovery — turn BLE discovery off. The reload clears every un-keyed
               issue and the ignored list (see __init__.py).
"""
from __future__ import annotations

import voluptuous as vol

from homeassistant.components.repairs import RepairsFlow
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .ble_map import (
    CONF_BLE_DEVICES,
    CONF_BLE_DISCOVERY,
    CONF_BLE_IGNORED,
    KIND_LABELS,
    is_valid_key,
    resolve_instance,
)
from .const import DOMAIN


class BleKeyRepairFlow(RepairsFlow):
    """Add-key-or-ignore flow for an un-keyed Victron BLE device."""

    def __init__(self, data: dict | None) -> None:
        self._data = data or {}

    def _placeholders(self) -> dict:
        return {
            "kind": KIND_LABELS.get(
                self._data.get("kind"), self._data.get("kind", "device")
            ),
            "address": self._data.get("address", ""),
        }

    async def async_step_init(self, user_input=None):
        return self.async_show_menu(
            step_id="init",
            menu_options=["add_key", "ignore", "stop_discovery"],
            description_placeholders=self._placeholders(),
        )

    async def async_step_add_key(self, user_input=None):
        errors: dict[str, str] = {}
        if user_input is not None:
            key = (user_input.get("key") or "").strip()
            if not key:
                # Blank -> back to the menu rather than silently dismissing.
                return await self.async_step_init()
            if is_valid_key(key):
                await _fold_in(self.hass, self._data, key)
                return self.async_create_entry(title="", data={})
            errors["base"] = "invalid_key"

        return self.async_show_form(
            step_id="add_key",
            data_schema=vol.Schema({vol.Optional("key"): str}),
            errors=errors,
            description_placeholders=self._placeholders(),
        )

    async def async_step_ignore(self, user_input=None):
        await _ignore(self.hass, self._data)
        return self.async_create_entry(title="", data={})

    async def async_step_stop_discovery(self, user_input=None):
        await _stop_discovery(self.hass, self._data)
        return self.async_create_entry(title="", data={})


async def _fold_in(hass: HomeAssistant, data: dict, key: str) -> None:
    entry_id = data.get("entry_id")
    entry = hass.config_entries.async_get_entry(entry_id) if entry_id else None
    if entry is None:
        return
    runtime = hass.data.get(DOMAIN, {}).get(entry_id)
    hub = runtime.hub if runtime else None
    kind = data.get("kind")
    existing = list(entry.options.get(CONF_BLE_DEVICES, []))
    if any(d["address"].upper() == data["address"].upper() for d in existing):
        ir.async_delete_issue(hass, DOMAIN, data.get("issue_id", ""))
        return
    instance = resolve_instance(hub, kind, existing)
    existing.append(
        {"address": data["address"], "key": key, "kind": kind, "instance": instance}
    )
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_BLE_DEVICES: existing}
    )
    ir.async_delete_issue(
        hass, DOMAIN, data.get("issue_id", f"ble_unkeyed_{data['address']}")
    )
    await hass.config_entries.async_reload(entry_id)


async def _ignore(hass: HomeAssistant, data: dict) -> None:
    entry_id = data.get("entry_id")
    entry = hass.config_entries.async_get_entry(entry_id) if entry_id else None
    mac = (data.get("address") or "").upper()
    if entry is not None and mac:
        ignored = [m.upper() for m in entry.options.get(CONF_BLE_IGNORED, [])]
        if mac not in ignored:
            ignored.append(mac)
            hass.config_entries.async_update_entry(
                entry, options={**entry.options, CONF_BLE_IGNORED: ignored}
            )
    ir.async_delete_issue(hass, DOMAIN, data.get("issue_id", ""))


async def _stop_discovery(hass: HomeAssistant, data: dict) -> None:
    entry_id = data.get("entry_id")
    entry = hass.config_entries.async_get_entry(entry_id) if entry_id else None
    ir.async_delete_issue(hass, DOMAIN, data.get("issue_id", ""))
    if entry is None:
        return
    # Options change -> update listener reloads -> setup purges the backlog.
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, CONF_BLE_DISCOVERY: False}
    )


async def async_create_fix_flow(hass, issue_id, data) -> RepairsFlow:
    return BleKeyRepairFlow(data)
