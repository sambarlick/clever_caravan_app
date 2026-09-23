# Copyright (c) 2026 Samuel Myers. All rights reserved.
# Proprietary - see LICENSE. Unauthorised use, copying, or distribution prohibited.

"""Base entity for Clever Caravan: Power."""
from __future__ import annotations

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity, EntityCategory

from .const import (
    CONF_INSTANCE_NAME,
    DEV_GX,
    DEVICE_NAMES,
    DOMAIN,
    MANUFACTURER,
    NAMEABLE_SERVICES,
    SIGNAL_CONNECTION,
    SIGNAL_NEW_ENTITY,
    SIGNAL_VALUE,
)


def async_setup_discovery(hass, entry, data, platform: str, factory) -> None:
    """Wire a platform into discovery: live signals + replay of missed ones.

    Announcements can arrive (from the Cerbo's full publish) before a
    platform finishes loading, so after subscribing we replay everything
    already discovered. The data.claim() guard ensures each entity is
    created exactly once regardless of whether replay or a live signal
    gets there first.
    """
    from homeassistant.core import callback as _callback

    @_callback
    def _async_new_entity(announce_platform: str, vdef, instance: str, extra) -> None:
        if announce_platform != platform:
            return
        if not data.claim(platform, vdef.key, instance if extra is None else str(extra)):
            return
        factory(vdef, instance, extra)

    entry.async_on_unload(
        async_dispatcher_connect(
            hass, SIGNAL_NEW_ENTITY.format(entry.entry_id), _async_new_entity
        )
    )
    # Replay announcements that fired before this platform subscribed.
    for announcement in list(data.discovered.values()):
        _async_new_entity(*announcement)


class _SafeDict(dict):
    """format_map helper — unknown placeholders become empty strings."""

    def __missing__(self, key: str) -> str:
        return ""


class CcpEntity(Entity):
    """Common behaviour: device grouping, availability, value updates."""

    _attr_should_poll = False
    _attr_has_entity_name = False

    def __init__(self, data, vdef, instance: str, value_key: str) -> None:
        self._data = data
        self._hub = data.hub
        self._def = vdef
        self._instance = instance
        self._value_key = value_key
        portal = self._hub.portal_id
        self._attr_unique_id = f"{portal}_{vdef.key}_{instance}"
        self._attr_name = self._resolve_name(vdef, instance)
        if getattr(vdef, "icon", None):
            self._attr_icon = vdef.icon
        if getattr(vdef, "entity_category", None) == "diagnostic":
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
        if getattr(vdef, "enabled_default", True) is False:
            self._attr_entity_registry_enabled_default = False

        custom_tpl = getattr(vdef, "custom_name", None)
        if custom_tpl:
            custom = self._hub.get(vdef.service, instance, "CustomName")
            if custom:
                self._attr_name = custom_tpl.format(custom=custom)

        device = getattr(vdef, "device", DEV_GX)
        dev_id = f"{portal}_{device}"
        info = DeviceInfo(
            identifiers={(DOMAIN, dev_id)},
            name=DEVICE_NAMES[device],
            manufacturer=MANUFACTURER,
            model="Cerbo GX",
        )
        if device != DEV_GX:
            info["via_device"] = (DOMAIN, f"{portal}_{DEV_GX}")
        self._attr_device_info = info

    def _resolve_name(self, vdef, instance: str) -> str:
        """Build the entity name, honouring per-instance custom names.

        Resolution order for services in NAMEABLE_SERVICES:
          1. A user-set custom name (settings cog) wins outright.
          2. If only one instance of the service exists, drop the {instance}
             number entirely ("Alternator Current", not "Alternator 278 Current").
          3. Otherwise fall back to the default "{instance}" formatting.
        Non-nameable services always use the default formatting.
        """
        service = vdef.service
        base = vdef.name  # e.g. "Alternator {instance} Current"

        if service in NAMEABLE_SERVICES:
            # 1. explicit custom name for this instance
            key = CONF_INSTANCE_NAME.format(service=service, instance=instance)
            custom = self._data.entry.options.get(key)
            if custom:
                # Replace the "{service-label} {instance}" portion with the
                # custom label by substituting {instance} -> custom and then
                # collapsing a now-redundant service word is overkill; instead
                # we swap the whole "<Word> {instance}" head for the custom
                # label when the template starts with a word + {instance}.
                return self._apply_custom(base, instance, custom)

            # 2. single instance -> drop the number
            if len(self._hub.instances_of(service)) <= 1:
                # Remove the "{instance}" placeholder and any doubled spaces.
                dropped = base.replace("{instance}", "").replace("  ", " ")
                return dropped.strip()

        # 3. default
        return base.format_map(_SafeDict(instance=instance)).strip()

    @staticmethod
    def _apply_custom(base: str, instance: str, custom: str) -> str:
        """Substitute a custom label in place of the '<Word> {instance}' head.

        "Alternator {instance} Current" + custom "Starter" -> "Starter Current".
        "Solar Charger {instance} Power" + custom "Roof"   -> "Roof Power".
        Falls back to replacing just {instance} if the pattern isn't the
        expected "<Word(s)> {instance} <rest>" shape.
        """
        marker = "{instance}"
        if marker not in base:
            return f"{custom} {base}".strip()
        head, _, tail = base.partition(marker)
        # head is like "Alternator " or "Solar Charger " — drop it, use custom.
        return f"{custom}{tail}".strip().replace("  ", " ")

    @property
    def available(self) -> bool:
        return self._hub.connected and self._hub.heartbeat_ok

    async def async_added_to_hass(self) -> None:
        eid = self._data.entry.entry_id
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_VALUE.format(eid, self._value_key), self._handle_update
            )
        )
        if getattr(self._def, "custom_name", None):
            self.async_on_remove(
                async_dispatcher_connect(
                    self.hass,
                    SIGNAL_VALUE.format(
                        eid, f"customname_{self._def.service}_{self._instance}"
                    ),
                    self._handle_custom_name,
                )
            )
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, SIGNAL_CONNECTION.format(eid), self._handle_connection
            )
        )

    @callback
    def _handle_custom_name(self, custom) -> None:
        if custom:
            self._attr_name = self._def.custom_name.format(custom=custom)
            self.async_write_ha_state()

    @callback
    def _handle_connection(self, _connected: bool) -> None:
        self.async_write_ha_state()

    @callback
    def _handle_update(self, value) -> None:
        self._apply_value(value)
        self.async_write_ha_state()

    @callback
    def _apply_value(self, value) -> None:
        """Override in platform classes."""
        raise NotImplementedError
