# Clever Caravan: Weather

![Maintenance](https://img.shields.io/maintenance/yes/2026?style=for-the-badge)

A Home Assistant integration that pulls weather data from the [Australian Bureau of Meteorology (BOM)](http://www.bom.gov.au) for your **current** Home Zone location — built for caravan travellers who move around Australia.

> **This integration only supports locations within Australia.**

---

## What makes this different

Standard BOM integrations lock the weather location to the coordinates set at install time. This integration reads weather data for your **current `zone.home` location**, refreshing every 5 minutes. Move the caravan, update Home Zone, and weather follows you. No reconfiguration needed.

---

## Attribution

This integration is a fork of the excellent [bureau_of_meteorology](https://github.com/bremor/bureau_of_meteorology) custom component by [@bremor](https://github.com/bremor) and contributors. The BOM API client, sensor definitions, forecast formatting, and HA architecture are all their work. This fork adapts that foundation for dynamic Home Zone tracking and an opinionated one-click install.

---

## Installation

### Install

Installed and updated by the Clever Caravan App. Turn on
**Clever Caravan: Weather** in the App's Configuration tab, then add it under
**Settings > Devices & services**.

---

## What you get

19 entities, all prefixed `caravan_`:

**Weather entities (2)**
- `weather.caravan` — daily forecast
- `weather.caravan_hourly` — hourly forecast

**Observations (6)**
- `sensor.caravan_temp` — current temperature
- `sensor.caravan_humidity`
- `sensor.caravan_dew_point`
- `sensor.caravan_wind_direction`
- `sensor.caravan_wind_speed_kilometre`
- `sensor.caravan_gust_speed_kilometre`

**Forecasts (8)**
- `sensor.caravan_short_text_0` through `sensor.caravan_short_text_7` — short text forecast for today (`_0`) and the next 7 days

**Warnings (1)**
- `sensor.caravan_warnings` — count of active BOM warnings; full warning list available in entity attributes

**Station debug (2)**
- `sensor.caravan_station` — name of the BOM observation station serving your location (e.g. "Brisbane Airport")
- `sensor.caravan_station_distance` — distance to that station, in km

---

## How location tracking works

On every refresh cycle (every 5 minutes), the integration reads `zone.home`'s latitude and longitude. If the geohash of that location has changed since the last cycle, it invalidates the cached location data and fetches fresh BOM data for the new spot.

---

## Release notes

### v0.1.0 — Initial fork
- Forked from [bureau_of_meteorology](https://github.com/bremor/bureau_of_meteorology).
- Replaced static lat/lon config with dynamic `zone.home` reads on every refresh cycle.

---

## Links

- **Repository:** [github.com/sambarlick/clever_caravan_weather](https://github.com/sambarlick/clever_caravan_weather)
- **Issues:** [github.com/sambarlick/clever_caravan_weather/issues](https://github.com/sambarlick/clever_caravan_weather/issues)
- **Upstream:** [github.com/bremor/bureau_of_meteorology](https://github.com/bremor/bureau_of_meteorology) by [@bremor](https://github.com/bremor)

---

*Part of the [Clever Caravan](https://github.com/sambarlick) project · Built on the work of [@bremor](https://github.com/bremor) and contributors · Data provided by the [Australian Bureau of Meteorology](http://www.bom.gov.au)*
