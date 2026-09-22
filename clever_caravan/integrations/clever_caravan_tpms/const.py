# Copyright (c) 2026 Samuel Myers. All rights reserved.
# Proprietary - see LICENSE. Unauthorised use, copying, or distribution prohibited.

"""Constants for the Clever Caravan TPMS integration."""

DOMAIN = "clever_caravan_tpms"

# Safety Sam sensors (SYTPMS clone family) advertise with this
# Bluetooth SIG company identifier in the manufacturer data.
MANUFACTURER_ID = 256  # 0x0100

# Advertised service UUID used as a secondary discovery matcher.
SERVICE_UUID = "0000fbb0-0000-1000-8000-00805f9b34fb"

# First byte of the MAC / payload encodes wheel position: 0x80 = wheel 1.
WHEEL_BASE = 0x80
MAX_WHEELS = 8
