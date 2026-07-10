#!/usr/bin/env bash
set -euo pipefail
VERSION=${1:?Usage: scripts/fleet-upgrade.sh VERSION RELEASE_MANIFEST}
RELEASE_MANIFEST=${2:-${SVS_RELEASE_MANIFEST:-}}
: "${RELEASE_MANIFEST:?Usage: scripts/fleet-upgrade.sh VERSION RELEASE_MANIFEST}"
MAX_CONCURRENT=${MAX_CONCURRENT:-3}
find instances -name instance.yaml -not -path '*/_templates/*' -print0 | xargs -0 -n1 -P "$MAX_CONCURRENT" -I{} bash scripts/deploy-instance.sh {} "$RELEASE_MANIFEST" "$VERSION"
