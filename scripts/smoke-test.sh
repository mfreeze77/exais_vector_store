#!/usr/bin/env bash
set -euo pipefail
API=${API:-http://localhost:8080}
curl -fsS "$API/healthz" | python -m json.tool
curl -fsS "$API/api/v1/vectorization/modes" >/tmp/svs_modes.json
python - <<'PY'
import json
m=json.load(open('/tmp/svs_modes.json'))['modes']
print('modes:', ', '.join(sorted(m)[:8]))
PY
VS=$(curl -fsS -X POST "$API/v1/vector_stores" -H 'Content-Type: application/json' -d '{"name":"Smoke Store","knowledge_base_id":"kb_dev","attributes":{"purpose":"smoke"}}' | python -c 'import sys,json; print(json.load(sys.stdin)["id"])')
echo "Vector store: $VS"
curl -fsS -X POST "$API/api/v1/documents/ingest" -H 'Content-Type: application/json' -d "{\"vector_store_id\":\"$VS\",\"knowledge_base_id\":\"kb_dev\",\"title\":\"Smoke Doc\",\"filename\":\"smoke.md\",\"mime_type\":\"text/markdown\",\"mode\":\"markdown_docs_v1\",\"content\":\"# Smoke Test\\nThis document explains the sovereign vector store retrieval operating system.\\n## Security\\nThe LLM never decides authorization.\",\"security_level\":1}" | python -m json.tool
curl -fsS -X POST "$API/api/v1/retrieval/search" -H 'Content-Type: application/json' -d "{\"vector_store_id\":\"$VS\",\"query\":\"who decides authorization\",\"top_k\":3}" | python -m json.tool
