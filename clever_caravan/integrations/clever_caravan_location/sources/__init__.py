# Copyright (c) 2026 Samuel Myers. All rights reserved.
# Proprietary - see LICENSE. Unauthorised use, copying, or distribution prohibited.

"""Location source adapters."""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from ..const import CONF_SOURCE, SOURCE_ENTITY, SOURCE_MANUAL, SOURCE_USB
from .base import LocationFix, LocationSource


def build_source(hass: HomeAssistant, config: dict) -> LocationSource:
    """Construct the right adapter for the configured source type."""
    source_type = config[CONF_SOURCE]

    if source_type == SOURCE_USB:
        from .usb import UsbSource
        return UsbSource(hass, config)
    if source_type == SOURCE_ENTITY:
        from .entity_source import EntitySource
        return EntitySource(hass, config)
    if source_type == SOURCE_MANUAL:
        from .manual import ManualSource
        return ManualSource(hass, config)

    raise ValueError(f"Unknown source type: {source_type}")


__all__ = ["LocationFix", "LocationSource", "build_source"]
