# Clever Caravan: Waymote

Home Assistant integration for the Waymote CAN-bus bridge.

It connects to the bridge over the LAN, reads the bridge's `config.json` (output
names, icons, enabled flags, and MQTT broker address), and registers the Waymote
as a device in Home Assistant, with entities for its outputs.

## Requirements

- A Waymote bridge running firmware that serves `GET/POST /api/config`.
- The bridge reachable from Home Assistant on its LAN address (default port 8080).

## Install

Installed and updated by the Clever Caravan App. Turn on
**Clever Caravan: Waymote** in the App's Configuration tab, then add it under
**Settings > Devices & services**.
