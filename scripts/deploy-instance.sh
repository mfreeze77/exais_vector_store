#!/usr/bin/env bash
set -euo pipefail
MANIFEST=${1:?Usage: scripts/deploy-instance.sh INSTANCE_MANIFEST RELEASE_MANIFEST [version] [instance-env]}
RELEASE_MANIFEST=${2:?Usage: scripts/deploy-instance.sh INSTANCE_MANIFEST RELEASE_MANIFEST [version] [instance-env]}
VERSION=${3:-}
INSTANCE_ENV=${4:-}
AGENT=${SVS_AGENT_URL:-http://localhost:8090}
python - <<PY >/tmp/svs_deploy_body.json
import json
print(json.dumps({"manifest_path":"$MANIFEST", "release_manifest_path":"$RELEASE_MANIFEST", "env_file_path":"$INSTANCE_ENV" or None, "version":"$VERSION" or None, "dry_run": False}))
PY
curl -fsS -X POST "$AGENT/agent/v1/instances/deploy" -H 'Content-Type: application/json' -d @/tmp/svs_deploy_body.json | python -m json.tool
