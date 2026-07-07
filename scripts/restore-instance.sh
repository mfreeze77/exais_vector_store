#!/usr/bin/env bash
set -euo pipefail
BUNDLE=${1:?Usage: scripts/restore-instance.sh backups/<bundle>.tar.gz [restore-dir]}
RESTORE_DIR=${2:-restore-work}
mkdir -p "$RESTORE_DIR"
tar -C "$RESTORE_DIR" -xzf "$BUNDLE"
BUNDLE_DIR="$RESTORE_DIR/$(tar -tzf "$BUNDLE" | head -1 | cut -d/ -f1)"
( cd "$BUNDLE_DIR" && sha256sum -c CHECKSUMS.sha256 )
if [[ -f "$BUNDLE_DIR/postgres/svs.dump" ]]; then
  : "${DATABASE_URL_SYNC:?Set DATABASE_URL_SYNC before restoring Postgres dump}"
  pg_restore --clean --if-exists --no-owner --dbname "$DATABASE_URL_SYNC" "$BUNDLE_DIR/postgres/svs.dump"
fi
echo "Verified bundle at $BUNDLE_DIR. Qdrant/OpenSearch snapshots, if present, must be restored with their cluster-specific APIs."
