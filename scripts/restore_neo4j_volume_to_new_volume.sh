#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "Usage: $0 <backup.tar.gz> <new_volume_name>"
  exit 2
fi

BACKUP="$(realpath "$1")"
NEW_VOLUME="$2"
BACKUP_DIR="$(dirname "$BACKUP")"
BACKUP_FILE="$(basename "$BACKUP")"

if [[ ! -f "$BACKUP" ]]; then
  echo "Backup file not found: $BACKUP"
  exit 2
fi

if docker volume inspect "$NEW_VOLUME" >/dev/null 2>&1; then
  echo "Refusing to overwrite existing Docker volume: $NEW_VOLUME"
  exit 3
fi

docker volume create "$NEW_VOLUME" >/dev/null

docker run --rm \
  -v "$NEW_VOLUME:/data" \
  -v "$BACKUP_DIR:/backup:ro" \
  alpine:3.20 \
  sh -c "cd /data && tar -xzf /backup/$BACKUP_FILE"

echo "Restore complete into NEW volume: $NEW_VOLUME"
echo "No existing Neo4j volume was modified. Point a test container at this volume before cutover."
