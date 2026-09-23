# Clever Caravan: Dashboard

Serves and auto-loads a bundled Home Assistant dashboard **strategy** that builds
the Clever Caravan dashboard from whatever hardware a unit actually reports, gated
by product tier. No manual resource entry, no third-party card dependencies.

## Requirements

- Home Assistant 2026.5 or newer (the strategy self-registers into the
  **Community dashboards** picker, which needs the 2026.5 strategy API).

## Install

Installed and updated by the Clever Caravan App. Turn on
**Clever Caravan: Dashboard** in the App's Configuration tab, then add it under
**Settings > Devices & services**.

## Set up

1. Settings → Devices & Services → **Add Integration** → *Clever Caravan Dashboard*.
2. Settings → Dashboards → **Add dashboard** → **Community dashboards** →
   *Clever Caravan*.
3. In the integration's options (⋮ → **Configure**): set the product **tier** and
   link any foreign entities the dashboard can't resolve automatically.

## How it works

- The integration serves its own JS module and loads it on every frontend page,
  and exposes a **config sensor** carrying the tier and the role map.
- The strategy reads that sensor, then resolves the entities it needs off each
  entity's `translation_key` (rename-proof, and the only stable key exposed to
  the frontend registry). Foreign entities are resolved via the options-flow map.
- Upgrading a unit is a tier flip in the options, not a redeploy.

Owned entities must carry a `translation_key` matching the role tokens used in
`custom_components/clever_caravan_dashboard/frontend/dist/cc-dashboard.js`.
Unresolved roles render a visible placeholder rather than vanishing.

## Tier enforcement

The dashboard tier gate is a **UX** layer only. A premium feature must also not
exist as a live entity on a base unit — enforce that in the producing
integrations, not here.
