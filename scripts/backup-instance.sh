#!/usr/bin/env bash
set -euo pipefail
MANIFEST=${1:?Usage: scripts/backup-instance.sh instances/expert-ai-services/prod/instance.yaml [dest-root]}
DEST_ROOT=${2:-backups}
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
INSTANCE_NAME=$(python - <<PY
import yaml, sys
m=yaml.safe_load(open('$MANIFEST'))
print(m.get('metadata',{}).get('name') or m.get('metadata',{}).get('instanceId') or '$MANIFEST'.split('/')[-2])
PY
)
DEST="$DEST_ROOT/${INSTANCE_NAME}-${STAMP}"
mkdir -p "$DEST" "$DEST/postgres" "$DEST/qdrant" "$DEST/opensearch" "$DEST/object-store"
cp "$MANIFEST" "$DEST/instance.yaml"
cat > "$DEST/manifest.json" <<JSON
{"instance":"$INSTANCE_NAME","created_at":"$STAMP","source_manifest":"$MANIFEST","product_version":"$(cat VERSION 2>/dev/null || echo unknown)"}
JSON
if [[ -n "${DATABASE_URL_SYNC:-}" ]] && command -v pg_dump >/dev/null 2>&1; then
  pg_dump "$DATABASE_URL_SYNC" --format=custom --file "$DEST/postgres/svs.dump"
fi
if [[ -n "${QDRANT_URL:-}" ]]; then
  curl -fsS -X POST "$QDRANT_URL/collections/snapshots" -o "$DEST/qdrant/snapshot-create-response.json" || true
fi
if [[ -n "${OPENSEARCH_URL:-}" ]]; then
  curl -fsS "$OPENSEARCH_URL/_cat/indices?format=json" -o "$DEST/opensearch/indices.json" || true
fi
if [[ -d "${SVS_LOCAL_OBJECT_STORE_PATH:-.svs-object-store}" ]]; then
  (cd "${SVS_LOCAL_OBJECT_STORE_PATH:-.svs-object-store}" && find . -type f -print | sort) > "$DEST/object-store/local-files.txt" || true
fi
find "$DEST" -type f -print0 | sort -z | xargs -0 sha256sum > "$DEST/CHECKSUMS.sha256"
tar -C "$DEST_ROOT" -czf "$DEST.tar.gz" "$(basename "$DEST")"
sha256sum "$DEST.tar.gz" > "$DEST.tar.gz.sha256"
echo "$DEST.tar.gz"
