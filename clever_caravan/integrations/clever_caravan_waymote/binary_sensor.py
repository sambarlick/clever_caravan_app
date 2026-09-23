# Copyright (c) 2026 Samuel Myers. All rights reserved.
# Proprietary - see LICENSE. Unauthorised use, copying, or distribution prohibited.

"""Connectivity binary sensors for Clever Caravan: Waymote."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import WaymoteConfigEntry
from .entity import WaymoteBridgeEntity


@dataclass(frozen=True, kw_only=True)
class WaymoteBinarySpec:
    key: str
    name: str
    topic: str
    icon: str
    # The Bridge Online sensor reports the same topic it would use for its own
    # availability, so it must stay available to show 'offline'.
    use_bridge_availability: bool = True


BINARY_SENSORS: tuple[WaymoteBinarySpec, ...] = (
    WaymoteBinarySpec(key="bridge_online", name="Bridge Online",
                      topic="Waymote/Bridge/Availability", icon="mdi:lan-connect",
                      use_bridge_availability=False),
    WaymoteBinarySpec(key="can_online", name="CAN Link",
                      topic="Waymote/CAN/Availability", icon="mdi:serial-port"),
    WaymoteBinarySpec(key="waymote_online", name="Controller Online",
                      topic="Waymote/Status/Availability", icon="mdi:check-network"),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WaymoteConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    async_add_entities(
        WaymoteBinarySensor(coordinator, spec) for spec in BINARY_SENSORS
    )


class WaymoteBinarySensor(WaymoteBridgeEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, coordinator, spec: WaymoteBinarySpec) -> None:
        super().__init__(
            coordinator,
            key=spec.key,
            name=spec.name,
            state_topic=spec.topic,
            icon=spec.icon,
            entity_category=EntityCategory.DIAGNOSTIC,
            use_bridge_availability=spec.use_bridge_availability,
        )

    @property
    def is_on(self) -> bool | None:
        if self._payload is None:
            return None
        return self._payload == "online"
