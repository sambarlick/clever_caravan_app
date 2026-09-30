# Copyright (c) 2026 Samuel Myers. All rights reserved.
# Proprietary - see LICENSE. Unauthorised use, copying, or distribution prohibited.

"""Light platform for Clever Caravan: Waymote.

Two kinds of light:
  - a single output mapped to 'light' (plain on/off relay)
  - a two-tone light combining two outputs (e.g. White + Ambient) into one
    entity, with the relays mutually exclusive
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components import mqtt
from homeassistant.components.light import ATTR_COLOR_TEMP_KELVIN, ATTR_EFFECT, ColorMode, LightEntity, LightEntityFeature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import WaymoteConfigEntry
from .const import (
    AVAILABILITY_TOPIC,
    COMBO_TWO_TONE,
    CONF_COMBOS,
    CONTROL_TOPIC,
    DOMAIN,
    STATUS_TOPIC,
    TONE_AMBIENT,
    TONE_AMBIENT_KELVIN,
    TONE_WHITE,
    TONE_WHITE_KELVIN,
)
from .entity import WaymoteOutputEntity
from .switch import _channels_for_domain

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: WaymoteConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    entities: list[LightEntity] = [
        WaymoteOutputLight(coordinator, ch)
        for ch in _channels_for_domain(entry, "light")
    ]
    for index, combo in enumerate(entry.data.get(CONF_COMBOS) or []):
        if combo.get("type") == COMBO_TWO_TONE:
            entities.append(WaymoteTwoToneLight(coordinator, combo, index))
    async_add_entities(entities)


class WaymoteOutputLight(WaymoteOutputEntity, LightEntity):
    _attr_color_mode = ColorMode.ONOFF
    _attr_supported_color_modes = {ColorMode.ONOFF}

    @property
    def is_on(self) -> bool:
        return self._is_on

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._async_set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._async_set(False)


class WaymoteTwoToneLight(LightEntity):
    """Two relays (White + Ambient) presented as one light.

    The relays are on/off only, so the two tones are represented as two colour
    temperatures. HA gets a normal colour-temp control that snaps between them,
    and an effect list naming the tones for a plain dropdown. The two relays are
    never on together: switching tone turns the other off first.
    """

    _attr_has_entity_name = False
    _attr_should_poll = False
    _attr_color_mode = ColorMode.COLOR_TEMP
    _attr_supported_color_modes = {ColorMode.COLOR_TEMP}
    _attr_supported_features = LightEntityFeature.EFFECT
    _attr_effect_list = [TONE_WHITE, TONE_AMBIENT]
    _attr_min_color_temp_kelvin = TONE_AMBIENT_KELVIN
    _attr_max_color_temp_kelvin = TONE_WHITE_KELVIN

    def __init__(self, coordinator, combo: dict, index: int) -> None:
        self._coordinator = coordinator
        self._white = int(combo["white"])
        self._ambient = int(combo["ambient"])
        base = coordinator.entry.unique_id or coordinator.entry.entry_id
        self._attr_unique_id = f"{base}_combo_{index}_{self._white}_{self._ambient}"
        self._attr_name = combo.get("name") or f"Light {self._white}/{self._ambient}"
        self._attr_icon = "mdi:wall-sconce-flat"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, base)})
        self._tone = TONE_WHITE
        self._is_on = False
        self._available = True

    # --- state -------------------------------------------------------------

    @property
    def is_on(self) -> bool:
        return self._is_on

    @property
    def available(self) -> bool:
        return self._available

    @property
    def effect(self) -> str:
        return self._tone

    @property
    def color_temp_kelvin(self) -> int:
        return TONE_WHITE_KELVIN if self._tone == TONE_WHITE else TONE_AMBIENT_KELVIN

    # --- mqtt --------------------------------------------------------------

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        def _make_status_handler(channel: int):
            @callback
            def _handler(msg: mqtt.ReceiveMessage) -> None:
                payload = msg.payload.strip().upper()
                if payload not in ("ON", "OFF"):
                    return
                if payload == "ON":
                    self._is_on = True
                    self._tone = TONE_WHITE if channel == self._white else TONE_AMBIENT
                elif self._tone == (TONE_WHITE if channel == self._white else TONE_AMBIENT):
                    # The relay currently representing the lit tone went off.
                    self._is_on = False
                self.async_write_ha_state()

            return _handler

        for channel in (self._white, self._ambient):
            self.async_on_remove(
                await mqtt.async_subscribe(
                    self.hass,
                    STATUS_TOPIC.format(n=channel),
                    _make_status_handler(channel),
                )
            )

        @callback
        def _availability(msg: mqtt.ReceiveMessage) -> None:
            self._available = msg.payload.strip() == "online"
            self.async_write_ha_state()

        self.async_on_remove(
            await mqtt.async_subscribe(self.hass, AVAILABILITY_TOPIC, _availability)
        )

    async def _publish(self, channel: int, on: bool) -> None:
        await mqtt.async_publish(
            self.hass, CONTROL_TOPIC.format(n=channel), "ON" if on else "OFF",
            qos=1, retain=True,
        )

    # --- commands ----------------------------------------------------------

    def _requested_tone(self, kwargs: dict[str, Any]) -> str:
        """Tone asked for: explicit effect, nearest colour temp, or unchanged."""
        effect = kwargs.get(ATTR_EFFECT)
        if effect in (TONE_WHITE, TONE_AMBIENT):
            return effect
        kelvin = kwargs.get(ATTR_COLOR_TEMP_KELVIN)
        if kelvin is not None:
            midpoint = (TONE_WHITE_KELVIN + TONE_AMBIENT_KELVIN) / 2
            return TONE_WHITE if kelvin >= midpoint else TONE_AMBIENT
        return self._tone

    async def async_turn_on(self, **kwargs: Any) -> None:
        tone = self._requested_tone(kwargs)
        wanted = self._white if tone == TONE_WHITE else self._ambient
        other = self._ambient if tone == TONE_WHITE else self._white
        # Other tone off first, so the two are never on together.
        await self._publish(other, False)
        await self._publish(wanted, True)
        self._tone = tone
        self._is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._publish(self._white, False)
        await self._publish(self._ambient, False)
        self._is_on = False
        self.async_write_ha_state()
