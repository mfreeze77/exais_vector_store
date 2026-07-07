#!/usr/bin/env bash
set -euo pipefail
VERSION=${1:?Usage: scripts/fleet-upgrade.sh 1.2.3}
MAX_CONCURRENT=${MAX_CONCURRENT:-3}
find instances -name instance.yaml -not -path '*/_templates/*' -print0 | xargs -0 -n1 -P "$MAX_CONCURRENT" -I{} bash scripts/deploy-instance.sh {} "$VERSION"
