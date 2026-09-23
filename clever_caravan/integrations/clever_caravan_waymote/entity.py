# Copyright (c) 2026 Samuel Myers. All rights reserved.
# Proprietary - see LICENSE. Unauthorised use, copying, or distribution prohibited.

"""Shared base for Waymote output entities.

Every output is an ON/OFF relay underneath. This base owns the common MQTT
plumbing - command publish, optimistic state, status self-correction, and
availability - so the per-domain classes (switch/light/fan) stay tiny wrappers
that only differ in HA entity type.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components import mqtt
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo

from .const import AVAILABILITY_TOPIC, CONTROL_TOPIC, DOMAIN, STATUS_TOPIC

_LOGGER = logging.getLogger(__name__)


class WaymoteOutputEntity:
    """Common MQTT on/off behaviour for a single Waymote output channel."""

    # has_entity_name = False keeps the entity_id and friendly name as just the
    # output name (e.g. light.ambient_lights), not prefixed by the device.
    _attr_has_entity_name = False
    _attr_should_poll = False

    def __init__(self, coordinator, channel: int) -> None:
        super().__init__()
        self._coordinator = coordinator
        self._channel = channel
        base = coordinator.entry.unique_id or coordinator.entry.entry_id
        self._attr_unique_id = f"{base}_output_{channel}"
        self._command_topic = CONTROL_TOPIC.format(n=channel)
        self._status_topic = STATUS_TOPIC.format(n=channel)
        self._is_on = False
        self._available = True

        cfg = self._cfg()
        self._attr_name = cfg.get("name", f"Output {channel}")
        self._attr_icon = cfg.get("icon")
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, base)})

    def _cfg(self) -> dict[str, Any]:
        outputs = (self._coordinator.data or {}).get("outputs", {})
        return outputs.get(str(self._channel), {})

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        @callback
        def _status_received(msg: mqtt.ReceiveMessage) -> None:
            payload = msg.payload.strip().upper()
            if payload in ("ON", "OFF"):
                self._is_on = payload == "ON"
                self.async_write_ha_state()

        @callback
        def _availability_received(msg: mqtt.ReceiveMessage) -> None:
            self._available = msg.payload.strip() == "online"
            self.async_write_ha_state()

        self.async_on_remove(
            await mqtt.async_subscribe(self.hass, self._status_topic, _status_received)
        )
        self.async_on_remove(
            await mqtt.async_subscribe(
                self.hass, AVAILABILITY_TOPIC, _availability_received
            )
        )

    @property
    def available(self) -> bool:
        return self._available

    async def _async_set(self, turn_on: bool) -> None:
        await mqtt.async_publish(
            self.hass,
            self._command_topic,
            "ON" if turn_on else "OFF",
            qos=1,
            retain=True,
        )
        self._is_on = turn_on
        self.async_write_ha_state()


class WaymoteBridgeEntity:
    """Base for fixed, bridge-level entities (not tied to an output channel).

    Handles device attachment, an optional read state topic, and availability
    tracking from the bridge's own online/offline topic.
    """

    _attr_has_entity_name = False
    _attr_should_poll = False

    def __init__(
        self,
        coordinator,
        *,
        key: str,
        name: str,
        state_topic: str | None = None,
        icon: str | None = None,
        entity_category=None,
        device_class=None,
        use_bridge_availability: bool = True,
    ) -> None:
        super().__init__()
        self._coordinator = coordinator
        base = coordinator.entry.unique_id or coordinator.entry.entry_id
        self._attr_unique_id = f"{base}_{key}"
        self._attr_name = name
        if icon:
            self._attr_icon = icon
        if entity_category is not None:
            self._attr_entity_category = entity_category
        if device_class is not None:
            self._attr_device_class = device_class
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, base)})
        self._state_topic = state_topic
        self._use_bridge_availability = use_bridge_availability
        self._payload: str | None = None
        self._bridge_online = True

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        if self._state_topic:

            @callback
            def _state_received(msg: mqtt.ReceiveMessage) -> None:
                self._payload = msg.payload.strip()
                self.async_write_ha_state()

            self.async_on_remove(
                await mqtt.async_subscribe(
                    self.hass, self._state_topic, _state_received
                )
            )

        if self._use_bridge_availability:

            @callback
            def _availability_received(msg: mqtt.ReceiveMessage) -> None:
                self._bridge_online = msg.payload.strip() == "online"
                self.async_write_ha_state()

            self.async_on_remove(
                await mqtt.async_subscribe(
                    self.hass, AVAILABILITY_TOPIC, _availability_received
                )
            )

    @property
    def available(self) -> bool:
        return self._bridge_online if self._use_bridge_availability else True
