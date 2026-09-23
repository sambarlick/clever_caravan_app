# Copyright (c) 2026 Samuel Myers. All rights reserved.
# Proprietary - see LICENSE. Unauthorised use, copying, or distribution prohibited.

"""Constants for the Clever Caravan: Waymote integration."""

from __future__ import annotations

DOMAIN = "clever_caravan_waymote"

# Waymote bridge REST API
DEFAULT_PORT = 8080
API_CONFIG_PATH = "/api/config"

# How often to re-read config.json from the bridge (seconds).
DEFAULT_SCAN_INTERVAL = 60

# Network timeout for a single bridge request (seconds).
REQUEST_TIMEOUT = 10

# MQTT topic scheme (published through Home Assistant's own MQTT connection).
CONTROL_TOPIC = "Waymote/Output{n}/Control"
STATUS_TOPIC = "Waymote/Output{n}/Status"
AVAILABILITY_TOPIC = "Waymote/Bridge/Availability"

# Which HA entity types an output may be mapped to (single-output types only;
# multi-output composites like cover are handled separately, later).
SUPPORTED_DOMAINS = ["switch", "light", "fan"]
DEFAULT_DOMAIN = "switch"

# Key under config entry data holding the {channel: domain} map.
CONF_DOMAINS = "domains"


def infer_domain(name: str) -> str:
    """Best-guess HA type from an output's name. User confirms in onboarding."""
    n = (name or "").lower()
    if "light" in n:
        return "light"
    if "fan" in n:
        return "fan"
    return DEFAULT_DOMAIN
