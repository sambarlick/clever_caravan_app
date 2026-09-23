# Copyright (c) 2026 Samuel Myers. All rights reserved.
# Proprietary - see LICENSE. Unauthorised use, copying, or distribution prohibited.

"""MQTT hub for Venus OS (Victron GX) devices.

Deliberately free of Home Assistant imports so it can be unit-tested
standalone against any MQTT broker. The HA glue lives in __init__.py.

Venus OS MQTT behaviour this hub encapsulates:
- Topics: N/<portal_id>/<service>/<instance>/<path> (notifications),
  W/... (writes), R/... (requests).
- The broker stops publishing N/ topics unless a keepalive is published
  to R/<portal_id>/keepalive at least every ~60s. An empty keepalive
  payload triggers a full republish of every value; the
  suppress-republish option sends only changes thereafter.
- Payloads are JSON: {"value": <something>}.
"""
from __future__ import annotations

import json
import logging
import ssl as ssl_module
import threading
import time
from collections.abc import Callable

import paho.mqtt.client as mqtt

_LOGGER = logging.getLogger(__name__)

KEEPALIVE_SUPPRESS = '{"keepalive-options": ["suppress-republish"]}'


class VenusHub:
    """Maintains a connection to a Venus OS MQTT broker."""

    def __init__(
        self,
        host: str,
        port: int = 1883,
        username: str | None = None,
        password: str | None = None,
        use_ssl: bool = False,
        portal_id: str | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.portal_id = portal_id
        self.connected = False
        self.last_heartbeat: float = 0.0
        self._stopping = False

        # values[(service, instance, path)] = raw value.
        # Written from the paho network thread (_on_message) AND from the event
        # loop (the resolver writeback via store()), and iterated by
        # instances_of(); guard mutation+iteration with a lock so a concurrent
        # write can't blow up an in-progress iteration.
        self.values: dict[tuple[str, str, str], object] = {}
        self._values_lock = threading.Lock()

        # Callbacks (set by the consumer). All are invoked from the paho
        # network thread — consumers must marshal to their own loop.
        self.on_value: Callable[[str, str, str, object], None] | None = None
        self.on_connection: Callable[[bool], None] | None = None
        self.on_portal: Callable[[str], None] | None = None

        self._portal_event = threading.Event()
        self._full_publish_event = threading.Event()
        if portal_id:
            self._portal_event.set()

        # paho 1.x / 2.x compatibility
        try:
            self._client = mqtt.Client(
                mqtt.CallbackAPIVersion.VERSION2, protocol=mqtt.MQTTv311
            )
        except AttributeError:  # paho 1.x
            self._client = mqtt.Client(protocol=mqtt.MQTTv311)

        if username:
            self._client.username_pw_set(username, password or None)
        if use_ssl:
            ctx = ssl_module.SSLContext(ssl_module.PROTOCOL_TLS_CLIENT)
            ctx.check_hostname = False
            ctx.verify_mode = ssl_module.CERT_NONE  # Venus uses a self-signed cert
            self._client.tls_set_context(ctx)

        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message
        self._client.reconnect_delay_set(min_delay=1, max_delay=30)

    # ------------------------------------------------------------------ public
    def start(self) -> None:
        """Connect and start the network loop (non-blocking)."""
        self._client.connect_async(self.host, self.port, keepalive=60)
        self._client.loop_start()

    def stop(self) -> None:
        self._stopping = True
        self._client.loop_stop()
        try:
            self._client.disconnect()
        except Exception:  # noqa: BLE001 - best effort on teardown
            pass
        self.connected = False

    def wait_for_portal(self, timeout: float = 12.0) -> str | None:
        """Block until the portal ID has been detected (config-flow helper)."""
        if self._portal_event.wait(timeout):
            return self.portal_id
        return None

    def wait_for_data(self, timeout: float = 15.0) -> bool:
        """Block until the initial full publish has completed."""
        return self._full_publish_event.wait(timeout)

    def publish_keepalive(self, full: bool = False) -> None:
        """Tell Venus to keep publishing. full=True requests a full republish."""
        if not self.portal_id or not self.connected:
            return
        payload = "" if full else KEEPALIVE_SUPPRESS
        self._client.publish(f"R/{self.portal_id}/keepalive", payload)

    def set_value(self, service: str, instance: str, path: str, value) -> None:
        """Write a value to a Venus dbus path via the W/ topic."""
        if not self.portal_id:
            return
        topic = f"W/{self.portal_id}/{service}/{instance}/{path}"
        self._client.publish(topic, json.dumps({"value": value}))

    def get(self, service: str, instance: str, path: str):
        # A single dict lookup is atomic under the GIL — no lock needed.
        return self.values.get((service, instance, path))

    def store(self, service: str, instance: str, path: str, value) -> None:
        """Set a merged value (used by the resolver writeback), lock-guarded so
        it can't collide with an iteration in instances_of()."""
        with self._values_lock:
            self.values[(service, instance, path)] = value

    def instances_of(self, service: str) -> set[str]:
        with self._values_lock:
            return {inst for (svc, inst, _p) in self.values if svc == service}

    @property
    def heartbeat_ok(self) -> bool:
        return (time.monotonic() - self.last_heartbeat) < 90 if self.last_heartbeat else False

    # --------------------------------------------------------------- callbacks
    def _on_connect(self, client, userdata, flags, rc, properties=None):
        failed = getattr(rc, "is_failure", None)
        if failed is None:  # paho 1.x int return code
            failed = rc != 0
        if failed:
            _LOGGER.warning("MQTT connect to %s failed: %s", self.host, rc)
            return
        self.connected = True
        _LOGGER.info("Connected to Venus MQTT at %s:%s", self.host, self.port)
        if self.portal_id:
            client.subscribe(f"N/{self.portal_id}/#")
            self.publish_keepalive(full=True)
        else:
            # Portal unknown: watch the always-on heartbeat to learn it.
            client.subscribe("N/+/heartbeat")
            client.subscribe("N/+/system/0/Serial")
        if self.on_connection:
            self.on_connection(True)

    def _on_disconnect(self, client, userdata, *args, **kwargs):
        self.connected = False
        if self._stopping:
            _LOGGER.debug("Disconnected from Venus MQTT at %s (shutdown)", self.host)
        else:
            _LOGGER.warning(
                "Disconnected from Venus MQTT at %s — reconnecting automatically", self.host
            )
        if self.on_connection:
            self.on_connection(False)

    def _set_portal(self, portal_id: str) -> None:
        if self.portal_id:
            return
        self.portal_id = portal_id
        _LOGGER.info("Detected Venus portal ID: %s", portal_id)
        self._portal_event.set()
        self._client.subscribe(f"N/{portal_id}/#")
        self.publish_keepalive(full=True)
        if self.on_portal:
            self.on_portal(portal_id)

    def _on_message(self, client, userdata, msg):
        parts = msg.topic.split("/")
        # N/<portal>/<service>[/<instance>[/<path...>]]
        if len(parts) < 3 or parts[0] != "N":
            return
        portal = parts[1]
        if not self.portal_id:
            self._set_portal(portal)
        elif portal != self.portal_id:
            return

        service = parts[2]
        if service == "heartbeat":
            self.last_heartbeat = time.monotonic()
            return
        if service == "full_publish_completed":
            self._full_publish_event.set()
            return
        if len(parts) < 5:
            return

        instance = parts[3]
        path = "/".join(parts[4:])

        try:
            value = json.loads(msg.payload.decode()).get("value")
        except (ValueError, AttributeError, UnicodeDecodeError):
            return

        with self._values_lock:
            self.values[(service, instance, path)] = value
        if self.on_value:
            self.on_value(service, instance, path, value)
