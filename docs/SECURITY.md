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

## Expert conversation persistence

Expert sessions and their messages, tool calls, retrieval runs, feedback,
memory events, and fork records use forced Postgres row-level security. Runtime
database context binds every row to tenant, business instance, API key, and
authenticated user; application queries repeat those checks explicitly. The
session key additionally partitions expert ID, caller external user ID, and
caller conversation ID.

Forks copy only prompt-relevant message, tool, and retrieval history. Feedback
and memory events remain separate governed records and are never citation
authority by themselves.

Feedback ownership fails closed across tenant, business instance, API key,
authenticated user, expert, caller external user, caller conversation, session,
and (when supplied) message ID. Application queries repeat the complete scope
even though forced RLS already enforces tenant/business/API-key/user boundaries.

Memory candidates are limited to retrieval strategy, answer style, and caller
preference. They have a confidence score and remain inert until a caller uses
the separate promotion route with explicit confirmation. Promotion and deletion
are audit-visible `expert_governance` events. Deletion retains a lifecycle
tombstone but scrubs the stored instruction payload. Forks do not copy feedback
or memory.

All feedback and candidate content passes the existing PII/secret output guard
before storage. Obvious PII and inline secret assignments are redacted;
secret-bearing structured fields, unsafe structured values, and citation
markers in memory are rejected. Audit metadata never contains the feedback
comment or memory instruction. Promoted memory enters synthesis only as an
explicitly non-authoritative style/preference instruction. It is never placed in
retrieved corpus context, and expert citations remain limited to validated
retrieval results.

Structured feedback and memory keys are reject-only when the key itself matches
PII or a secret indicator, including compound variants such as `client_secret`
and `aws_secret_access_key`. This validation lives in the shared persistence
boundary so bypassing the HTTP request schema cannot store an untyped feedback
category or unsafe structured content.
