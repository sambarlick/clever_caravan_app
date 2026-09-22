# Copyright (c) 2026 Samuel Myers. All rights reserved.
# Proprietary - see LICENSE. Unauthorised use, copying, or distribution prohibited.

"""Button: cc_update — manually refresh all location action layers."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import CaravanLocationCoordinator, get_coordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = get_coordinator(hass, entry.entry_id)
    async_add_entities([UpdateButton(coordinator, entry)])


class UpdateButton(ButtonEntity):
    """Force-refresh all action layers against the latest fix."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "update"
    _attr_icon = "mdi:map-marker-radius"

    def __init__(
        self,
        coordinator: CaravanLocationCoordinator,
        entry: ConfigEntry,
    ) -> None:
        self.coordinator = coordinator
        self._attr_unique_id = f"{entry.entry_id}_update"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Clever Caravan",
            manufacturer="Clever Caravan",
            model="Location",
        )

    async def async_press(self) -> None:
        await self.coordinator.async_force_update()
