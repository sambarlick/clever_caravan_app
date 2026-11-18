# Copyright (c) 2026 Samuel Myers. All rights reserved.
# Proprietary - see LICENSE. Unauthorised use, copying, or distribution prohibited.

"""Slim entity list for the dashboard strategy.

`config/entity_registry/list` returns every entity with every field (~780 KB
on a 1,100-entity rig). Over a remote link that alone added ~1.8 s to every
dashboard load. This returns only the entities the dashboard can use, with
only the fields it reads, and leaves out empty fields.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN

WS_ENTITIES = f"{DOMAIN}/entities"


@callback
def async_register_websocket(hass: HomeAssistant) -> None:
    """Register the websocket command (idempotent per HA run)."""
    key = f"{DOMAIN}_ws_registered"
    if hass.data.get(key):
        return
    websocket_api.async_register_command(hass, ws_entities)
    hass.data[key] = True


@websocket_api.websocket_command({vol.Required("type"): WS_ENTITIES})
@callback
def ws_entities(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return the entities the dashboard can show, with only the fields it reads."""
    out: list[dict[str, Any]] = []
    for e in er.async_get(hass).entities.values():
        own = e.platform == DOMAIN
        # The strategy never shows these, so don't send them. Our own config
        # sensor is diagnostic but must be sent: the strategy reads it.
        if e.disabled_by or e.hidden_by or (e.entity_category and not own):
            continue
        row: dict[str, Any] = {"entity_id": e.entity_id, "platform": e.platform}
        if e.unique_id:
            row["unique_id"] = e.unique_id
        if e.device_id:
            row["device_id"] = e.device_id
        if e.area_id:
            row["area_id"] = e.area_id
        if e.labels:
            row["labels"] = sorted(e.labels)
        if e.translation_key:
            row["translation_key"] = e.translation_key
        if own and e.entity_category:
            row["entity_category"] = e.entity_category.value
        out.append(row)
    connection.send_result(msg["id"], out)
