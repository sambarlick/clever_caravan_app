# Copyright (c) 2026 Samuel Myers. All rights reserved.
# Proprietary - see LICENSE. Unauthorised use, copying, or distribution prohibited.

"""Shared helpers for Clever Caravan TPMS entity platforms."""

from __future__ import annotations

from homeassistant.components.bluetooth.passive_update_processor import (
    PassiveBluetoothEntityKey,
)
from homeassistant.helpers.device_registry import (
    CONNECTION_BLUETOOTH,
    DeviceInfo,
)

from .parser import TPMSReading, short_address


def device_info(reading: TPMSReading) -> DeviceInfo:
    """Build the device registry entry for a sensor."""
    return DeviceInfo(
        connections={(CONNECTION_BLUETOOTH, reading.address)},
        identifiers={("clever_caravan_tpms", reading.address)},
        name=f"Safety Sam TPMS Wheel {reading.wheel} ({short_address(reading.address)})",
        manufacturer="Safety Sam",
        model="Bluetooth TPMS",
    )


def key(name: str) -> PassiveBluetoothEntityKey:
    """Entity key helper (single device per coordinator, so device_id=None)."""
    return PassiveBluetoothEntityKey(key=name, device_id=None)
