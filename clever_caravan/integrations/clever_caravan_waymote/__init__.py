# Copyright (c) 2026 Samuel Myers. All rights reserved.
# Proprietary - see LICENSE. Unauthorised use, copying, or distribution prohibited.

"""The Clever Caravan: Waymote integration.

Stage 1: connect to the bridge, read its config.json, and register the Waymote
as a device. Switch entities are added in a later stage.
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN
from .coordinator import WaymoteCoordinator

_LOGGER = logging.getLogger(__name__)

# Outputs become switches/lights/fans; plus bridge-level sensors and buttons.
PLATFORMS: list[Platform] = [
    Platform.SWITCH,
    Platform.LIGHT,
    Platform.FAN,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
]

type WaymoteConfigEntry = ConfigEntry[WaymoteCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: WaymoteConfigEntry) -> bool:
    """Set up Waymote from a config entry."""
    coordinator = WaymoteCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    device_registry = dr.async_get(hass)
    device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, entry.unique_id or entry.entry_id)},
        manufacturer="Clever Caravan",
        model="Waymote Bridge",
        name="Waymote",
        configuration_url=coordinator.base_url,
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: WaymoteConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
