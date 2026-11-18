# Clever Caravan: Core

Rig-wide modes and shared utilities for Clever Caravan. Installed and updated
by the Clever Caravan App.

## Hibernation

`switch.clever_caravan_hibernation`: turn on when the caravan is stowed for a
long period.

- Manual control only. Nothing in the integration acts on it; automations use
  it as a condition (suspend travel and occupancy automations, enable sentry
  ones).
- Survives Home Assistant restarts and power loss.
- Shown in the Controls panel of the Clever Caravan dashboard.

## Setup

Settings → Devices & services → Add integration → **Clever Caravan: Core**.
One click, nothing to configure.
