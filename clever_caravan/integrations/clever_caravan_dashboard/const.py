# Copyright (c) 2026 Samuel Myers. All rights reserved.
# Proprietary - see LICENSE. Unauthorised use, copying, or distribution prohibited.

"""Constants for the Clever Caravan Dashboard integration."""

from __future__ import annotations

DOMAIN = "clever_caravan_dashboard"

# Static HTTP mount point + filename for the bundled strategy module.
# The cache-busting ?v= is read from manifest.json at runtime (see __init__.py).
URL_BASE = "/clever_caravan_dashboard"
JS_FILENAME = "cc-dashboard.js"

# Config-sensor / options keys.
CONF_TIER = "tier"
CONF_ROLE_MAP = "role_map"
CONF_EXTRA_PLATFORMS = "extra_platforms"

# Product tiers. Set by the installer in the options flow; end users have no
# access to HA settings.
TIER_BASE = "base"
TIER_PREMIUM = "premium"
TIER_CUSTOM = "custom"
TIER_KOKODA = "kokoda"
TIERS = [TIER_BASE, TIER_PREMIUM, TIER_CUSTOM, TIER_KOKODA]

# Clever Caravan integrations. Always included, auto-discovered.
OWNED_PLATFORMS = [
    "clever_caravan_power",
    "clever_caravan_tpms",
    "clever_caravan_location",
    "clever_caravan_weather",
    "clever_caravan_waymote",
]
