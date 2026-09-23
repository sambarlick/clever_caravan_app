# Clever Caravan: Power

Home Assistant integration for **Victron Energy GX devices** (Cerbo GX, Venus
OS) — connecting directly to the GX device's MQTT broker. Built for Clever
Caravan installs: zero YAML, zero broker bridging, auto-adapts to whatever
Victron hardware each caravan has.

## What it replaces

If you're migrating from a manual setup, this integration retires:

- The Mosquitto **bridge** config remapping `N/# → victron/N/#`
- The **keepalive automation** publishing to `R/<portal>/keepalive`
- The **MQTT YAML entity file**
- The `shell_command` SSH reboot button

It connects straight to the Cerbo, manages the 30-second keepalive itself
(with `suppress-republish` so you're not flooded), and auto-detects the
portal ID — nothing is hardcoded.

## Entities

Created automatically for whatever the GX reports — three MPPTs or one,
four tanks or none, the same install works everywhere.

**Cerbo GX** — DC/AC consumption, shore power, temperature sensors,
inverter state and alarms, relay switches, Inverter Mode select,
Input Current Limit number, Reboot button.

**Batteries** — SoC, voltage, current, power, temperature, Time to Go
(raw duration + the friendly "2 days 5 hours" text, including
"For Ever and Ever!").

**Solar** — system PV power/current, per-charger power, energy (from the
charger's own `Yield/User` counter — more accurate than a Riemann sum),
PV voltage, state, **plus computed Total Solar Power and Total Solar
Energy across all chargers**.

**Alternator** — current, voltage, power, input voltage per Orion unit,
with a 10-second expiry so stale readings clear when the vehicle is off.

**Tanks** — level (%), remaining (litres, converted from m³), capacity and
fluid type diagnostics.

## Installation

Installed and updated by the Clever Caravan App. Turn on
**Clever Caravan: Power** in the App's Configuration tab, then add it under
**Settings > Devices & services**.

Enter the GX device address (default `venus.local`). Username and password are
only needed if a Venus security profile is set. The portal ID is detected
automatically.

## Options

Settings → Devices & Services → Clever Caravan: Power → Configure:

- **Input current limit min/max** — match the shore breaker at each
  install (e.g. 9.5–30 A) so nobody can set an unsafe value.

## Requirements on the GX device

- MQTT enabled (Settings → Services → MQTT on LAN)
- Reboot button requires Venus OS 3.x+
- No keepalive automation needed — remove yours after migrating

## Migration tips

- Run alongside your YAML during testing; entities will be duplicated
  until you remove the YAML file and the bridge block.
- To keep long-term statistics (energy dashboards), rename the new
  entities' entity_ids to match your old ones after deleting the YAML.

## Roadmap

- **v0.2** — Victron Instant Readout BLE listener with MQTT/BLE fused
  entities (freshest source wins) for redundancy and sub-second updates
- **v0.3** — RedArc device support under the same integration
- CustomName support (auto-name tanks/temperature sensors from the
  names configured in VictronConnect/Venus)
