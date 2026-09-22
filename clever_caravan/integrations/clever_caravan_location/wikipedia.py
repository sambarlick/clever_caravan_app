# Copyright (c) 2026 Samuel Myers. All rights reserved.
# Proprietary - see LICENSE. Unauthorised use, copying, or distribution prohibited.

"""Wikipedia REST summary client.

Fetches the article summary + thumbnail image URL for a place.
Tries '{city}, {state}' first (disambiguated), falls back to bare
'{city}' if that 404s — matches the long-running REST sensor logic
from the YAML era.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging

import aiohttp

from .const import WIKI_TIMEOUT_S, WIKI_URL_BASE, WIKI_USER_AGENT

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class WikiResult:
    """Wikipedia summary fields used on the dashboard."""

    title: str | None
    extract: str | None  # the summary paragraph
    image_url: str | None  # image URL (full-res preferred, thumbnail fallback), or None
    article_url: str | None  # link to the live article


def _slug(text: str) -> str:
    """Wikipedia URL-escape pattern matching the REST endpoint."""
    return text.strip().replace(" ", "_")


async def _fetch_one(
    session: aiohttp.ClientSession,
    title_slug: str,
) -> dict | None:
    """Fetch a single summary; returns None on any non-200."""
    url = f"{WIKI_URL_BASE}/{title_slug}"
    headers = {"User-Agent": WIKI_USER_AGENT}

    try:
        async with asyncio.timeout(WIKI_TIMEOUT_S):
            async with session.get(url, headers=headers) as resp:
                if resp.status != 200:
                    return None
                return await resp.json()
    except (aiohttp.ClientError, TimeoutError) as exc:
        _LOGGER.warning("Wikipedia request failed for %s: %s", title_slug, exc)
        return None


async def fetch_summary(
    session: aiohttp.ClientSession,
    city: str,
    state: str | None,
) -> WikiResult | None:
    """Fetch summary, trying disambiguated form first then bare city."""
    if not city or city in {"Unknown", "Waiting...", "unavailable", "unknown"}:
        return None

    candidates: list[str] = []
    if state:
        candidates.append(f"{_slug(city)},_{_slug(state)}")
    candidates.append(_slug(city))

    data: dict | None = None
    for slug in candidates:
        data = await _fetch_one(session, slug)
        if data:
            break

    if not data:
        return None

    # Prefer full-resolution originalimage; fall back to the smaller
    # thumbnail when a page has no originalimage block.
    image_url = None
    if isinstance(data.get("originalimage"), dict):
        image_url = data["originalimage"].get("source")
    if image_url is None and isinstance(data.get("thumbnail"), dict):
        image_url = data["thumbnail"].get("source")

    article_url = None
    content_urls = data.get("content_urls")
    if isinstance(content_urls, dict):
        desktop = content_urls.get("desktop")
        if isinstance(desktop, dict):
            article_url = desktop.get("page")

    return WikiResult(
        title=data.get("title"),
        extract=data.get("extract"),
        image_url=image_url,
        article_url=article_url,
    )
