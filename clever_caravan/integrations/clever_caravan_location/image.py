# Copyright (c) 2026 Samuel Myers. All rights reserved.
# Proprietary - see LICENSE. Unauthorised use, copying, or distribution prohibited.

"""Image platform: serves the Wikipedia thumbnail via HA's image proxy.

This avoids writing files to /config/www/ — HA caches and serves the
remote image directly. Dashboard markdown can reference the image
entity via its entity_picture attribute.

The image is fetched with the integration's own User-Agent rather than
HA's default httpx client: Wikimedia rate-limits generic client UAs
(429 Too Many Requests) on upload.wikimedia.org.
"""

from __future__ import annotations

import asyncio
import logging

import aiohttp

from homeassistant.components.image import ImageEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import DOMAIN, SIGNAL_WIKI_UPDATED, USER_AGENT, WIKI_TIMEOUT_S
from .coordinator import CaravanLocationCoordinator, get_coordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = get_coordinator(hass, entry.entry_id)
    async_add_entities([CaravanWikipediaImage(hass, coordinator, entry)])


class CaravanWikipediaImage(ImageEntity):
    """Image entity backed by Wikipedia's lead image URL."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "wikipedia_image"
    _attr_content_type = "image/jpeg"

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: CaravanLocationCoordinator,
        entry: ConfigEntry,
    ) -> None:
        super().__init__(hass)
        self.coordinator = coordinator
        self._attr_unique_id = f"{entry.entry_id}_wikipedia_image"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Clever Caravan",
            manufacturer="Clever Caravan",
            model="Location",
        )
        self._current_url: str | None = None
        self._image_bytes: bytes | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_WIKI_UPDATED, self._handle_update
            )
        )
        # Initial population if we already have data
        self._refresh_url()

    @callback
    def _handle_update(self) -> None:
        self._refresh_url()
        self.async_write_ha_state()

    def _refresh_url(self) -> None:
        wiki = self.coordinator.wiki_data
        new_url = wiki.image_url if wiki else None
        if new_url != self._current_url:
            self._current_url = new_url
            self._image_bytes = None  # invalidate cache
            self._attr_image_last_updated = dt_util.utcnow()

    async def async_image(self) -> bytes | None:
        """Fetch (once per URL) with our own User-Agent, then serve cached bytes."""
        url = self._current_url
        if url is None:
            return None
        if self._image_bytes is not None:
            return self._image_bytes

        session = async_get_clientsession(self.hass)
        try:
            async with asyncio.timeout(WIKI_TIMEOUT_S):
                async with session.get(
                    url, headers={"User-Agent": USER_AGENT}
                ) as resp:
                    if resp.status != 200:
                        _LOGGER.warning(
                            "Wikipedia image fetch returned HTTP %s for %s",
                            resp.status,
                            url,
                        )
                        return None
                    content_type = resp.headers.get(
                        "Content-Type", "image/jpeg"
                    ).split(";")[0]
                    data = await resp.read()
        except (aiohttp.ClientError, TimeoutError) as exc:
            _LOGGER.warning("Wikipedia image fetch failed for %s: %s", url, exc)
            return None

        # Guard against the URL changing mid-fetch
        if url != self._current_url:
            return None

        self._attr_content_type = content_type
        self._image_bytes = data
        return data

    @property
    def available(self) -> bool:
        return self._current_url is not None
