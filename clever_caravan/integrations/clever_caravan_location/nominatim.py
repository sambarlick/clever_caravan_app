# Copyright (c) 2026 Samuel Myers. All rights reserved.
# Proprietary - see LICENSE. Unauthorised use, copying, or distribution prohibited.

"""Nominatim reverse-geocoding client.

Uses HA's shared aiohttp session and stdlib asyncio.timeout (Python 3.11+).
Respects OSM Nominatim usage policy: User-Agent identification, throttling
handled at the coordinator level, no aggressive retries on failure.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging

import aiohttp

from .const import NOMINATIM_TIMEOUT_S, NOMINATIM_URL, NOMINATIM_USER_AGENT

_LOGGER = logging.getLogger(__name__)


# Map full Australian state/territory names to their short codes.
# Nominatim returns "Queensland"; ABS/everyday usage prefers "QLD".
AU_STATE_SHORT: dict[str, str] = {
    "New South Wales": "NSW",
    "Victoria": "VIC",
    "Queensland": "QLD",
    "South Australia": "SA",
    "Western Australia": "WA",
    "Tasmania": "TAS",
    "Northern Territory": "NT",
    "Australian Capital Territory": "ACT",
}


@dataclass(frozen=True)
class GeocodeResult:
    """Best-effort fields extracted from Nominatim's response."""

    city: str | None
    state: str | None
    state_short: str | None
    country: str | None
    country_code: str | None
    postcode: str | None
    raw_address: dict | None


async def reverse_geocode(
    session: aiohttp.ClientSession,
    latitude: float,
    longitude: float,
) -> GeocodeResult | None:
    """Look up a place name for the given coordinates.

    Returns None on any failure — caller decides whether to retain
    last good result or null out the sensors.
    """
    params = {
        "lat": f"{latitude:.6f}",
        "lon": f"{longitude:.6f}",
        "format": "jsonv2",
        "zoom": "18",
        "addressdetails": "1",
    }
    headers = {"User-Agent": NOMINATIM_USER_AGENT}

    try:
        async with asyncio.timeout(NOMINATIM_TIMEOUT_S):
            async with session.get(
                NOMINATIM_URL, params=params, headers=headers
            ) as resp:
                if resp.status != 200:
                    _LOGGER.warning(
                        "Nominatim returned HTTP %s for %f,%f",
                        resp.status, latitude, longitude,
                    )
                    return None
                data = await resp.json()
    except (aiohttp.ClientError, TimeoutError) as exc:
        _LOGGER.warning("Nominatim request failed: %s", exc)
        return None

    address = data.get("address") if isinstance(data, dict) else None
    if not address:
        return None

    # Cascading fallback matching HA template logic exactly.
    # Prioritizes granular locations (suburb) before falling back to city/region.
    city = (
        address.get("isolated_dwelling")
        or address.get("farm")
        or address.get("neighbourhood")
        or address.get("suburb")
        or address.get("hamlet")
        or address.get("village")
        or address.get("town")
        or address.get("city_district")
        or address.get("city")
        or address.get("locality")
        or address.get("municipality")
        or address.get("county")
        or address.get("state_district")
        or address.get("region")
        or "Unknown"
    )

    state_full = address.get("state")
    # Try the full-name map first; fall back to ISO 3166-2 codes which
    # Nominatim returns as e.g. "AU-QLD" — strip the prefix.
    state_short = AU_STATE_SHORT.get(state_full) if state_full else None
    if not state_short:
        iso = address.get("ISO3166-2-lvl4")
        if isinstance(iso, str) and iso.startswith("AU-"):
            state_short = iso[3:]

    return GeocodeResult(
        city=city,
        state=state_full,
        state_short=state_short,
        country=address.get("country"),
        country_code=address.get("country_code"),
        postcode=address.get("postcode"),
        raw_address=address,
    )
