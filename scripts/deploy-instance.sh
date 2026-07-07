#!/usr/bin/env bash
set -euo pipefail
MANIFEST=${1:?Usage: scripts/deploy-instance.sh instances/expert-ai-services/prod/instance.yaml [version]}
VERSION=${2:-}
AGENT=${SVS_AGENT_URL:-http://localhost:8090}
python - <<PY >/tmp/svs_deploy_body.json
import json
print(json.dumps({"manifest_path":"$MANIFEST", "version":"$VERSION" or None, "dry_run": False}))
PY
curl -fsS -X POST "$AGENT/agent/v1/instances/deploy" -H 'Content-Type: application/json' -d @/tmp/svs_deploy_body.json | python -m json.tool
