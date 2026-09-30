# Copyright (c) 2026 Samuel Myers. All rights reserved.
# Proprietary - see LICENSE. Unauthorised use, copying, or distribution prohibited.

"""Switch platform for Clever Caravan: Waymote (outputs mapped to 'switch')."""

from __future__ import annotations

from typing import Any

from homeassistant.components import mqtt
from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import WaymoteConfigEntry
from .const import (
    COMBO_AWNING,
    CONF_COMBOS,
    CONF_DOMAINS,
    CONTROL_TOPIC,
    DEFAULT_DOMAIN,
    get_combos,
    STATUS_TOPIC,
    channels_in_combos,
)
from .entity import WaymoteBridgeEntity, WaymoteOutputEntity

AUTORECOVERY_TOPIC = "Waymote/CAN/AutoRecovery"


def _channels_for_domain(entry: WaymoteConfigEntry, target: str) -> list[int]:
    coordinator = entry.runtime_data
    outputs = (coordinator.data or {}).get("outputs", {})
    domains = entry.data.get(CONF_DOMAINS, {})
    # Channels used by a combined device are owned by that device, not by a
    # standalone entity.
    combined = channels_in_combos(get_combos(entry))
    result = []
    for key, cfg in outputs.items():
        if not (str(key).isdigit() and isinstance(cfg, dict) and cfg.get("enabled")):
            continue
        channel = int(key)
        if channel in combined:
            continue
        if domains.get(str(channel), DEFAULT_DOMAIN) == target:
            result.append(channel)
    return sorted(result)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WaymoteConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    entities: list[SwitchEntity] = [
        WaymoteOutputSwitch(coordinator, ch)
        for ch in _channels_for_domain(entry, "switch")
    ]
    for combo in get_combos(entry):
        if combo.get("type") == COMBO_AWNING:
            entities.append(
                WaymoteAwningPowerSwitch(coordinator, combo, int(combo["power"]))
            )
    entities.append(WaymoteAutoRecoverySwitch(coordinator))
    async_add_entities(entities)


class WaymoteOutputSwitch(WaymoteOutputEntity, SwitchEntity):
    @property
    def is_on(self) -> bool:
        return self._is_on

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_set(False)


class WaymoteAutoRecoverySwitch(WaymoteBridgeEntity, SwitchEntity):
    """CAN auto-recovery toggle. Real state (the bridge echoes it retained)."""

    def __init__(self, coordinator) -> None:
        super().__init__(
            coordinator,
            key="can_autorecovery",
            name="CAN Auto Recovery",
            state_topic=AUTORECOVERY_TOPIC,
            icon="mdi:refresh-auto",
            entity_category=EntityCategory.CONFIG,
        )

    @property
    def is_on(self) -> bool | None:
        if self._payload is None:
            return None
        return self._payload.upper() == "ON"

    async def async_turn_on(self, **kwargs: Any) -> None:
        await mqtt.async_publish(self.hass, AUTORECOVERY_TOPIC, "ON", qos=1, retain=False)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await mqtt.async_publish(self.hass, AUTORECOVERY_TOPIC, "OFF", qos=1, retain=False)


class WaymoteAwningPowerSwitch(WaymoteOutputEntity, SwitchEntity):
    """The Power relay of an awning, shown on its own so it can be seen and set."""

    def __init__(self, coordinator, combo: dict, channel: int) -> None:
        super().__init__(coordinator, channel)
        name = combo.get("name") or f"Awning {channel}"
        self._attr_name = f"{name} Power"
        self._attr_icon = "mdi:power-plug"

    @property
    def is_on(self) -> bool:
        return self._is_on

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_set(False)
