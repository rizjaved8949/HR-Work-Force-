#!/usr/bin/env bash
set -euo pipefail

CONTAINER_NAME="${NEO4J_CONTAINER_NAME:-hr-neo4j}"
VOLUME_NAME="${NEO4J_VOLUME_NAME:-hr_neo4j_data}"
BACKUP_DIR="${BACKUP_DIR:-$PWD/backups}"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$BACKUP_DIR/${VOLUME_NAME}_${TIMESTAMP}.tar.gz"

mkdir -p "$BACKUP_DIR"

if docker ps --format '{{.Names}}' | grep -qx "$CONTAINER_NAME"; then
  echo "Stopping $CONTAINER_NAME for a consistent volume snapshot..."
  docker stop "$CONTAINER_NAME" >/dev/null
  RESTART=1
else
  RESTART=0
fi

cleanup() {
  if [[ "$RESTART" == "1" ]]; then
    docker start "$CONTAINER_NAME" >/dev/null || true
  fi
}
trap cleanup EXIT

docker run --rm \
  -v "$VOLUME_NAME:/data:ro" \
  -v "$BACKUP_DIR:/backup" \
  alpine:3.20 \
  sh -c "cd /data && tar -czf /backup/$(basename "$OUT") ."

echo "Neo4j volume backup created: $OUT"
