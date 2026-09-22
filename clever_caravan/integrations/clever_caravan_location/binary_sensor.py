# Copyright (c) 2026 Samuel Myers. All rights reserved.
# Proprietary - see LICENSE. Unauthorised use, copying, or distribution prohibited.

"""Binary sensor: cc_gps_healthy."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_SOURCE, DOMAIN, SIGNAL_LOCATION_UPDATED, SOURCE_USB
from .coordinator import CaravanLocationCoordinator, get_coordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = get_coordinator(hass, entry.entry_id)
    is_usb = entry.data.get(CONF_SOURCE) == SOURCE_USB
    async_add_entities([GpsHealthySensor(coordinator, entry, enabled=is_usb)])


class GpsHealthySensor(BinarySensorEntity):
    """True when GPS has a recent valid fix."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "gps_healthy"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(
        self,
        coordinator: CaravanLocationCoordinator,
        entry: ConfigEntry,
        enabled: bool = True,
    ) -> None:
        self.coordinator = coordinator
        self._attr_unique_id = f"{entry.entry_id}_gps_healthy"
        self._attr_entity_registry_enabled_default = enabled
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Clever Caravan",
            manufacturer="Clever Caravan",
            model="Location",
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_LOCATION_UPDATED, self._handle_update
            )
        )

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()

    @property
    def is_on(self) -> bool:
        return self.coordinator.is_healthy
