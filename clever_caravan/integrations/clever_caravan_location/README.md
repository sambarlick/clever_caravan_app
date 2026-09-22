# Clever Caravan: Location

Home Assistant integration that gives the whole Clever Caravan system a live
sense of place. It reads GPS from whatever source a van has, keeps `zone.home`
and the system clock in step as the van moves, and — when the van stops —
enriches the location with reverse-geocoding and Australian place data. Built
for Clever Caravan installs: zero YAML, one source to pick, everything else
automatic.

> Place enrichment (statistical areas, climate normals) is Australia-focused.
> Core tracking works anywhere.

## Sources

One integration, three ways to feed it location. Chosen at setup and
changeable in place afterwards (see **Reconfigure**):

- **USB GPS dongle** — a NMEA GPS plugged into the HA host. Full fix-quality
  reporting: satellites, HDOP, 2D/3D mode, horizontal/vertical accuracy.
- **Entity-based** — reads latitude/longitude from existing HA entities:
  Starlink, a Companion-app `device_tracker` (e.g. an iPad — coordinates are
  read straight from its attributes), or MQTT GPS sensors.
- **Manual** — `input_number` helpers, for the bench and testing.

## What you get

**Position** — Latitude, Longitude, Elevation, Speed, Heading (16-point
compass), Bearing.

**Movement** — Status (Driving / Not Driving / Parked Up), Gradient
(Climbing / Level / Descending), Climb rate.

**Fix quality** *(USB source)* — GPS fix quality, GPS fix mode, Satellites
used, Satellites visible, HDOP, Horizontal accuracy, Vertical accuracy, GPS
atomic time, and a GPS healthy binary sensor.

**Place** — Current location, City, State, Country, Postcode.

**Enrichment** — Population, Population density, Statistical Area and its
size, a Wikipedia summary and image for the locality, and long-term climate
normals (mean max / min / temp, monthly rainfall).

Plus a **Force update** button and service.

## How it works

Tracking is **logic-gated**. As the van moves it keeps three things current:
`zone.home`, the system timezone (derived from the coordinates), and the
reverse-geocode sensors — each only when the position has moved enough to
matter, so a day of driving doesn't churn the database.

The heavier place enrichment — geocoding, ABS, Wikipedia, climate normals —
fires on the transition **into Parked Up**, not continuously. The van can
drive all day without burning through external lookups; the moment it settles,
the location fills in. The **Update** button forces a refresh on demand.

## Installation (HACS)

1. HACS → ⋮ → **Custom repositories** →
   `https://github.com/sambarlick/clever_caravan_location`, type *Integration*.
2. Install **Clever Caravan: Location** and restart Home Assistant.
3. Settings → Devices & Services → **Add Integration** → *Clever Caravan:
   Location*.
4. Pick a source type, then its settings — GPS device for USB, or the lat/lon
   entities for entity-based.

## Reconfigure — change source in place

Sources change over the life of a van: a Starlink GPS goes away, an iPad takes
over, an MQTT feed comes online. The entry's **⋮ → Reconfigure** swaps the
source without deleting and re-adding — entity IDs and history are preserved.

To move to a Companion-app device (iPad or phone): Reconfigure → **Entity-based**
→ point both latitude and longitude at that `device_tracker`. Coordinates come
from its attributes; leave elevation and speed blank.

## Requirements

- Home Assistant with HACS.
- Dependencies (installed automatically): `pyserial-asyncio-fast`, `pynmea2`,
  `tzfpy`.
- **USB source:** a NMEA GPS dongle on the HA host.
- **Entity source:** entities exposing latitude and longitude, or a GPS
  `device_tracker`.

## Roadmap

- MQTT GPS as a first-class source, sharing the NMEA parser with USB.
- Meteostat API key as a setup/reconfigure field (out of source).
- Auto-populate on a cold start while already parked.

---

*Part of the [Clever Caravan](https://github.com/sambarlick) project.*
