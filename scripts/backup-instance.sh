#!/usr/bin/env bash
set -euo pipefail

MANIFEST=${1:?Usage: scripts/backup-instance.sh instances/expert-ai-services/prod/instance.yaml [dest-root]}
DEST_ROOT=${2:-backups}
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
ROOT_DIR=$(cd "$SCRIPT_DIR/.." && pwd)
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
PRODUCT_VERSION=$(cat "$ROOT_DIR/VERSION" 2>/dev/null || echo unknown)

INSTANCE_NAME=$(
  python - "$MANIFEST" <<'PY'
from __future__ import annotations

import re
import sys
from pathlib import Path

try:
    import yaml
except Exception:
    yaml = None

path = Path(sys.argv[1])
metadata = {}
if yaml is not None and path.exists():
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if isinstance(data, dict):
        metadata = data.get("metadata") or {}
name = metadata.get("name") or metadata.get("instanceId") or path.parent.name or path.stem
print(re.sub(r"[^A-Za-z0-9_.-]+", "-", str(name)).strip("-") or "instance")
PY
)

BUNDLE_ID="${INSTANCE_NAME}-${STAMP}"
DEST="$DEST_ROOT/$BUNDLE_ID"
mkdir -p "$DEST/postgres" "$DEST/qdrant" "$DEST/opensearch" "$DEST/object-store" "$DEST/config" "$DEST/audit"
cp "$MANIFEST" "$DEST/instance.yaml"
cp "$MANIFEST" "$DEST/config/instance.yaml"

write_marker() {
  local path="$1"
  local kind="$2"
  local status="$3"
  local message="$4"
  python - "$path" "$kind" "$status" "$message" <<'PY'
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

path = Path(sys.argv[1])
kind = sys.argv[2]
status = sys.argv[3]
message = sys.argv[4]
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(
    json.dumps(
        {
            "kind": kind,
            "capture_status": status,
            "message": message,
            "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        },
        indent=2,
        sort_keys=True,
    )
    + "\n",
    encoding="utf-8",
)
PY
}

write_config_metadata() {
  python - "$DEST/config/config-metadata.json" "$MANIFEST" "$INSTANCE_NAME" "$PRODUCT_VERSION" <<'PY'
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

target = Path(sys.argv[1])
payload = {
    "capture_status": "captured",
    "source_manifest": sys.argv[2],
    "instance_name": sys.argv[3],
    "product_version": sys.argv[4],
    "notes": "Config metadata records paths and version only; secret values are not expanded into this manifest.",
    "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
}
target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
}

if [[ -n "${DATABASE_URL_SYNC:-}" ]]; then
  if ! command -v pg_dump >/dev/null 2>&1; then
    echo "DATABASE_URL_SYNC is set but pg_dump is not available." >&2
    exit 1
  fi
  pg_dump "$DATABASE_URL_SYNC" --format=custom --file "$DEST/postgres/svs.dump"
else
  write_marker "$DEST/postgres/metadata-unavailable.json" "postgres_metadata" "not_configured" "DATABASE_URL_SYNC was not set; this local bundle carries a metadata marker for restore preflight only."
fi

if [[ -n "${QDRANT_URL:-}" ]]; then
  if command -v curl >/dev/null 2>&1 && curl -fsS -X POST "$QDRANT_URL/collections/snapshots" -o "$DEST/qdrant/snapshot-create-response.json"; then
    :
  else
    write_marker "$DEST/qdrant/vectors-unavailable.json" "qdrant_vectors" "capture_failed" "QDRANT_URL was set, but Qdrant snapshot metadata could not be captured."
  fi
else
  write_marker "$DEST/qdrant/vectors-unavailable.json" "qdrant_vectors" "not_configured" "QDRANT_URL was not set; this local bundle carries a vector marker for restore preflight only."
fi

if [[ -n "${OPENSEARCH_URL:-}" ]]; then
  if command -v curl >/dev/null 2>&1 && curl -fsS "$OPENSEARCH_URL/_cat/indices?format=json" -o "$DEST/opensearch/indices.json"; then
    :
  else
    write_marker "$DEST/opensearch/sparse-unavailable.json" "opensearch_sparse" "capture_failed" "OPENSEARCH_URL was set, but sparse index metadata could not be captured."
  fi
else
  write_marker "$DEST/opensearch/sparse-unavailable.json" "opensearch_sparse" "not_configured" "OPENSEARCH_URL was not set; this local bundle carries a sparse-index marker for restore preflight only."
fi

OBJECT_STORE_PATH=${SVS_LOCAL_OBJECT_STORE_PATH:-.svs-object-store}
if [[ -d "$OBJECT_STORE_PATH" ]]; then
  (cd "$OBJECT_STORE_PATH" && find . -type f -print | sort) > "$DEST/object-store/local-files.txt"
else
  write_marker "$DEST/object-store/object-store-unavailable.json" "object_store" "not_configured" "SVS_LOCAL_OBJECT_STORE_PATH did not point at a local object store; this bundle carries an object-store marker for restore preflight only."
fi

write_config_metadata

if [[ -n "${SVS_AUDIT_EXPORT_PATH:-}" && -f "${SVS_AUDIT_EXPORT_PATH:-}" ]]; then
  cp "$SVS_AUDIT_EXPORT_PATH" "$DEST/audit/audit-export.json"
else
  write_marker "$DEST/audit/audit-unavailable.json" "audit_export" "not_configured" "SVS_AUDIT_EXPORT_PATH was not set; this local bundle carries an audit marker for restore preflight only."
fi

(
  cd "$DEST"
  find . -type f ! -name manifest.json ! -name CHECKSUMS.sha256 -print0 | sort -z | xargs -0 sha256sum > CHECKSUMS.sha256
)
python "$ROOT_DIR/scripts/release/backup_common.py" write "$DEST"

tar -C "$DEST_ROOT" -czf "$DEST.tar.gz" "$(basename "$DEST")"
sha256sum "$DEST.tar.gz" > "$DEST.tar.gz.sha256"
echo "$DEST.tar.gz"
