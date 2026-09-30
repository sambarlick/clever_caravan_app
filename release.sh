#!/usr/bin/env bash
# Usage: ./release.sh <integration> [integration...] "changelog line"
set -euo pipefail

[ $# -lt 2 ] && { echo "Usage: $0 <integration> [integration...] \"changelog line\""; exit 1; }

NOTE="${!#}"
NAMES=("${@:1:$#-1}")
SRC_REPO=../clever_caravan_integrations/custom_components

STASHED=false
if ! git diff --quiet || ! git diff --cached --quiet; then
  git stash push -u -m "release.sh" > /dev/null
  STASHED=true
fi
git pull --rebase
$STASHED && git stash pop

SUMMARY=()
for name in "${NAMES[@]}"; do
  src="$SRC_REPO/clever_caravan_$name/"
  [ -d "$src" ] || { echo "No such integration: $name"; exit 1; }
  rsync -a --delete --exclude '__pycache__' "$src" "clever_caravan/integrations/clever_caravan_$name/"
  v=$(jq -r .version "clever_caravan/integrations/clever_caravan_$name/manifest.json")
  echo "$name -> $v"
  SUMMARY+=("$name $v")
done

if git diff --quiet && git diff --cached --quiet; then
  echo "Nothing changed. Aborting without a version bump."
  exit 0
fi

V=$(grep '^version:' clever_caravan/config.yaml | grep -o '[0-9.]*')
N=$(echo "$V" | awk -F. '{print $1"."$2"."$3+1}')
sed -i "s/^version: .*/version: \"$N\"/" clever_caravan/config.yaml

printf "## %s\n- %s\n\n" "$N" "$NOTE" | cat - clever_caravan/CHANGELOG.md > /tmp/cl
mv /tmp/cl clever_caravan/CHANGELOG.md

MSG="App $N: $(IFS=', '; echo "${SUMMARY[*]}")"
git add -A
git commit -m "$MSG"
git push
git tag "v$N"
git push --tags
echo "Released $V -> $N"
