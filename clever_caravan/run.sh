#!/usr/bin/with-contenv bashio
SRC=/integrations
DEST=/homeassistant/custom_components
MARKER=.clever_caravan_app
changed=false
mkdir -p "$DEST"

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
    else
      bashio::log.info "$domain: $new already installed"
    fi
  elif [ -f "$dst/$MARKER" ]; then
    rm -rf "$dst"
    bashio::log.info "$domain: removed"
    changed=true
  fi
}

sync_integration tpms clever_caravan_tpms

if $changed; then
  bashio::log.info "Changes made. Restarting Home Assistant."
  curl -sSf -X POST -H "Authorization: Bearer ${SUPERVISOR_TOKEN}" \
    http://supervisor/core/restart
else
  bashio::log.info "No changes."
fi
