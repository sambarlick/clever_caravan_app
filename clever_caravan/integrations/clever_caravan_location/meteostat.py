# Copyright (c) 2026 Samuel Myers. All rights reserved.
# Proprietary - see LICENSE. Unauthorised use, copying, or distribution prohibited.

"""Meteostat climate normals client.

Fetches 30-year monthly climate normals (1991-2020) from RapidAPI's
Meteostat point/normals endpoint. Returns the current calendar month's
record only — the integration consumer doesn't need the full 12-row
table on a dashboard.

Requires a RapidAPI key. Free tier ~500 requests/month is comfortably
sufficient given SAL-cached lookup pattern.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
import logging

import aiohttp

from .const import (
    METEOSTAT_HOST,
    METEOSTAT_KEY,
    METEOSTAT_TIMEOUT_S,
    METEOSTAT_URL,
)

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class MeteostatResult:
    """Climate normals for a single month at a coordinate."""

    mean_max_c: float | None
    mean_min_c: float | None
    mean_temp_c: float | None
    monthly_rainfall_mm: float | None
    month: int  # 1-12, the month this snapshot represents
    raw_data: list | None  # full 12-month array for templating


async def fetch_climate_normals(
    session: aiohttp.ClientSession,
    latitude: float,
    longitude: float,
    elevation: float | None = None,
) -> MeteostatResult | None:
    """Fetch monthly climate normals for a coordinate.

    Returns None on any failure — caller decides whether to retain
    previous data or null out the sensors.
    """
    if not METEOSTAT_KEY or METEOSTAT_KEY == "REPLACE_ME":
        _LOGGER.warning("Meteostat API key not configured")
        return None

    params = {
        "lat": f"{latitude:.6f}",
        "lon": f"{longitude:.6f}",
        "start": "1991",
        "end": "2020",
    }
    if elevation is not None:
        params["alt"] = str(int(round(elevation)))

    headers = {
        "x-rapidapi-host": METEOSTAT_HOST,
        "x-rapidapi-key": METEOSTAT_KEY,
    }

    try:
        async with asyncio.timeout(METEOSTAT_TIMEOUT_S):
            async with session.get(
                METEOSTAT_URL, params=params, headers=headers
            ) as resp:
                if resp.status != 200:
                    _LOGGER.warning(
                        "Meteostat returned HTTP %s for %f,%f",
                        resp.status, latitude, longitude,
                    )
                    return None
                data = await resp.json()
    except (aiohttp.ClientError, TimeoutError) as exc:
        _LOGGER.warning("Meteostat request failed: %s", exc)
        return None

    rows = data.get("data") if isinstance(data, dict) else None
    if not rows or not isinstance(rows, list):
        return None

    # Pull the row for the current calendar month (1-12 in Meteostat's
    # output). Not all locations have all 12 months — be defensive.
    current_month = datetime.now().month
    month_row: dict | None = None
    for row in rows:
        if isinstance(row, dict) and row.get("month") == current_month:
            month_row = row
            break

    if month_row is None:
        # Fall back to indexing if 'month' field is missing
        if len(rows) >= current_month and isinstance(rows[current_month - 1], dict):
            month_row = rows[current_month - 1]
        else:
            return None

    def _f(key: str) -> float | None:
        v = month_row.get(key)
        if v is None:
            return None
        try:
            return round(float(v), 1)
        except (ValueError, TypeError):
            return None

    return MeteostatResult(
        mean_max_c=_f("tmax"),
        mean_min_c=_f("tmin"),
        mean_temp_c=_f("tavg"),
        monthly_rainfall_mm=_f("prcp"),
        month=current_month,
        raw_data=rows,
    )
