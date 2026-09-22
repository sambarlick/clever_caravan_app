# Copyright (c) 2026 Samuel Myers. All rights reserved.
# Proprietary - see LICENSE. Unauthorised use, copying, or distribution prohibited.

"""Clever Caravan TPMS — passive BLE tyre pressure monitoring."""

from __future__ import annotations

import logging

from homeassistant.components.bluetooth import (
    BluetoothScanningMode,
    BluetoothServiceInfoBleak,
)
from homeassistant.components.bluetooth.passive_update_processor import (
    PassiveBluetoothProcessorCoordinator,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .parser import TPMSReading, parse

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SENSOR]

type TPMSConfigEntry = ConfigEntry[
    PassiveBluetoothProcessorCoordinator[TPMSReading | None]
]


def _update_method(
    service_info: BluetoothServiceInfoBleak,
) -> TPMSReading | None:
    return parse(service_info)


async def async_setup_entry(hass: HomeAssistant, entry: TPMSConfigEntry) -> bool:
    """Set up a Safety Sam TPMS sensor from a config entry."""
    address = entry.unique_id
    assert address is not None

    coordinator = PassiveBluetoothProcessorCoordinator(
        hass,
        _LOGGER,
        address=address,
        mode=BluetoothScanningMode.PASSIVE,
        update_method=_update_method,
    )
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Only start receiving advertisements after platforms are ready.
    entry.async_on_unload(coordinator.async_start())
    return True


async def async_unload_entry(hass: HomeAssistant, entry: TPMSConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
