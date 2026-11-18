# Clever Caravan fleet telemetry (Phase 1: read-only, rig -> VPS).
# Sourced by run.sh. Publishes cc/<rig_id>/telemetry (retained) over TLS with
# the rig's client certificate. Contains no location data.

FLEET_DIR=/data/fleet
FLEET_ENABLED=false
LAST_UPDATE_FILE=/data/.last_update
TELEMETRY_SCHEMA=1

fleet_setup() {
  local code
  code=$(bashio::config 'fleet_enrolment')
  if [ -z "$code" ] || [ "$code" = "null" ]; then
    bashio::log.info "Fleet telemetry off (no enrolment code)."
    return
  fi
  local json
  if ! json=$(echo "$code" | base64 -d 2>/dev/null) || ! echo "$json" | jq -e '.v == 1' > /dev/null 2>&1; then
    bashio::log.warning "Fleet enrolment code is not valid. Telemetry off."
    return
  fi
  mkdir -p "$FLEET_DIR" && chmod 700 "$FLEET_DIR"
  echo "$json" | jq -r .ca > "$FLEET_DIR/ca.crt"
  echo "$json" | jq -r .cert > "$FLEET_DIR/rig.crt"
  (umask 077; echo "$json" | jq -r .key > "$FLEET_DIR/rig.key")
  FLEET_RIG=$(echo "$json" | jq -r .rig_id)
  FLEET_HOST=$(echo "$json" | jq -r .host)
  FLEET_PORT=$(echo "$json" | jq -r .port)
  FLEET_ENABLED=true
  bashio::log.info "Fleet telemetry on: rig '${FLEET_RIG}' -> ${FLEET_HOST}:${FLEET_PORT}."
}

iso() { date -u -d "@$1" +%Y-%m-%dT%H:%M:%SZ; }

# Next time the sync loop will actually check (it only acts inside the window).
next_check_estimate() {
  local ts=$1 start end
  start=$(date -d "$(date -d "@$ts" +%F) ${WINDOW_START}" +%s 2>/dev/null) || { echo "$ts"; return; }
  end=$((start + WINDOW_HOURS * 3600))
  if [ "$ts" -lt "$start" ]; then echo "$start"
  elif [ "$ts" -lt "$end" ]; then echo "$ts"
  else echo $((start + 86400)); fi
}

sv() { # Supervisor GET -> .data as JSON, or {} on any failure (e.g. os/info off HAOS)
  local out
  out=$(curl -sSf -H "$AUTH" "$SUPERVISOR/$1" 2>/dev/null | jq -c '.data // {}' 2>/dev/null)
  [ -n "$out" ] && echo "$out" || echo '{}'
}

fleet_publish() {
  $FLEET_ENABLED || return 0
  local now app core os sup ha_facts integrations last_update restart next
  now=$(date +%s)
  app=$(sv addons/self/info)
  core=$(sv core/info)
  os=$(sv os/info)
  sup=$(sv supervisor/info)

  # Load state, tier and GPS health come from HA itself.
  ha_facts=$(jq -Rs '{template: .}' /telemetry.j2 \
    | curl -sSf -X POST -H "$AUTH" -H "Content-Type: application/json" -d @- \
      "$SUPERVISOR/core/api/template" 2>/dev/null)
  echo "$ha_facts" | jq -e . > /dev/null 2>&1 || ha_facts='{}'

  integrations='{}'
  local key domain enabled installed bundled
  for pair in tpms:clever_caravan_tpms location:clever_caravan_location \
              waymote:clever_caravan_waymote power:clever_caravan_power \
              dashboard:clever_caravan_dashboard weather:clever_caravan_weather \
              core:clever_caravan_core; do
    key=${pair%%:*}; domain=${pair#*:}
    enabled=$(bashio::config.true "$key" && echo true || echo false)
    installed=$(jq -r .version "$DEST/$domain/manifest.json" 2>/dev/null || echo "")
    [ "$enabled" = false ] && [ -z "$installed" ] && continue
    bundled=$(jq -r .version "$SRC/$domain/manifest.json" 2>/dev/null || echo "")
    integrations=$(echo "$integrations" | jq -c \
      --arg k "$key" --arg d "$domain" --argjson en "$enabled" \
      --arg inst "$installed" --arg bun "$bundled" --argjson ha "$ha_facts" \
      '.[$k] = {
         enabled: $en,
         installed: (if $inst == "" then null else $inst end),
         bundled: (if $bun == "" then null else $bun end),
         state: (($ha.states[$d] // "unknown") | ascii_downcase | sub("^configentrystate\\."; ""))
       }')
  done

  last_update=null
  [ -f "$LAST_UPDATE_FILE" ] && last_update="\"$(iso "$(cat "$LAST_UPDATE_FILE")")\""
  restart=null
  [ -f "$PENDING" ] && restart="\"$(iso "$(next_check_estimate "$now")")\""
  next=$(iso "$(next_check_estimate "$NEXT_CHECK")")

  local payload
  payload=$(jq -cn \
    --argjson schema "$TELEMETRY_SCHEMA" --arg ts "$(iso "$now")" \
    --argjson app "$app" --argjson core "$core" --argjson os "$os" --argjson sup "$sup" \
    --argjson ints "$integrations" --argjson ha "$ha_facts" \
    --argjson last_update "$last_update" --argjson restart "$restart" --arg next "$next" \
    --argjson interval "$INTERVAL" --argjson heartbeat "$HEARTBEAT" \
    '{
      schema: $schema,
      ts: $ts,
      heartbeat_minutes: $heartbeat,
      app: {
        version: $app.version, latest: $app.version_latest,
        check_interval_minutes: $interval,
        last_update: $last_update, next_check: $next, restart_pending: $restart
      },
      ha: { core: $core.version, core_latest: $core.version_latest,
            os: $os.version, os_latest: $os.version_latest,
            supervisor: $sup.version, supervisor_latest: $sup.version_latest },
      integrations: $ints,
      dashboard: { tier: $ha.tier },
      gps: $ha.gps,
      bridges: {}
    }')

  if mosquitto_pub -h "$FLEET_HOST" -p "$FLEET_PORT" \
       --cafile "$FLEET_DIR/ca.crt" --cert "$FLEET_DIR/rig.crt" --key "$FLEET_DIR/rig.key" \
       -i "cc-${FLEET_RIG}" -q 1 -r -t "cc/${FLEET_RIG}/telemetry" -m "$payload" 2>/tmp/fleet.err; then
    bashio::log.debug "Telemetry sent."
  else
    bashio::log.warning "Telemetry not sent: $(tail -1 /tmp/fleet.err)"
  fi
}
