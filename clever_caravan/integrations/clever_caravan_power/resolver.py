# Copyright (c) 2026 Samuel Myers. All rights reserved.
# Proprietary - see LICENSE. Unauthorised use, copying, or distribution prohibited.

"""Source arbitration for Clever Caravan: Power.

Deliberately free of Home Assistant imports so it can be unit-tested standalone,
matching the philosophy of hub.py.

Two feeders push values per (service, instance, path) triple:
  * MQTT  — primary, richer (VenusHub).
  * BLE   — fallback / gap-fill (Victron Instant Readout via ble_hub).

The resolver decides the winner for each triple:

  * MQTT healthy  -> the MQTT value wins for any triple MQTT provides.
                     BLE fills triples MQTT has NEVER provided (gap-fill for
                     devices not on the Cerbo).
  * MQTT unhealthy -> the BLE value wins wherever BLE is fresh; otherwise the
                      triple has no live source.

"Healthy" is the MQTT *connection* state (connected + heartbeat_ok) — NOT
per-triple age. Venus suppress-republish means a valid value can legitimately be
minutes old, so age is a false staleness signal for MQTT; the connection
dropping is the real one. Health is read through `mqtt_healthy_fn` (a live
callable, so there's no startup gap) when one is supplied; otherwise the pushed
bool set via set_mqtt_healthy() is used (handy for tests).

BLE freshness IS per-triple: a BLE value only counts if its advertisement
arrived within `ble_ttl` seconds (default 60), so a device going out of range
can't hold a stale value up during an MQTT outage.

The resolver calls `on_output(service, instance, path, value, live)` whenever the
winning value OR liveness for a triple changes. Call recompute() periodically
(e.g. off the keepalive tick) and on any MQTT-health transition so BLE values
that age out — or an MQTT recovery — are reflected even without a new packet.
"""
from __future__ import annotations

import time
from collections.abc import Callable

Triple = tuple[str, str, str]  # (service, instance, path)
OutputCallback = Callable[[str, str, str, object, bool], None]


class SourceResolver:
    """Merges MQTT (primary) and BLE (fallback) feeds per triple."""

    def __init__(
        self,
        ble_ttl: float = 60.0,
        time_fn: Callable[[], float] = time.monotonic,
        mqtt_healthy_fn: Callable[[], bool] | None = None,
    ) -> None:
        self._ttl = ble_ttl
        self._now = time_fn
        self._healthy_fn = mqtt_healthy_fn
        # Presence of a triple in _mqtt means "MQTT covers this datapoint".
        self._mqtt: dict[Triple, object] = {}
        # (value, monotonic_timestamp) of the last BLE reading.
        self._ble: dict[Triple, tuple[object, float]] = {}
        self._mqtt_healthy = False  # pushed-mode fallback (see set_mqtt_healthy)
        # Last (value, live) emitted, to suppress no-change churn.
        self._emitted: dict[Triple, tuple[object, bool]] = {}
        self.on_output: OutputCallback | None = None

    # ------------------------------------------------------------- feeders
    def update_mqtt(self, service: str, instance: str, path: str, value) -> None:
        t = (service, instance, path)
        self._mqtt[t] = value
        # force: a repeated same-value reading must still propagate so downstream
        # entity `expire` timers get refreshed (matches the pre-resolver path).
        self._emit(t, force=True)

    def update_ble(self, service: str, instance: str, path: str, value) -> None:
        t = (service, instance, path)
        self._ble[t] = (value, self._now())
        self._emit(t, force=True)

    def set_mqtt_healthy(self, healthy: bool) -> None:
        """Pushed-mode health (used when no mqtt_healthy_fn is supplied).

        A change re-resolves every triple. When a live mqtt_healthy_fn is in
        use, call recompute() on transitions instead.
        """
        if healthy == self._mqtt_healthy:
            return
        self._mqtt_healthy = healthy
        self.recompute()

    # -------------------------------------------------------- periodic sweep
    def recompute(self) -> None:
        """Re-resolve and emit changes for every known triple.

        Drives BLE TTL expiry and health transitions: a BLE value that has aged
        past `ble_ttl` while MQTT is down flips to (None, live=False); an MQTT
        recovery reclaims its triples.
        """
        for t in set(self._mqtt) | set(self._ble):
            self._emit(t)

    # ------------------------------------------------------------ resolution
    def _mqtt_ok(self) -> bool:
        return self._healthy_fn() if self._healthy_fn is not None else self._mqtt_healthy

    def _ble_fresh(self, t: Triple) -> tuple[object, bool]:
        entry = self._ble.get(t)
        if entry is None:
            return None, False
        value, ts = entry
        if (self._now() - ts) > self._ttl:
            return None, False
        return value, True

    def ble_fresh(self, service: str, instance: str, path: str) -> bool:
        """True if a fresh BLE reading currently exists for this triple.

        Evaluated live (checks the TTL now), so entity availability can call it
        on every render without needing a pushed liveness flag.
        """
        return self._ble_fresh((service, instance, path))[1]

    def _resolve(self, t: Triple) -> tuple[object, bool]:
        """Return (value, live) for a triple under the current policy."""
        # MQTT wins whenever it's healthy AND actually carries this triple.
        if self._mqtt_ok() and t in self._mqtt:
            return self._mqtt[t], True
        # Otherwise (MQTT down, or MQTT simply doesn't carry this triple) BLE
        # takes over if it has a fresh reading.
        value, fresh = self._ble_fresh(t)
        if fresh:
            return value, True
        # No live source for this triple right now.
        return None, False

    def _emit(self, t: Triple, force: bool = False) -> None:
        value, live = self._resolve(t)
        if not force and self._emitted.get(t) == (value, live):
            return
        self._emitted[t] = (value, live)
        if self.on_output is not None:
            self.on_output(t[0], t[1], t[2], value, live)
