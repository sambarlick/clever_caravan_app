# Temporary patches

Band-aids that must be removed once the proper fix lands. Search the code for the tag.

## TEMP-DCX — OzXcorp DCX inverter via MQTT (Client X)

- **Added:** v0.1.16
- **Where:** `frontend/dist/cc-dashboard.js`, search `TEMP-DCX`
- **What:** Overview Power panel reads Client X's DCX Inverter directly from its
  MQTT discovery entities (unique IDs `ozxcorp_dcx_*`), and keeps the DCX relay
  switch out of Controls. The DCX Battery (BMS) device is ignored (currently dead).
- **Why temporary:** hardware knowledge belongs in `clever_caravan_power`, not the
  dashboard. The dashboard should only read Clever Caravan's standard keys.
- **Proper fix:** add a DCX backend to `clever_caravan_power` that publishes the
  standard keys (`battery_soc`, `battery_voltage`, `pv_power`, `shore_power`,
  `ac_consumption`) plus a generic inverter on/off switch.
- **Removal steps:**
  1. Ship the Power DCX backend; confirm Client X's Power panel fills from it.
  2. Delete every `TEMP-DCX` block in `cc-dashboard.js`, keeping the generic
     inverter-switch button support (move it onto a standard Power key).
  3. Disable the old `ozxcorp_dcx_*` MQTT discovery entities on Client X.
  4. Remove this section.
