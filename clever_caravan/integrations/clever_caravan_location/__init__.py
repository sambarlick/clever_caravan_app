# Copyright (c) 2026 Samuel Myers. All rights reserved.
# Proprietary - see LICENSE. Unauthorised use, copying, or distribution prohibited.

"""Clever Caravan: Location integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import entity_registry as er

from .const import CONF_SOURCE, DOMAIN, SERVICE_UPDATE, SOURCE_USB
from .coordinator import CaravanLocationCoordinator
from .sources import build_source

# USB-specific entities. Disabled by default on non-USB sources via
# v0.6.2; this list is also used by the v0.6.3 one-shot migration to
# clean up entities that were registered enabled before v0.6.2.
USB_ONLY_KEYS: frozenset[str] = frozenset({
    "fix_quality",
    "fix_mode",
    "satellites_used",
    "satellites_visible",
    "hdop",
    "accuracy_horizontal",
    "accuracy_vertical",
    "gps_atomic_time",
    "gps_healthy",
})

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.IMAGE, Platform.BUTTON]


def _disable_usb_entities_if_needed(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """One-shot cleanup: disable USB-specific entities on non-USB installs.

    Pre-v0.6.2 these were registered enabled. v0.6.2 changed the default
    for new installs but did not retroactively disable existing ones.
    This migration disables them, but only if the user hasn't already
    explicitly disabled or enabled them (i.e. disabled_by is None and
    they're still in the integration-default state).

    This also runs on reconfigure: switching a USB source to entity/manual
    triggers a reload, and the GPS-only entities disable themselves here.
    """
    if entry.data.get(CONF_SOURCE) == SOURCE_USB:
        return

    registry = er.async_get(hass)
    for entity_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
        # entity_entry.unique_id format is "{entry_id}_{key}"
        prefix = f"{entry.entry_id}_"
        if not entity_entry.unique_id.startswith(prefix):
            continue
        key = entity_entry.unique_id[len(prefix):]
        if key not in USB_ONLY_KEYS:
            continue
        if entity_entry.disabled_by is not None:
            continue  # already disabled, leave alone
        registry.async_update_entity(
            entity_entry.entity_id,
            disabled_by=er.RegistryEntryDisabler.INTEGRATION,
        )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Clever Caravan: Location from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    source = build_source(hass, dict(entry.data))
    coordinator = CaravanLocationCoordinator(hass, source)
    await source.async_start()

    hass.data[DOMAIN][entry.entry_id] = {
        "source": source,
        "coordinator": coordinator,
    }

    _disable_usb_entities_if_needed(hass, entry)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register the update service once (across all entries — single instance
    # is enforced in the config flow anyway).
    if not hass.services.has_service(DOMAIN, SERVICE_UPDATE):
        async def _handle_update(_call: ServiceCall) -> None:
            for data in hass.data[DOMAIN].values():
                if "coordinator" in data:
                    await data["coordinator"].async_force_update()

        hass.services.async_register(DOMAIN, SERVICE_UPDATE, _handle_update)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        data = hass.data[DOMAIN].pop(entry.entry_id)
        await data["source"].async_stop()
        # Last entry going? Tear down the service.
        if not hass.data[DOMAIN]:
            hass.services.async_remove(DOMAIN, SERVICE_UPDATE)
    return unload_ok
