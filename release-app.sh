#!/usr/bin/env bash
# Usage: ./release-app.sh "what changed"
set -euo pipefail
[ $# -lt 1 ] && { echo "Usage: $0 \"what changed\""; exit 1; }

STASHED=false
if ! git diff --quiet || ! git diff --cached --quiet; then
  git stash push -u -m "release-app.sh" > /dev/null
  STASHED=true
fi
git pull --rebase
$STASHED && git stash pop

if git diff --quiet && git diff --cached --quiet; then
  echo "Nothing changed. Aborting without a version bump."
  exit 0
fi

V=$(grep '^version:' clever_caravan/config.yaml | grep -o '[0-9.]*')
N=$(echo "$V" | awk -F. '{print $1"."$2"."$3+1}')
sed -i "s/^version: .*/version: \"$N\"/" clever_caravan/config.yaml

printf "## %s\n- App %s: %s\n\n" "$N" "$N" "$1" | cat - clever_caravan/CHANGELOG.md > /tmp/cl
mv /tmp/cl clever_caravan/CHANGELOG.md

git add -A
git commit -m "App $N: $1"
git push
git tag "v$N"
git push --tags
echo "Released $V -> $N"
