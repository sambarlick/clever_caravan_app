# Copyright (c) 2026 Samuel Myers. All rights reserved.
# Proprietary - see LICENSE. Unauthorised use, copying, or distribution prohibited.

"""Diagnostics for Clever Caravan: Power.

Adds the "Download diagnostics" item to the integration's menu. Dumps the live
state that matters for support — MQTT connection, configured BLE devices with
their current receiving status, discovered Venus instances, and a snapshot of
resolved values — with encryption keys redacted.
"""
from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant

from .ble_map import CONF_BLE_DEVICES, status_triple
from .const import DOMAIN

_SERVICES = ("solarcharger", "battery", "dcdc", "alternator", "vebus", "system")


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if data is None:
        return {"error": "integration not loaded"}

    hub = data.hub

    ble_devices = []
    for cfg in entry.options.get(CONF_BLE_DEVICES, []):
        ble_devices.append(
            {
                "address": cfg.get("address"),
                "kind": cfg.get("kind"),
                "instance": cfg.get("instance"),
                "key": "**REDACTED**",
                "receiving": data.ble_fresh(*status_triple(cfg)),
            }
        )

    # values dict has tuple keys -> stringify for JSON.
    values = {
        f"{svc}/{inst}/{path}": val
        for (svc, inst, path), val in list(hub.values.items())
    }

    return {
        "mqtt": {
            "host": entry.data.get(CONF_HOST),
            "portal_id": hub.portal_id,
            "connected": hub.connected,
            "heartbeat_ok": hub.heartbeat_ok,
            "value_count": len(values),
        },
        "ble": {
            "device_count": len(ble_devices),
            "devices": ble_devices,
        },
        "instances": {svc: sorted(hub.instances_of(svc)) for svc in _SERVICES},
        "values": values,
    }
