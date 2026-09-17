#!/usr/bin/env bash
set -euo pipefail
BACKUP_DIR="${BACKUP_DIR:-$PWD/backups}"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$BACKUP_DIR/app_state_${TIMESTAMP}.tar.gz"
mkdir -p "$BACKUP_DIR"

items=()
[[ -d backend/ontology_studio/workspace ]] && items+=(backend/ontology_studio/workspace)
[[ -d backend/multi_org/workspace ]] && items+=(backend/multi_org/workspace)
[[ -d backend/ingestion/plans ]] && items+=(backend/ingestion/plans)
[[ -f VERSION ]] && items+=(VERSION)
[[ -f backend/production/release_manifest.json ]] && items+=(backend/production/release_manifest.json)

if [[ ${#items[@]} -eq 0 ]]; then
  echo "No application state files found to back up."
  exit 1
fi

tar -czf "$OUT" "${items[@]}"
echo "Application metadata/state backup created: $OUT"
echo ".env and secrets are intentionally NOT included."
