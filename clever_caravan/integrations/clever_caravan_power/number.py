# Copyright (c) 2026 Samuel Myers. All rights reserved.
# Proprietary - see LICENSE. Unauthorised use, copying, or distribution prohibited.

"""Number platform for Clever Caravan: Power (input current limit)."""
from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_CURRENT_LIMIT_MAX,
    CONF_CURRENT_LIMIT_MIN,
    DEFAULT_CURRENT_LIMIT_MAX,
    DEFAULT_CURRENT_LIMIT_MIN,
    DOMAIN,
)
from .entity import CcpEntity, async_setup_discovery


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]

    @callback
    def _factory(vdef, instance: str, extra) -> None:
        async_add_entities([CcpNumber(data, vdef, instance)])

    async_setup_discovery(hass, entry, data, "number", _factory)


class CcpNumber(CcpEntity, NumberEntity):
    """A writable Venus value exposed as a number."""

    _attr_mode = NumberMode.BOX

    def __init__(self, data, vdef, instance: str) -> None:
        super().__init__(data, vdef, instance, f"{vdef.key}_{instance}")
        options = data.entry.options
        if vdef.key == "input_current_limit":
            self._attr_native_min_value = options.get(
                CONF_CURRENT_LIMIT_MIN, DEFAULT_CURRENT_LIMIT_MIN
            )
            self._attr_native_max_value = options.get(
                CONF_CURRENT_LIMIT_MAX, DEFAULT_CURRENT_LIMIT_MAX
            )
        else:
            self._attr_native_min_value = getattr(vdef, "min", 0.0)
            self._attr_native_max_value = getattr(vdef, "max", 100.0)
        self._attr_native_step = vdef.step
        if vdef.unit:
            self._attr_native_unit_of_measurement = vdef.unit
        self._apply_value(self._hub.get(vdef.service, instance, vdef.path))

    @callback
    def _apply_value(self, value) -> None:
        try:
            self._attr_native_value = float(value)
        except (TypeError, ValueError):
            self._attr_native_value = None

    async def async_set_native_value(self, value: float) -> None:
        self._hub.set_value(self._def.service, self._instance, self._def.path, value)
