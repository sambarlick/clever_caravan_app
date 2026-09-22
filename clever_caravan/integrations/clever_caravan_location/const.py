# Copyright (c) 2026 Samuel Myers. All rights reserved.
# Proprietary - see LICENSE. Unauthorised use, copying, or distribution prohibited.

"""Constants for Clever Caravan Location."""

from __future__ import annotations

import json
from pathlib import Path

DOMAIN = "clever_caravan_location"

# Integration version, read from the manifest so it has a single source of
# truth. Used to build the outbound User-Agent below. Falls back gracefully
# if the manifest can't be read for any reason.
try:
    VERSION: str = json.loads(
        (Path(__file__).parent / "manifest.json").read_text(encoding="utf-8")
    )["version"]
except (OSError, ValueError, KeyError):
    VERSION = "0.0.0"

# Single User-Agent for every outbound API call (Nominatim, Wikipedia, ABS).
# Derived from VERSION so it never drifts out of step with releases.
USER_AGENT = (
    f"CleverCaravan/{VERSION} "
    "(https://github.com/sambarlick/clever_caravan_location)"
)

# Config entry keys
CONF_SOURCE = "source"
CONF_LATITUDE_ENTITY = "latitude_entity"
CONF_LONGITUDE_ENTITY = "longitude_entity"
CONF_ELEVATION_ENTITY = "elevation_entity"
CONF_SPEED_ENTITY = "speed_entity"
CONF_USB_DEVICE = "usb_device"
CONF_USB_BAUDRATE = "usb_baudrate"
CONF_REVERSE_GEOCODE = "reverse_geocode"

# Source types
SOURCE_USB = "usb"
SOURCE_ENTITY = "entity"
SOURCE_MANUAL = "manual"
SOURCES = [SOURCE_USB, SOURCE_ENTITY, SOURCE_MANUAL]

# Status enum values (Sam's terms)
STATUS_DRIVING = "Driving"
STATUS_NOT_DRIVING = "Not Driving"
STATUS_PARKED_UP = "Parked Up"
STATUS_UNKNOWN = None  # HA-native unknown state (no valid fix yet)

STATUS_OPTIONS = [STATUS_DRIVING, STATUS_NOT_DRIVING, STATUS_PARKED_UP]

# Fix quality enum (NMEA $GPGGA field 7) → user-facing accuracy labels
FIX_QUALITY_LABELS: dict[int, str] = {
    0: "No Signal",
    1: "Standard (~3-5m accuracy)",
    2: "Standard (~1m accuracy)",
    4: "High Precision (~1cm accuracy)",
    5: "High Precision (~10cm accuracy)",
    6: "Estimated (predicted from last movement)",
    9: "Enhanced (~1m accuracy)",
}
FIX_QUALITY_OPTIONS = list(FIX_QUALITY_LABELS.values())

# Fix mode enum (NMEA $GPGSA field 2)
FIX_MODE_NO_FIX = "No Fix"
FIX_MODE_2D = "2D Fix"
FIX_MODE_3D = "3D Fix"
FIX_MODE_OPTIONS = [FIX_MODE_NO_FIX, FIX_MODE_2D, FIX_MODE_3D]

# Gradient enum
GRADIENT_CLIMBING = "Climbing"
GRADIENT_DESCENDING = "Descending"
GRADIENT_LEVEL = "Level"
GRADIENT_OPTIONS = [GRADIENT_CLIMBING, GRADIENT_LEVEL, GRADIENT_DESCENDING]

# Heading: 16-direction compass rose (matches the old MQTT add-on)
HEADING_DIRECTIONS = [
    "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
    "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
]

# Speed thresholds (km/h)
SPEED_DRIVING_THRESHOLD = 5.0
SPEED_NOT_DRIVING_THRESHOLD = 1.0
PARKED_UP_AFTER_MINUTES = 20

# Climb thresholds (m/s) — gradient classifier
CLIMB_GRADIENT_THRESHOLD_MS = 0.5
# Window over which to compute climb rate from elevation samples
CLIMB_WINDOW_S = 5.0

# USB defaults
DEFAULT_BAUDRATE = 9600

# DOP-to-accuracy multiplier (rule of thumb: ~5m baseline × DOP)
DOP_TO_METRES = 5.0

# Sanity bounds
LAT_MIN = -90.0
LAT_MAX = 90.0
LON_MIN = -180.0
LON_MAX = 180.0

# Action layer thresholds
SET_LOCATION_MIN_DELTA_DEG = 0.001        # ~110m
TIMEZONE_MIN_DELTA_DEG = 0.1              # ~11km
GEOCODE_MIN_DELTA_DEG = 0.01              # ~1.1km
GEOCODE_MIN_INTERVAL_S = 60

# Nominatim
NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
NOMINATIM_USER_AGENT = USER_AGENT
NOMINATIM_TIMEOUT_S = 10

# Meteostat climate normals via RapidAPI
METEOSTAT_HOST = "meteostat.p.rapidapi.com"
METEOSTAT_URL = "https://meteostat.p.rapidapi.com/point/normals"
METEOSTAT_KEY = "2c0706353bmsh99520efe69ff5f7p18a435jsn40c4329870f8"  # RapidAPI key — set in const.py before deploy
METEOSTAT_TIMEOUT_S = 15

# Wikipedia REST summary
WIKI_URL_BASE = "https://en.wikipedia.org/api/rest_v1/page/summary"
WIKI_USER_AGENT = USER_AGENT
WIKI_TIMEOUT_S = 10

# ABS Digital Atlas (SEIFA by SAL)
ABS_URL = (
    "https://services-ap1.arcgis.com/ypkPEy1AmwPKGNNv/arcgis/rest/services/"
    "ABS_Socio_Economic_Indexes_for_Areas_SEIFA_by_2021_SAL/FeatureServer/0/query"
)
ABS_USER_AGENT = USER_AGENT
ABS_TIMEOUT_S = 15
ABS_MIN_INTERVAL_S = 60

# Service
SERVICE_UPDATE = "update"

# Signal dispatch
SIGNAL_LOCATION_UPDATED = f"{DOMAIN}_location_updated"
SIGNAL_GEOCODE_UPDATED = f"{DOMAIN}_geocode_updated"
SIGNAL_ABS_UPDATED = f"{DOMAIN}_abs_updated"
SIGNAL_WIKI_UPDATED = f"{DOMAIN}_wiki_updated"
SIGNAL_METEOSTAT_UPDATED = f"{DOMAIN}_meteostat_updated"
