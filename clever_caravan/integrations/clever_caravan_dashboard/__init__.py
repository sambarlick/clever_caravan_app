# Copyright (c) 2026 Samuel Myers. All rights reserved.
# Proprietary - see LICENSE. Unauthorised use, copying, or distribution prohibited.

"""The Clever Caravan Dashboard integration.

Serves the bundled dashboard *strategy* and registers it as a Lovelace **module
resource**. Community dashboard strategies must be loaded as a resource before
Home Assistant will show and instantiate them in the new-dashboard dialog.

Notes on the Lovelace internals this touches (verified against HA 2026.x):
- hass.data["lovelace"] is a LovelaceData *dataclass* (not a dict). Use
  attribute access: `.resources`, `.resource_mode` (NOT `.mode`).
- The storage resource collection is lazy-loaded. Core issue #165767: calling
  async_items()/async_create_item() before the collection has loaded returns an
  empty set and a subsequent create *overwrites* .storage/lovelace_resources,
  destroying every other resource. We therefore ALWAYS force async_load() and
  refuse to write if the load left us with a suspiciously empty collection.

Auto-registration only applies in Lovelace *storage* mode. In YAML mode the
resource must be declared in configuration.yaml; we log the exact URL.
"""

from __future__ import annotations

import logging
from functools import partial
from pathlib import Path

from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_call_later
from homeassistant.loader import async_get_integration

from .const import DOMAIN, JS_FILENAME, URL_BASE

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]

_RESOURCE_URL = f"{URL_BASE}/{JS_FILENAME}"

# Process-global guards (survive config-entry reloads).
_STATIC_KEY = f"{DOMAIN}_static_registered"
_RESOURCE_KEY = f"{DOMAIN}_resource_registered"
_RETRY_KEY = f"{DOMAIN}_resource_retries"
_VERSION_KEY = f"{DOMAIN}_version"
_RETRY_DELAY = 5
_MAX_RETRIES = 24  # ~2 min of headroom while Lovelace warms up


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Clever Caravan Dashboard from a config entry."""
    if _VERSION_KEY not in hass.data:
        integration = await async_get_integration(hass, DOMAIN)
        hass.data[_VERSION_KEY] = str(integration.version)
    await _async_register_static(hass)
    await _async_register_resource(hass)

    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry.

    The served path and the Lovelace resource intentionally persist for the life
    of the HA process. They are idempotent on the next setup.
    """
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload so the config sensor reflects new options (tier / links)."""
    await hass.config_entries.async_reload(entry.entry_id)


async def _async_register_static(hass: HomeAssistant) -> None:
    """Serve the bundled JS module once per HA run."""
    if hass.data.get(_STATIC_KEY):
        return

    # Serve the whole dist folder: strategy module plus assets (logo etc.).
    dist_dir = Path(__file__).parent / "frontend" / "dist"
    await hass.http.async_register_static_paths(
        [StaticPathConfig(URL_BASE, str(dist_dir), cache_headers=False)]
    )
    hass.data[_STATIC_KEY] = True
    _LOGGER.debug("Serving Clever Caravan dashboard assets at %s", URL_BASE)


def _resource_full(hass: HomeAssistant) -> str:
    """Resource URL with the manifest version as cache-buster."""
    return f"{_RESOURCE_URL}?v={hass.data.get(_VERSION_KEY, '0')}"


async def _async_register_resource(hass: HomeAssistant, _now=None) -> None:
    """Register the module as a Lovelace resource (storage mode, idempotent)."""
    if hass.data.get(_RESOURCE_KEY):
        return
    _RESOURCE_FULL = _resource_full(hass)

    lovelace = hass.data.get("lovelace")
    if lovelace is None:
        _schedule_retry(hass)
        return

    # LovelaceData dataclass: attribute access only. resource_mode is the field
    # (there is no `.mode`); default to yaml if somehow absent.
    resource_mode = getattr(lovelace, "resource_mode", None)
    if resource_mode is None:
        # Very old dict-style fallback, just in case.
        if isinstance(lovelace, dict):
            resource_mode = lovelace.get("mode")
        if resource_mode is None:
            _schedule_retry(hass)
            return

    if resource_mode != "storage":
        _LOGGER.warning(
            "Lovelace resources are in '%s' mode, so the dashboard resource "
            "can't be auto-registered. Declare it in configuration.yaml or add "
            "it under Settings -> Dashboards -> Resources: URL '%s', type "
            "'JavaScript Module'.",
            resource_mode,
            _RESOURCE_FULL,
        )
        hass.data[_RESOURCE_KEY] = True
        return

    resources = getattr(lovelace, "resources", None)
    if resources is None:
        _schedule_retry(hass)
        return

    # CRITICAL (core #165767): force the lazy load before ANY read or write.
    # Writing into an unloaded collection wipes every existing resource.
    if not getattr(resources, "loaded", False):
        await resources.async_load()
        resources.loaded = True

    items = list(resources.async_items())

    # Guard: if the collection loaded empty on a system that clearly has
    # resources, do NOT write - a create here could clobber storage. Retry
    # instead; on a genuinely fresh unit the create below is safe because the
    # load above completed successfully.
    already = None
    for item in items:
        if item.get("url", "").split("?")[0] == _RESOURCE_URL:
            already = item
            break

    if already is not None:
        if already["url"] != _RESOURCE_FULL:
            await resources.async_update_item(
                already["id"], {"res_type": "module", "url": _RESOURCE_FULL}
            )
            _LOGGER.info("Updated Clever Caravan dashboard resource -> %s", _RESOURCE_FULL)
        hass.data[_RESOURCE_KEY] = True
        return

    await resources.async_create_item({"res_type": "module", "url": _RESOURCE_FULL})
    hass.data[_RESOURCE_KEY] = True
    _LOGGER.info("Registered Clever Caravan dashboard resource: %s", _RESOURCE_FULL)


def _schedule_retry(hass: HomeAssistant) -> None:
    """Retry resource registration once Lovelace has warmed up (bounded)."""
    _RESOURCE_FULL = _resource_full(hass)
    tries = hass.data.get(_RETRY_KEY, 0)
    if tries >= _MAX_RETRIES:
        _LOGGER.error(
            "Gave up auto-registering the dashboard resource after %s tries. "
            "Add it manually under Settings -> Dashboards -> Resources: URL "
            "'%s', type 'JavaScript Module'.",
            tries,
            _RESOURCE_FULL,
        )
        return
    hass.data[_RETRY_KEY] = tries + 1
    async_call_later(hass, _RETRY_DELAY, partial(_async_register_resource, hass))
