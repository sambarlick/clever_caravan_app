# Copyright (c) 2026 Samuel Myers. All rights reserved.
# Proprietary - see LICENSE. Unauthorised use, copying, or distribution prohibited.

"""Coordinator that polls the Waymote bridge's /api/config endpoint."""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    API_CONFIG_PATH,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    REQUEST_TIMEOUT,
)

_LOGGER = logging.getLogger(__name__)


class WaymoteCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Fetches and caches the Waymote config.json over the LAN.

    The bridge is the single source of truth. This coordinator reads it; writing
    back (renaming/enabling outputs) is done via POST /api/config in later stages.
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )
        self.entry = entry
        self._session = async_get_clientsession(hass)
        host = entry.data[CONF_HOST]
        port = entry.data.get(CONF_PORT, DEFAULT_PORT)
        self.base_url = f"http://{host}:{port}"
        self._config_url = f"{self.base_url}{API_CONFIG_PATH}"

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            async with asyncio.timeout(REQUEST_TIMEOUT):
                resp = await self._session.get(self._config_url)
                resp.raise_for_status()
                data = await resp.json(content_type=None)
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            raise UpdateFailed(
                f"Error reaching Waymote at {self._config_url}: {err}"
            ) from err

        if not isinstance(data, dict) or "outputs" not in data:
            raise UpdateFailed("Unexpected response from Waymote /api/config")

        return data
