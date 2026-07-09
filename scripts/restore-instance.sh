#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/restore-instance.sh [--preflight-only] backups/<bundle>.tar.gz [restore-dir]

Options:
  --preflight-only   Extract and validate the backup manifest/checksums only.
                    Does not require DATABASE_URL_SYNC and does not run pg_restore.
EOF
}

PREFLIGHT_ONLY=0
BUNDLE=""
RESTORE_DIR="restore-work"
RESTORE_DIR_SET=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --preflight-only)
      PREFLIGHT_ONLY=1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    -*)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
    *)
      if [[ -z "$BUNDLE" ]]; then
        BUNDLE="$1"
      elif [[ "$RESTORE_DIR_SET" -eq 0 ]]; then
        RESTORE_DIR="$1"
        RESTORE_DIR_SET=1
      else
        echo "Unexpected argument: $1" >&2
        usage >&2
        exit 2
      fi
      ;;
  esac
  shift
done

if [[ -z "$BUNDLE" ]]; then
  usage >&2
  exit 2
fi

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
ROOT_DIR=$(cd "$SCRIPT_DIR/.." && pwd)

mkdir -p "$RESTORE_DIR"
tar -C "$RESTORE_DIR" -xzf "$BUNDLE"
BUNDLE_LIST="$RESTORE_DIR/.bundle-contents.txt"
tar -tzf "$BUNDLE" > "$BUNDLE_LIST"
BUNDLE_TOP=$(sed -n '1{s#/.*##;p;q;}' "$BUNDLE_LIST")
BUNDLE_DIR="$RESTORE_DIR/$BUNDLE_TOP"

if [[ -f "$BUNDLE_DIR/manifest.json" ]]; then
  python "$ROOT_DIR/scripts/release/backup_common.py" validate "$BUNDLE_DIR/manifest.json" --print-artifacts
else
  echo "No backup manifest found; falling back to legacy CHECKSUMS.sha256 verification." >&2
fi

if [[ -f "$BUNDLE_DIR/CHECKSUMS.sha256" ]]; then
  ( cd "$BUNDLE_DIR" && sha256sum -c CHECKSUMS.sha256 )
fi

if [[ "$PREFLIGHT_ONLY" -eq 1 ]]; then
  echo "Restore preflight completed for $BUNDLE_DIR. No restore commands were run."
  exit 0
fi

if [[ -f "$BUNDLE_DIR/postgres/svs.dump" ]]; then
  : "${DATABASE_URL_SYNC:?Set DATABASE_URL_SYNC before restoring Postgres dump}"
  pg_restore --clean --if-exists --no-owner --dbname "$DATABASE_URL_SYNC" "$BUNDLE_DIR/postgres/svs.dump"
fi

echo "Verified bundle at $BUNDLE_DIR. Qdrant/OpenSearch snapshots, if present, must be restored with their cluster-specific APIs."
