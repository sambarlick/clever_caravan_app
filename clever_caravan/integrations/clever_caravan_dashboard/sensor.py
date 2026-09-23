# Copyright (c) 2026 Samuel Myers. All rights reserved.
# Proprietary - see LICENSE. Unauthorised use, copying, or distribution prohibited.

"""Config sensor: the frontend-readable channel for tier + role map.

The strategy resolves this entity by platform + translation_key (rename-proof),
then reads `tier`, `role_map`, and `owned_platforms` from its attributes.

Recorder note: the state rarely changes (only on options update), so churn is
minimal, but if you want it out of history entirely, exclude
`sensor.*_config` (entity_category: diagnostic) in your recorder config.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_EXTRA_PLATFORMS,
    CONF_ROLE_MAP,
    CONF_TIER,
    DOMAIN,
    OWNED_PLATFORMS,
    TIER_BASE,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the config sensor."""
    async_add_entities([CleverCaravanConfigSensor(entry)])


class CleverCaravanConfigSensor(SensorEntity):
    """Exposes dashboard tier + role map for the frontend strategy to read."""

    _attr_has_entity_name = True
    _attr_translation_key = "config"
    _attr_icon = "mdi:cog"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_should_poll = False

    def __init__(self, entry: ConfigEntry) -> None:
        """Initialize the config sensor."""
        self._entry = entry
        # Stable unique_id; the strategy matches on translation_key, not this.
        self._attr_unique_id = f"{entry.entry_id}_config"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Clever Caravan Dashboard",
            "manufacturer": "Clever Caravan",
        }

    @property
    def native_value(self) -> str:
        """State is the active tier (handy at-a-glance in Dev Tools)."""
        return self._entry.options.get(CONF_TIER, TIER_BASE)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Everything the strategy needs to build the dashboard."""
        return {
            "tier": self._entry.options.get(CONF_TIER, TIER_BASE),
            "role_map": self._entry.options.get(CONF_ROLE_MAP, {}),
            "owned_platforms": OWNED_PLATFORMS,
            "extra_platforms": self._entry.options.get(CONF_EXTRA_PLATFORMS, []),
        }
