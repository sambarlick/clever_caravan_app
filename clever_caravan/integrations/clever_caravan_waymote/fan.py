# Copyright (c) 2026 Samuel Myers. All rights reserved.
# Proprietary - see LICENSE. Unauthorised use, copying, or distribution prohibited.

"""Fan platform for Clever Caravan: Waymote (outputs mapped to 'fan')."""

from __future__ import annotations

from typing import Any

from homeassistant.components.fan import FanEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import WaymoteConfigEntry
from .entity import WaymoteOutputEntity
from .switch import _channels_for_domain


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WaymoteConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        WaymoteOutputFan(coordinator, ch)
        for ch in _channels_for_domain(entry, "fan")
    )


class WaymoteOutputFan(WaymoteOutputEntity, FanEntity):
    @property
    def is_on(self) -> bool:
        return self._is_on

    async def async_turn_on(
        self,
        percentage: int | None = None,
        preset_mode: str | None = None,
        **kwargs: Any,
    ) -> None:
        await self._async_set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_set(False)
