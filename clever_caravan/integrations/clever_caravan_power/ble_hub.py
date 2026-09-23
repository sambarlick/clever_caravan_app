# Copyright (c) 2026 Samuel Myers. All rights reserved.
# Proprietary - see LICENSE. Unauthorised use, copying, or distribution prohibited.

"""BLE ingestion for Clever Caravan: Power — Victron Instant Readout fallback.

Subscribes to Home Assistant's Bluetooth advertisements for each configured
Victron device, decrypts + maps them (ble_map), and pushes the resulting Venus
triples to a sink (the resolver's update_ble).

Broadcast-only: this never opens a BLE connection. It registers one passive
callback per configured device (matched by MAC), so the per-device key and Venus
instance are bound in the callback closure. Callbacks fire on the event loop, so
the sink is touched only on the loop — same thread the MQTT feed marshals onto —
and the resolver needs no locking.

This is the only BLE file that imports Home Assistant; parsing/mapping/arbitration
all live in HA-free modules (ble_map, resolver).
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import (
    BluetoothCallbackMatcher,
    BluetoothChange,
    BluetoothScanningMode,
    BluetoothServiceInfoBleak,
)
from homeassistant.core import HomeAssistant, callback

from .ble_map import VICTRON_COMPANY_ID, parse_and_map

_LOGGER = logging.getLogger(__name__)

# Sink signature: (service, instance, path, value) -> None.
OnTriple = Callable[[str, str, str, object], None]


@dataclass(frozen=True)
class BleDevice:
    """A configured Victron BLE device to listen for."""

    address: str   # MAC, colon-separated
    key: str       # per-device advertisement key (hex)
    instance: str  # the Venus instance this device mirrors


class BleHub:
    """Feeds Victron Instant Readout advertisements into a triple sink."""

    def __init__(
        self, hass: HomeAssistant, devices: list[BleDevice], on_triple: OnTriple
    ) -> None:
        self._hass = hass
        self._devices = {d.address.upper(): d for d in devices}
        self._on_triple = on_triple
        self._unsubs: list[Callable[[], None]] = []

    def start(self) -> None:
        """Register a passive per-device advertisement callback."""
        for address, device in self._devices.items():
            unsub = bluetooth.async_register_callback(
                self._hass,
                self._make_callback(device),
                BluetoothCallbackMatcher(address=address, connectable=False),
                BluetoothScanningMode.PASSIVE,
            )
            self._unsubs.append(unsub)
        _LOGGER.debug(
            "BLE fallback listening for %d Victron device(s)", len(self._devices)
        )

    def stop(self) -> None:
        while self._unsubs:
            self._unsubs.pop()()

    def _make_callback(self, device: BleDevice):
        @callback
        def _on_advertisement(
            service_info: BluetoothServiceInfoBleak, change: BluetoothChange
        ) -> None:
            raw = service_info.manufacturer_data.get(VICTRON_COMPANY_ID)
            if not raw:
                return
            try:
                triples = parse_and_map(raw, device.key, device.instance)
            except Exception:  # noqa: BLE001 - a bad advert must not kill the callback
                _LOGGER.exception(
                    "BLE parse failed for %s (instance %s)",
                    device.address,
                    device.instance,
                )
                return
            for service, instance, path, value in triples:
                self._on_triple(service, instance, path, value)
            if triples and _LOGGER.isEnabledFor(logging.DEBUG):
                _LOGGER.debug(
                    "BLE decode %s (instance %s): %s",
                    device.address,
                    device.instance,
                    {f"{s}/{i}/{p}": v for s, i, p, v in triples},
                )

        return _on_advertisement
