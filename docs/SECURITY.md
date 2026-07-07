# Security Model

## Principle

The LLM never decides permissions. The vector database never decides final permissions. Postgres/policy code is the source of truth.

## Security levels

| Level | Label | Notes |
|---:|---|---|
| 0 | public | shared index acceptable |
| 1 | tenant_private | tenant/business scope required |
| 2 | team_restricted | group/role scope required |
| 3 | confidential | stricter output guard and provider restrictions |
| 4 | regulated_sensitive | private backend preferred/required |
| 5 | isolated_high_risk | dedicated data plane |

## Enforcement

1. Ingestion labels documents/chunks.
2. Retrieval scope derives from user/API key.
3. Qdrant/OpenSearch filters apply coarse security.
4. Postgres hydration performs final chunk-level verification.
5. Context pack only includes authorized chunks.

Embeddings, summaries, payloads, sparse indexes, and cached context are sensitive at the same level as the original text.
