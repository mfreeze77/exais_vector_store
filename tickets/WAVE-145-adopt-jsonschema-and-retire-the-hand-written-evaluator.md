# WAVE-145: Adopt jsonschema as a real dependency and retire the hand-written evaluator

Status: DONE 2026-09-13, landed_by (this commit). Parent: WAVE-134.

## Summary

Make `jsonschema` a declared dependency of this repository and delete the bounded
JSON Schema evaluator in
`packages/svs_common/svs_common/statecivics_record_adapter.py`, so StateCivics
contract records are validated by a maintained implementation of the
specification rather than by one we wrote.

## Background

WAVE-134 lane B needed to validate records against the two branches of the
pinned StateCivics retrieval-export contract. There is no `jsonschema` in this
repository -- not installed, not in any `requirements.txt` -- so the adapter
shipped a bounded evaluator covering the contract's keyword vocabulary.

Round one of that evaluator was cross-checked against `jsonschema` 4.26.0 over a
44-case mutation battery and reported zero disagreements. Quality control then
reproduced the cross-check independently, extended it to 93 cases and found
**six divergences: five fail-open, three reachable on the unmodified pinned
contract**. Two were decisive:

- `if value != schema["const"]` used Python equality, and `True == 1`. So
  `record_version: true` satisfied `const: 1` and was admitted as a valid entity
  projection -- through the kind/version gate the contract's own text calls
  "sufficient on its own to refuse an unknown kind or version".
- `format: date` was a shape regex, so `2026-02-31`, `2026-13-99` and
  `0000-99-99` all passed, on both branches, through the real dispatch.

Every one of the six sat inside a keyword class the round-one battery nominally
covered. The battery covered keywords by NAME; the defects were in their
SEMANTICS. That is the same defect class WAVE-133's pin exists to stop, one
layer inside the check built to avoid it.

WAVE-134's round-two patch fixed the four named keywords semantically, split the
vocabulary into exact/approximated/annotation sets, and added a disclosure
channel for what is still approximated. That closed the findings. It did not
change the standing exposure, which is the point of this ticket: **a validator we
maintain by hand is a standing invitation to this defect class.** The next
divergence will also sit inside something the battery "covers", and it will also
be found by someone else, later, after it has been trusted. The dependency is
the fix; the round-two patch is the bridge.

## Scope

- Add `jsonschema` (and `rfc3339-validator`, which is what makes `format:
  date-time` assert at all) to the dependency sets that ship `svs_common`:
  `apps/api`, `apps/worker`, `apps/model_gateway`, `apps/instance_agent`. Pin
  exact versions, as `PyYAML==6.0.2` already is.
- Replace `validate`, `_validate`, `_probe`, `_json_equal`, `_equality_key`,
  `_valid_date`, `_valid_date_time`, `_type_matches`, `_check_keywords` and the
  `EXACT_KEYWORDS` / `APPROXIMATED_KEYWORDS` / `ANNOTATION_KEYWORDS` /
  `KNOWN_KEYWORDS` / `APPROXIMATION_TOKENS` / `EXACT_FORMATS` sets with a
  `Draft202012Validator` built once per contract.
- Keep the remote-`$ref` policy EXACTLY as it is. `branch_closure` does not
  follow a remote ref because it names a separate contract with its own pin, and
  `RecordValidation.unvalidated_remote_refs` reports every one not followed.
  Under `jsonschema` this becomes a `referencing` registry of deliberate
  always-true stubs plus the same disclosure tuple. Resolving the KS-600
  contracts for real is a SEPARATE decision with its own pin, not a side effect
  of adopting a library.
- Delete `RecordValidation.unsupported_keyword_semantics` and its test only when
  the tuple is provably empty -- `pattern` stays approximate even under
  `jsonschema`, which also uses Python `re` rather than ECMA-262, so the honest
  outcome is probably that the channel SURVIVES with `pattern` in it and
  `format:uri` removed.
- Keep every behavioural test in `tests/test_statecivics_record_adapter.py`
  green unchanged. They assert branch routing, refusal messages and collection
  separation, none of which this ticket touches. The tests that assert the
  keyword-set partition go with the sets.

## Out Of Scope

- Any change to `load_manifest`, its signature, or its contract-pin enforcement.
- Any change to the dispatch derivation, the per-branch pins, or
  `statecivics_contract_pin.py`.
- Resolving the remote KS-600 `$ref`s. See Scope.
- Vendoring. A vendored copy is a hand-maintained validator with extra steps.
- Any live ingestion, embedding spend or store write.

## Prior Art

- **Code** — [packages/svs_common/svs_common/statecivics_record_adapter.py](../packages/svs_common/svs_common/statecivics_record_adapter.py): the evaluator to retire, and the docstring section stating precisely what it approximates and why. Shared file owner: WAVE-134. Edit sequence: WAVE-134 → WAVE-145.
- **Code** — [tests/test_statecivics_record_adapter.py](../tests/test_statecivics_record_adapter.py): the semantic tests that must stay green. Shared file owner: WAVE-134. Edit sequence: WAVE-134 → WAVE-145.
- **Config** — `apps/*/requirements.txt`: `PyYAML==6.0.2` is the precedent for a pinned shared dependency used from `svs_common`.
- **Upstream** — StateCivics `tests/unit/civic_impact/test_entity_projection_contract.py` at `314beafe` already validates this same contract with `Draft202012Validator` + `FormatChecker` + a `referencing` `Registry`. That is the shape to copy; it is the producer's own validation of the same document.

## Acceptance Criteria

- `jsonschema` and `rfc3339-validator` are pinned in every requirements set that
  ships `svs_common`, and the adapter imports `jsonschema` at module scope.
- The hand-written evaluator is deleted, not deprecated in place.
- The round-two semantic battery (six boundaries: bool-vs-number, int-vs-float,
  date-calendar, datetime-calendar, uniqueitems-nested, whole-record fixtures)
  is re-run against the new implementation and reports zero disagreements --
  trivially, since both sides become the same library. Its real job afterwards
  is to be RETAINED as a regression suite in the repository, no longer needing a
  scratch venv, so the boundaries stay covered by something that runs in CI.
- `RecordValidation.unvalidated_remote_refs` returns the same three refs for the
  same fixtures, byte for byte.
- Full-suite failing-test-ID sets are identical to the pre-change baseline in
  BOTH regimes (corpus vars set and unset), stated with the regime beside each
  count.

## Verification

```sh
# regime: corpus vars UNSET
pytest -q
# regime: corpus vars SET (SVS_STATUTE_EXPORT_ROOT, SVS_STATUTE_CORPUS_ROOT,
#                          SVS_STATUTE_CUSTODY_ROOT, SVS_STATUTE_ROLLOUT_SEED)
pytest -q
```

Compare failing ID sets as sets, in both directions, per regime.

## Risks

Adding a dependency to four requirements sets touches the image build for every
app. `jsonschema` pulls `attrs`, `referencing`, `jsonschema-specifications` and
`rpds-py`; `rpds-py` is a compiled wheel, so the platform matrix must be
confirmed before this lands rather than after.

## Rollback

Revert the commit. The evaluator is deleted in one place and restored in one
place; nothing else depends on it.

## Implementation Log

Filed by WAVE-134 lane B round two, in the same commit that names it, alongside
the round-two evaluator fixes this ticket supersedes.

**2026-09-13 — done, in WAVE-134 lane B round three.** The owner pulled this
forward: round two's patched evaluator is not patched further, it is deleted.

* `jsonschema==4.25.1` and `rfc3339-validator==0.1.4` pinned in all four
  `apps/*/requirements.txt`. 4.25.1 matches repo A's `pyproject.toml:56` and
  `poetry.lock`, so producer and consumer judge the same record by the same
  implementation — which is what the composition milestone rests on.
* Every hand-written validation function is gone: `_validate`, `_probe`,
  `_json_equal`, `_equality_key`, `_valid_date`, `_valid_date_time`,
  `_type_matches`, `_check_keywords`, `_Disclosures`, and the
  `EXACT_KEYWORDS` / `APPROXIMATED_KEYWORDS` / `APPROXIMATION_TOKENS` /
  `EXACT_FORMATS` sets. `validate` now builds a `Draft202012Validator`.
* `FormatChecker` is passed EXPLICITLY, because draft 2020-12 makes `format` an
  annotation by default — a validator built without one calls `2026-02-31` a
  valid `date`. Which formats actually assert is READ from the registry into
  `ASSERTED_FORMATS`, not assumed.
* The vocabulary guard SURVIVES, now derived from
  `Draft202012Validator.VALIDATORS` rather than hand-listed. `jsonschema`
  ignores an unrecognised keyword, exactly as the specification requires; that
  is correct of a validator and wrong of a consumer, so a typo
  (`dependentRequried`) is still refused by name. Conversely `dependentRequired`
  — which the old evaluator had to refuse — is now simply CHECKED, and a test
  asserts that.
* Remote-`$ref` policy unchanged: always-true `referencing` stubs, never
  resolution, and `unvalidated_remote_refs` reports each one. Same three refs,
  now correctly split per branch (`source-artifact` on the document branch, the
  two KS-600 contracts on the entity branch).
* **The recorded prediction held.** This ticket expected
  `unsupported_keyword_semantics` to SURVIVE with `pattern` in it, because
  `jsonschema` also uses Python `re` rather than ECMA-262. It did, and
  `format:uri` survived too for a different reason than before: `jsonschema`
  registers no `uri` checker without `rfc3987`, which is GPLv3 and not a
  dependency this product can take, so a `uri`-formatted field is now DECLARED
  AND NOT CHECKED rather than checked more strictly. Both entries are now
  properties of the library. The values are unchanged — `("pattern",)` for the
  entity branch, `("format:uri", "pattern")` for the document branch — and are
  now DERIVED from the branch subtree plus the checker registry rather than
  listed.
* The round-two cross-check battery is RETAINED IN THE REPOSITORY, as this
  ticket's acceptance criteria required, as `_SEMANTIC_BOUNDARIES` plus
  `test_semantic_boundaries` (41 cases over five boundaries). It no longer
  compares two implementations; its job now is to keep the boundaries covered
  by something that runs in CI. `test_every_semantic_boundary_carries_near_misses_and_controls`
  fails if any boundary becomes all-pass or all-refuse, so it cannot decay into
  a battery that proves nothing.

Not done here, and still open: the image rebuild. Adding a dependency changes
every app image, and `.env.images` records immutable digests. Building and
recording those is a release action with its own approval; this commit changes
the requirements sets only. See the WAVE-134 log for the exact gate.
