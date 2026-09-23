# Copyright (c) 2026 Samuel Myers. All rights reserved.
# Proprietary - see LICENSE. Unauthorised use, copying, or distribution prohibited.

"""Clever Caravan: Power — Victron GX over MQTT, with Victron BLE fallback.

Data path:
    VenusHub (MQTT, paho thread) --marshal--> resolver.update_mqtt
    BleHub   (BLE, event loop)   ----------->  resolver.update_ble
    resolver.on_output --> _resolver_output --> writeback + discovery/dispatch

The resolver (resolver.py) decides, per (service, instance, path) triple, which
source is authoritative: MQTT when its connection is healthy, BLE as fallback /
gap-fill. Entities are unchanged — they consume the same triples regardless of
which source produced them. With no BLE devices configured, BleHub is never
created and behaviour is identical to the MQTT-only integration.

A discovery watcher raises a fixable Repairs issue whenever a Victron device
advertises over Bluetooth without a key configured. It only runs while the
installer-only "BLE discovery" option is on; turning it off deletes every
un-keyed issue (active or ignored) and clears the ignored-MAC list, so
neighbouring/passing caravans can never spam Repairs.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import (
    BluetoothCallbackMatcher,
    BluetoothChange,
    BluetoothScanningMode,
    BluetoothServiceInfoBleak,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_time_interval

from .ble_hub import BleDevice, BleHub
from .ble_map import (
    CONF_BLE_DEVICES,
    CONF_BLE_IGNORED,
    ISSUE_PREFIX,
    KIND_LABELS,
    VICTRON_COMPANY_ID,
    detect_kind,
    discovery_enabled,
    is_valid_key,
)
from .const import (
    BINARY_SENSOR_DEFS,
    CONF_PORTAL_ID,
    CONF_USE_SSL,
    DOMAIN,
    KEEPALIVE_INTERVAL,
    NUMBER_DEFS,
    SELECT_DEFS,
    SENSOR_DEFS,
    SIGNAL_CONNECTION,
    SIGNAL_NEW_ENTITY,
    SIGNAL_VALUE,
    SWITCH_DEFS,
)
from .hub import VenusHub
from .resolver import SourceResolver

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.SWITCH,
    Platform.SELECT,
    Platform.NUMBER,
    Platform.BUTTON,
]

# A BLE reading counts as "live" only if seen within this many seconds.
BLE_TTL_SECONDS = 60.0

# Index definitions by (service, path) for O(1) lookup on every value.
_DEFS_BY_TOPIC: dict[tuple[str, str], list] = {}
for _def in (*SENSOR_DEFS, *BINARY_SENSOR_DEFS, *SELECT_DEFS, *NUMBER_DEFS):
    _DEFS_BY_TOPIC.setdefault((_def.service, _def.path), []).append(_def)

_PLATFORM_OF = {}
for _d in SENSOR_DEFS:
    _PLATFORM_OF[_d.key] = "sensor"
for _d in BINARY_SENSOR_DEFS:
    _PLATFORM_OF[_d.key] = "binary_sensor"
for _d in SELECT_DEFS:
    _PLATFORM_OF[_d.key] = "select"
for _d in NUMBER_DEFS:
    _PLATFORM_OF[_d.key] = "number"


def _issue_id(mac: str) -> str:
    return f"{ISSUE_PREFIX}{mac.upper()}"


@callback
def _purge_unkeyed_issues(hass: HomeAssistant) -> int:
    """Delete every un-keyed BLE issue, including ones the user dismissed."""
    registry = ir.async_get(hass)
    stale = [
        issue_id
        for (domain, issue_id) in list(registry.issues)
        if domain == DOMAIN and issue_id.startswith(ISSUE_PREFIX)
    ]
    for issue_id in stale:
        ir.async_delete_issue(hass, DOMAIN, issue_id)
    return len(stale)


class CcpData:
    """Runtime data shared with the entity platforms."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, hub: VenusHub) -> None:
        self.hass = hass
        self.entry = entry
        self.hub = hub
        # Merges MQTT (primary) and BLE (fallback). MQTT health is read live so
        # there is no startup gap waiting on a timer.
        self.resolver = SourceResolver(
            ble_ttl=BLE_TTL_SECONDS,
            mqtt_healthy_fn=lambda: hub.connected and hub.heartbeat_ok,
        )
        self.resolver.on_output = self._resolver_output
        self.ble_hub: BleHub | None = None
        self._unsub_discovery = None
        self._flagged_macs: set[str] = set()
        # discovered[(def_key, instance)] = (platform, vdef, instance, extra)
        self.discovered: dict[tuple[str, str], tuple] = {}
        # Claimed (created) entities, guarded so replay + live signals can
        # never double-add: claimed by (platform, def_key, instance).
        self._claimed: set[tuple[str, str, str]] = set()
        self._unsub_keepalive = None

    def claim(self, platform: str, def_key: str, instance: str) -> bool:
        """Return True exactly once per entity — the caller may create it."""
        key = (platform, def_key, instance)
        if key in self._claimed:
            return False
        self._claimed.add(key)
        return True

    def ble_fresh(self, service: str, instance: str, path: str) -> bool:
        """Whether BLE currently has a fresh reading for this triple."""
        return self.resolver.ble_fresh(service, instance, path)

    # --------- feeders: marshal every source onto the event loop -----------
    # VenusHub calls this from the paho network thread.
    def thread_on_value(self, service: str, instance: str, path: str, value) -> None:
        self.hass.loop.call_soon_threadsafe(
            self.resolver.update_mqtt, service, instance, path, value
        )

    # VenusHub calls this from the paho network thread.
    def thread_on_connection(self, connected: bool) -> None:
        self.hass.loop.call_soon_threadsafe(self._handle_connection_change, connected)

    # BleHub calls this from the event loop (HA bluetooth callbacks).
    @callback
    def _on_ble_triple(self, service: str, instance: str, path: str, value) -> None:
        self.resolver.update_ble(service, instance, path, value)

    @callback
    def _handle_connection_change(self, connected: bool) -> None:
        # Re-resolve (MQTT health transition) and refresh entity availability.
        self.resolver.recompute()
        async_dispatcher_send(
            self.hass, SIGNAL_CONNECTION.format(self.entry.entry_id), connected
        )

    # --------- resolver output: the single sink for winning values ---------
    @callback
    def _resolver_output(
        self, service: str, instance: str, path: str, value, live: bool
    ) -> None:
        # Writeback so aggregates and initial entity reads (hub.get) see the
        # winning value regardless of which source produced it. Via store() so
        # the write is lock-guarded against instances_of() iterating.
        self.hub.store(service, instance, path, value)
        self._dispatch(service, instance, path, value)

    @callback
    def _dispatch(self, service: str, instance: str, path: str, value) -> None:
        eid = self.entry.entry_id

        # Relays are dynamic (Relay/<n>/State) — handled as a pattern.
        if service == "system" and path.startswith("Relay/") and path.endswith("/State"):
            relay = path.split("/")[1]
            disc_key = ("relay", relay)
            if disc_key not in self.discovered:
                announcement = ("switch", SWITCH_DEFS[0], instance, {"relay": relay})
                self.discovered[disc_key] = announcement
                async_dispatcher_send(self.hass, SIGNAL_NEW_ENTITY.format(eid), *announcement)
            async_dispatcher_send(
                self.hass, SIGNAL_VALUE.format(eid, f"relay_{relay}"), value
            )
            return

        if path == "CustomName":
            async_dispatcher_send(
                self.hass,
                SIGNAL_VALUE.format(eid, f"customname_{service}_{instance}"),
                value,
            )
            return

        defs = _DEFS_BY_TOPIC.get((service, path))
        if not defs:
            return
        # Any solar yield update also feeds the Total Solar aggregates.
        if service == "solarcharger" and path in ("Yield/Power", "Yield/User", "History/Daily/0/Yield"):
            async_dispatcher_send(self.hass, SIGNAL_VALUE.format(eid, "sc_aggregate"), value)
        for vdef in defs:
            disc_key = (vdef.key, instance)
            if disc_key not in self.discovered:
                announcement = (_PLATFORM_OF[vdef.key], vdef, instance, None)
                self.discovered[disc_key] = announcement
                async_dispatcher_send(self.hass, SIGNAL_NEW_ENTITY.format(eid), *announcement)
            async_dispatcher_send(
                self.hass, SIGNAL_VALUE.format(eid, f"{vdef.key}_{instance}"), value
            )

    async def async_start_keepalive(self) -> None:
        @callback
        def _keepalive(_now) -> None:
            self.hub.publish_keepalive()
            # Periodic sweep: drives heartbeat-staleness failover and BLE TTL
            # expiry even when no new packet has arrived.
            self.resolver.recompute()

        self._unsub_keepalive = async_track_time_interval(
            self.hass, _keepalive, timedelta(seconds=KEEPALIVE_INTERVAL)
        )

    def _configured_macs(self) -> set[str]:
        return {
            d["address"].upper()
            for d in (self.entry.options.get(CONF_BLE_DEVICES) or [])
        }

    def _ignored_macs(self) -> set[str]:
        return {m.upper() for m in (self.entry.options.get(CONF_BLE_IGNORED) or [])}

    def _start_ble(self) -> None:
        """Start the BLE fallback if any devices are configured."""
        raw = self.entry.options.get(CONF_BLE_DEVICES) or []
        devices = []
        for d in raw:
            if not (d.get("address") and d.get("key") and d.get("instance") is not None):
                continue
            if not is_valid_key(d["key"]):
                _LOGGER.warning(
                    "Clever Caravan Power: skipping BLE device %s — its advertisement "
                    "key is not 32 hex characters. Re-enter it under Options -> "
                    "Victron Bluetooth fallback.",
                    d.get("address"),
                )
                continue
            devices.append(
                BleDevice(address=d["address"], key=d["key"], instance=str(d["instance"]))
            )
        if not devices:
            return
        self.ble_hub = BleHub(self.hass, devices, self._on_ble_triple)
        self.ble_hub.start()
        _LOGGER.info("Clever Caravan Power: BLE fallback active for %d device(s)", len(devices))

    def _start_ble_discovery(self) -> None:
        """Watch for Victron devices advertising without a key and raise a
        fixable Repairs issue for each, so the user can fold them in.

        Registered regardless of whether any BLE device is configured. Replay of
        the last-known advert flags devices already broadcasting at startup.
        """

        @callback
        def _on_victron_advert(
            service_info: BluetoothServiceInfoBleak, change: BluetoothChange
        ) -> None:
            mac = service_info.address.upper()
            if (
                mac in self._flagged_macs
                or mac in self._configured_macs()
                or mac in self._ignored_macs()
            ):
                return
            raw = service_info.manufacturer_data.get(VICTRON_COMPANY_ID)
            if not raw:
                return
            kind = detect_kind(raw)
            if kind is None:
                return
            self._flagged_macs.add(mac)
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                _issue_id(mac),
                is_fixable=True,
                severity=ir.IssueSeverity.WARNING,
                translation_key="ble_unkeyed",
                translation_placeholders={
                    "kind": KIND_LABELS.get(kind, kind),
                    "address": mac,
                },
                data={
                    "entry_id": self.entry.entry_id,
                    "address": mac,
                    "kind": kind,
                    "issue_id": _issue_id(mac),
                },
            )

        self._unsub_discovery = bluetooth.async_register_callback(
            self.hass,
            _on_victron_advert,
            BluetoothCallbackMatcher(
                manufacturer_id=VICTRON_COMPANY_ID, connectable=False
            ),
            BluetoothScanningMode.PASSIVE,
        )

    def stop(self) -> None:
        if self._unsub_keepalive:
            self._unsub_keepalive()
        if self._unsub_discovery:
            self._unsub_discovery()
        if self.ble_hub is not None:
            self.ble_hub.stop()
        self.hub.stop()


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    hub = VenusHub(
        host=entry.data[CONF_HOST],
        port=entry.data.get(CONF_PORT, 1883),
        username=entry.data.get(CONF_USERNAME) or None,
        password=entry.data.get(CONF_PASSWORD) or None,
        use_ssl=entry.data.get(CONF_USE_SSL, False),
        portal_id=entry.data.get(CONF_PORTAL_ID) or None,
    )
    data = CcpData(hass, entry, hub)
    hub.on_value = data.thread_on_value
    hub.on_connection = data.thread_on_connection

    await hass.async_add_executor_job(hub.start)
    portal = await hass.async_add_executor_job(hub.wait_for_portal, 15.0)
    if portal is None:
        data.stop()
        raise ConfigEntryNotReady(f"No Venus portal detected at {entry.data[CONF_HOST]}")

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = data

    # BLE fallback (no-op unless devices are configured) + discovery watcher.
    # Started before the platforms so any retained advert replays into discovery
    # alongside MQTT.
    data._start_ble()
    if discovery_enabled(entry.options):
        data._start_ble_discovery()
    else:
        # Discovery off: clear the backlog. Done before the update listener is
        # registered, so the options write below doesn't trigger a reload.
        purged = _purge_unkeyed_issues(hass)
        if entry.options.get(CONF_BLE_IGNORED):
            hass.config_entries.async_update_entry(
                entry, options={**entry.options, CONF_BLE_IGNORED: []}
            )
        if purged:
            _LOGGER.info(
                "Clever Caravan Power: BLE discovery off — cleared %d Repairs issue(s)",
                purged,
            )

    # Entity platforms subscribe to discovery signals first, then we let the
    # retained/full-publish messages flow into discovery.
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await data.async_start_keepalive()

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        data: CcpData = hass.data[DOMAIN].pop(entry.entry_id)
        await hass.async_add_executor_job(data.stop)
    return unload_ok
