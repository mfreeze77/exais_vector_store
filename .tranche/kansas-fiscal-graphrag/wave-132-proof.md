# WAVE-132 runtime implementation proof

**Historical mechanics proof; real-corpus acceptance reopened 2026-09-10.**
The real KanView corpus and fiscal document extraction outputs invalidate the
assumption that every graph entity can bind a PDF page/chunk. See
`docs/FISCAL_GRAPH_REAL_DATA.md` for the corrected design basis, real-source
audit and remaining implementation requirements. The results below do not
establish real law-to-money answer quality or deployment readiness.

Worktree: `/Users/mfrieson/Developer/exais-vector-store-ovh`.
Base: `bb7e575016ed398a6f9379d6bddf4bda0ca8639f`.
Ticket: `tickets/WAVE-132-fiscal-law-money-graphrag-runtime.md`.

## Scope

The ExAIS shared repository now contains a handler selected only by an exact
operator-owned fiscal cell/store/corpus/profile binding. The checked-in profile
template under the State Civics fiscal store is disabled. No court/Grant/Topeka
profile, running cell, production database, upstream publisher record, VPS, or
external model provider was modified or called by this implementation.

Implemented: strict six-node/five-relation graph validation and deterministic
identities; exact current document/chunk bindings; serialized immutable graph
generation staging; an explicit served-run selector; bounded one-hop expansion
through authorized current public evidence; original chunk citations and
directed relationship metadata; independent semantic search; publisher artifact
adapter and operator build/validate/load/evaluate CLI.

The complete synthetic chain exercises contains_appropriation, targets_account,
account_of_agency, account_in_fund, and documented_by in both directions. Tests
cover source changes/removal, current-version mismatch, private/inactive chunks,
group/role denial, denied supporting citations, exact/range/negative filters,
scope/run mismatch, immutable replay, staged second generations, same-document
distinct chunks and same-chunk relationships, fixture rejection, and exact API
dispatch. The API search integration replaces only external semantic seed
retrieval; graph SQL, RLS, hydration, file lookup and citation annotation run
against real PostgreSQL.

## Disposable database

Created only for this proof, with no host ports and Docker network `none`:

```sh
docker run -d --name exais-fiscal-graph-test-postgres --network none \
  --memory 768m --cpus 2 --label com.exais.task=fiscal-graphrag-proof \
  -e POSTGRES_USER=svs_owner -e POSTGRES_DB=fiscal_graph_test \
  -e POSTGRES_HOST_AUTH_METHOD=trust postgres:17
docker exec exais-fiscal-graph-test-postgres psql -U svs_owner \
  -d fiscal_graph_test -v ON_ERROR_STOP=1 \
  -c 'CREATE ROLE svs_app NOLOGIN NOSUPERUSER NOBYPASSRLS'
docker run --rm --platform linux/amd64 \
  --network container:exais-fiscal-graph-test-postgres --memory 2g --cpus 2 \
  -v /Users/mfrieson/Developer/exais-vector-store-ovh:/work:ro -w /work \
  -e PYTHONDONTWRITEBYTECODE=1 \
  -e DATABASE_URL_MIGRATIONS=postgresql+psycopg://svs_owner@127.0.0.1:5432/fiscal_graph_test \
  localhost:5000/expertaiservices-ovh/exai-vector-store-api:0.9.8-ovh-bb7e575 \
  alembic upgrade head
```

Migration completed successfully. Fixture transactions roll back. Runtime
load/search proof executes as `svs_app`, asserting superuser=false and
bypassrls=false. Privileged fixture withdrawal changes reset the role only for
that synthetic mutation and restore `svs_app` before retrieval.

After review, a database query found **0 synthetic fiscal/Grant test tenants**,
confirming fixture rollback. The owned disposable container and anonymous test
volume were removed with `docker rm -f -v exais-fiscal-graph-test-postgres`.
Existing cell and restoration containers were left running.

## Verification

Initial combined fiscal unit/API/adapter/PostgreSQL run: **96 passed**, two
existing FastAPI startup deprecation warnings. A preceding run found four test
setup errors because restricted RLS correctly prevented creating private or
inactive rows; fixture-only withdrawal setup was corrected as described above.

Final full suite: **1127 passed, 10 skipped, 3 warnings in 16.57s**. Both fiscal
and existing Grant PostgreSQL tests were enabled against the disposable DB.
Full output: `wave-132-test-output.txt` beside this proof (trailing whitespace
normalized when committed; output text otherwise unchanged). The 10 skips are
separate opt-in integration suites (expert sessions, source identity, worker,
and external StateCivics checkout compatibility). Warnings are existing
Starlette/AnyIO and FastAPI startup deprecations. No fiscal runtime test skipped.

```sh
docker run --rm --platform linux/amd64 \
  --network container:exais-fiscal-graph-test-postgres --memory 2g --cpus 2 \
  -v /Users/mfrieson/Developer/exais-vector-store-ovh:/work:ro -w /work \
  -e PYTHONDONTWRITEBYTECODE=1 \
  -e PYTHONPATH=/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent \
  -e SVS_FISCAL_GRAPH_TEST_DATABASE_URL=postgresql+psycopg://svs_owner@127.0.0.1:5432/fiscal_graph_test \
  -e SVS_GRANT_GRAPH_TEST_DATABASE_URL=postgresql+psycopg://svs_owner@127.0.0.1:5432/fiscal_graph_test \
  localhost:5000/expertaiservices-ovh/exai-vector-store-api:0.9.8-ovh-bb7e575 \
  python -m pytest -q -rs --tb=short -p no:cacheprovider
```

Host stdlib-only AST syntax check passed for all 11 changed/new Python files.
`git diff --check` passed. Adapter CLI help/compile and 23 focused adapter tests
also passed in the pinned image. No host dependencies were installed.

The historical independent QC returned **PASS WITH NOTES**; see
`wave-132-qc.md`. At that review the recorded note was the reviewed publisher-envelope
dependency described below. No real SB125 review, production corpus recall,
deployed runtime, or live activation is claimed by synthetic test success.

## Data and activation boundary

StateCivics must produce the actual reviewed versioned publisher envelope.
The adapter validates projection assertions, hashes, quote/page/current-chunk
bindings and runtime eligibility; canonical model semantics, source custody,
veto/override legal decisions and human review remain StateCivics-owned. The
runtime is additive and requires no schema migration. Serving real evidence
requires the actual fiscal store ID, mounted fiscal profile, reviewed artifact,
and matching `fiscal_graph_derivation_run_id` store attribute. Disable the
profile or invalidate the served run to withdraw graph service; semantic search
does not depend on graph configuration.
