# Clever Caravan

Installs and keeps the Clever Caravan integrations up to date on this rig.
Integrations are bundled with the App, so updating the App updates them.

## Setup

1. Turn on the integrations this rig needs in the Configuration tab.
2. Save, then start the App.
3. The App installs them and restarts Home Assistant.
4. Add each integration under Settings > Devices & services.

## Options

**Integrations** - one switch per integration. Turning one off removes it from
this rig.

**Check interval (minutes)** - how often the App checks for changes. The default
is 5 minutes.

## Notes

- The App only manages integrations it installed itself. Anything installed by
  HACS is left alone and noted in the log.
- Home Assistant restarts only when something has actually changed.
- Progress and any problems are shown in the Log tab.

## Support

sam.smarthome.tech@gmail.com

## Fleet telemetry

Paste the rig's one-line code from `cc-pki.sh rig <rig_id>` into **Fleet enrolment
code**. The App then reports this rig's health to the Clever Caravan fleet every
15 minutes: App, Home Assistant and integration versions, whether each integration
loaded, dashboard tier, GPS dongle health, and update times.

No location, camera or usage data is sent. Leave the field empty to keep telemetry off.
