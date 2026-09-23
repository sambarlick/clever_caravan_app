# Copyright (c) 2026 Samuel Myers. All rights reserved.
# Proprietary - see LICENSE. Unauthorised use, copying, or distribution prohibited.

"""Switch platform for Clever Caravan: Power (Cerbo GX relays)."""
from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_RELAY_NAME, DOMAIN, RELAY_NAMES
from .entity import CcpEntity, async_setup_discovery


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]

    @callback
    def _factory(vdef, instance: str, extra) -> None:
        async_add_entities([CcpRelaySwitch(data, vdef, instance, extra["relay"])])

    async_setup_discovery(hass, entry, data, "switch", _factory)


class CcpRelaySwitch(CcpEntity, SwitchEntity):
    """A Cerbo GX relay."""

    def __init__(self, data, vdef, instance: str, relay: str) -> None:
        super().__init__(data, vdef, instance, f"relay_{relay}")
        self._relay = relay
        default = RELAY_NAMES.get(int(relay), f"Relay {relay}")
        self._attr_name = data.entry.options.get(
            CONF_RELAY_NAME.format(relay), default
        )
        self._attr_unique_id = f"{self._hub.portal_id}_relay_{relay}"
        self._path = f"Relay/{relay}/State"
        self._apply_value(self._hub.get("system", instance, self._path))

    @callback
    def _apply_value(self, value) -> None:
        try:
            self._attr_is_on = int(value) == 1
        except (TypeError, ValueError):
            self._attr_is_on = None

    async def async_turn_on(self, **kwargs) -> None:
        self._hub.set_value("system", self._instance, self._path, 1)

    async def async_turn_off(self, **kwargs) -> None:
        self._hub.set_value("system", self._instance, self._path, 0)
