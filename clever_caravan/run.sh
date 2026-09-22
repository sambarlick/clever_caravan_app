#!/usr/bin/with-contenv bashio
SRC=/integrations
DEST=/homeassistant/custom_components
MARKER=.clever_caravan_app
INTERVAL=$(bashio::config 'check_interval_minutes')

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

bashio::log.info "Clever Caravan App started. Checking every ${INTERVAL}m."
mkdir -p "$DEST"

while true; do
  changed=false
  sync_integration tpms clever_caravan_tpms
  sync_integration location clever_caravan_location

  if $changed; then
    bashio::log.info "Changes made. Restarting Home Assistant."
    curl -sSf -X POST -H "Authorization: Bearer ${SUPERVISOR_TOKEN}" \
      http://supervisor/core/restart > /dev/null
  fi
  sleep "$((INTERVAL * 60))"
done
