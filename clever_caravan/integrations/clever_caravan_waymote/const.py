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

# Key under config entry data holding the list of combined devices. Each entry:
#   {"type": "two_tone_light", "name": str, "white": int, "ambient": int}
# Channels used by a combo do not also appear as standalone entities.
CONF_COMBOS = "combos"

COMBO_TWO_TONE = "two_tone_light"
COMBO_AWNING = "awning"

# Awning power handling (adjustable from the integration's Configure screen).
CONF_AWNING_POWER_OFF_MINUTES = "awning_power_off_minutes"
CONF_AWNING_STOP_CUTS_POWER = "awning_stop_cuts_power"
DEFAULT_AWNING_POWER_OFF_MINUTES = 3
DEFAULT_AWNING_STOP_CUTS_POWER = False

# Colour temperatures used to represent the two tones of a two-tone light.
# The relays are on/off only; these give HA a normal colour-temp control that
# snaps between the two, and name the tones for the dropdown.
TONE_WHITE_KELVIN = 5000
TONE_AMBIENT_KELVIN = 2700
TONE_WHITE = "White"
TONE_AMBIENT = "Ambient"


def combo_channels(combo: dict) -> list[int]:
    """Channel numbers consumed by one combo."""
    if combo.get("type") == COMBO_TWO_TONE:
        return [int(combo["white"]), int(combo["ambient"])]
    if combo.get("type") == COMBO_AWNING:
        return [int(combo["power"]), int(combo["extend"]), int(combo["retract"])]
    return []


def channels_in_combos(combos: list[dict] | None) -> set[int]:
    """All channels consumed by combos, so platforms can skip them."""
    used: set[int] = set()
    for combo in combos or []:
        used.update(combo_channels(combo))
    return used


def infer_domain(name: str) -> str:
    """Best-guess HA type from an output's name. User confirms in onboarding."""
    n = (name or "").lower()
    if "light" in n:
        return "light"
    if "fan" in n:
        return "fan"
    return DEFAULT_DOMAIN
