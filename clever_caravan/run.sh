#!/usr/bin/with-contenv bashio
SRC=/integrations
DEST=/homeassistant/custom_components
MARKER=.clever_caravan_app
SUPERVISOR=http://supervisor
AUTH="Authorization: Bearer ${SUPERVISOR_TOKEN}"

WINDOW_START=$(bashio::config 'update_window_start')
WINDOW_HOURS=$(bashio::config 'update_window_hours')
INTERVAL=$(bashio::config 'check_interval_minutes')

in_window() {
  local now start end
  now=$(date +%s)
  start=$(date -d "today ${WINDOW_START}" +%s 2>/dev/null) || return 1
  end=$((start + WINDOW_HOURS * 3600))
  [ "$now" -ge "$start" ] && [ "$now" -lt "$end" ]
}

self_update() {
  local current latest
  curl -sSf -X POST -H "$AUTH" "$SUPERVISOR/store/reload" > /dev/null 2>&1
  current=$(curl -sSf -H "$AUTH" "$SUPERVISOR/addons/self/info" | jq -r .data.version)
  latest=$(curl -sSf -H "$AUTH" "$SUPERVISOR/addons/self/info" | jq -r .data.version_latest)
  if [ -n "$latest" ] && [ "$latest" != "null" ] && [ "$current" != "$latest" ]; then
    bashio::log.info "App update available: $current -> $latest. Updating."
    if curl -sSf -X POST -H "$AUTH" "$SUPERVISOR/store/addons/self/update" > /dev/null; then
      bashio::log.info "Update requested."
    else
      bashio::log.warning "Self-update failed. Check App permissions."
    fi
    return 0
  fi
  return 1
}

sync_integration() {
  local key=$1 domain=$2
  local src="$SRC/$domain" dst="$DEST/$domain"
  if bashio::config.true "$key"; then
    if [ -d "$dst" ] && [ ! -f "$dst/$MARKER" ]; then
      bashio::log.warning "$domain exists but is not managed by this App (HACS?). Skipping."
      return
    fi
    local new old=""
    new=$(jq -r .version "$src/manifest.json")
    [ -f "$dst/manifest.json" ] && old=$(jq -r .version "$dst/manifest.json")
    if [ "$new" != "$old" ]; then
      rm -rf "$dst" && cp -r "$src" "$dst" && touch "$dst/$MARKER"
      bashio::log.info "$domain: installed $new (was ${old:-none})"
      changed=true
    fi
  elif [ -f "$dst/$MARKER" ]; then
    rm -rf "$dst"
    bashio::log.info "$domain: removed"
    changed=true
  fi
}

sync_all() {
  changed=false
  sync_integration tpms clever_caravan_tpms
  sync_integration location clever_caravan_location
  sync_integration waymote clever_caravan_waymote
  sync_integration power clever_caravan_power
  sync_integration dashboard clever_caravan_dashboard
  sync_integration weather clever_caravan_weather

  if $changed; then
    bashio::log.info "Changes made. Restarting Home Assistant."
    curl -sSf -X POST -H "$AUTH" "$SUPERVISOR/core/restart" > /dev/null
  fi
}

bashio::log.info "Clever Caravan App started."
bashio::log.info "Update window ${WINDOW_START} for ${WINDOW_HOURS}h. Checking every ${INTERVAL}m."
mkdir -p "$DEST"

bashio::log.info "Startup sync."
sync_all

while true; do
  sleep "$((INTERVAL * 60))"
  if in_window; then
    self_update && continue
    sync_all
  fi
done
