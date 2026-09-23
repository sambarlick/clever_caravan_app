# Copyright (c) 2026 Samuel Myers. All rights reserved.
# Proprietary - see LICENSE. Unauthorised use, copying, or distribution prohibited.

"""Maintenance buttons for Clever Caravan: Waymote (published over MQTT)."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components import mqtt
from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import WaymoteConfigEntry
from .entity import WaymoteBridgeEntity


@dataclass(frozen=True, kw_only=True)
class WaymoteButtonSpec:
    key: str
    name: str
    topic: str
    payload: str
    icon: str


BUTTONS: tuple[WaymoteButtonSpec, ...] = (
    WaymoteButtonSpec(key="can_reset", name="CAN Reset",
                      topic="Waymote/CAN/Reset", payload="RESET_NOW", icon="mdi:refresh"),
    WaymoteButtonSpec(key="restart_bridge", name="Restart Bridge",
                      topic="Waymote/System/RestartBridge", payload="RESTART_NOW", icon="mdi:restart"),
    WaymoteButtonSpec(key="reboot_waymote", name="Reboot Waymote",
                      topic="Waymote/System/Reboot", payload="REBOOT_NOW", icon="mdi:restart-alert"),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WaymoteConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(WaymoteButton(coordinator, spec) for spec in BUTTONS)


class WaymoteButton(WaymoteBridgeEntity, ButtonEntity):
    def __init__(self, coordinator, spec: WaymoteButtonSpec) -> None:
        super().__init__(
            coordinator,
            key=spec.key,
            name=spec.name,
            icon=spec.icon,
            entity_category=EntityCategory.CONFIG,
        )
        self._spec = spec

    async def async_press(self) -> None:
        await mqtt.async_publish(
            self.hass, self._spec.topic, self._spec.payload, qos=1, retain=False
        )
