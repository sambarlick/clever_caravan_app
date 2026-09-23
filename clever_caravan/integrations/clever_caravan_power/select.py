# Copyright (c) 2026 Samuel Myers. All rights reserved.
# Proprietary - see LICENSE. Unauthorised use, copying, or distribution prohibited.

"""Select platform for Clever Caravan: Power (inverter mode)."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import CcpEntity, async_setup_discovery


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]

    @callback
    def _factory(vdef, instance: str, extra) -> None:
        async_add_entities([CcpSelect(data, vdef, instance)])

    async_setup_discovery(hass, entry, data, "select", _factory)


class CcpSelect(CcpEntity, SelectEntity):
    """A mapped Venus enum exposed as a select."""

    def __init__(self, data, vdef, instance: str) -> None:
        super().__init__(data, vdef, instance, f"{vdef.key}_{instance}")
        self._map = vdef.options_map
        self._reverse = {v: k for k, v in vdef.options_map.items()}
        self._attr_options = list(vdef.options_map.values())
        self._apply_value(self._hub.get(vdef.service, instance, vdef.path))

    @callback
    def _apply_value(self, value) -> None:
        try:
            self._attr_current_option = self._map.get(int(value))
        except (TypeError, ValueError):
            self._attr_current_option = None

    async def async_select_option(self, option: str) -> None:
        self._hub.set_value(
            self._def.service, self._instance, self._def.path, self._reverse[option]
        )
