# WAVE-147: StateCivics' envelope/payload agreement helper is laxer than B's when called standalone

Status: filed 2026-09-13, not started. Filed AGAINST REPO A. Parent: WAVE-134.

## Summary

`validate_envelope_payload_agreement` in repo A is a public helper that returns
"agreed" for three inputs B's equivalent refuses. It is not a live defect —
ordering in A's real pipeline masks all three, and that was verified — but a
public helper that is only correct because of where it happens to be called is
one refactor away from being wrong.

## Background

WAVE-134 built the same rule on B's side after quality control found that a
record whose envelope said `published` while its payload said `candidate`
satisfied both schemas and reached the embedding and index callbacks. JSON
Schema cannot express the relation: the envelope is validated against
`retrieval-export-record.schema.json` and the payload against its own KS-600
contract, and nothing relates them.

Both repositories now implement the rule, which is what makes them agree by
construction rather than by coincidence. Comparing the two implementations
surfaced three asymmetries, all in the same direction — A laxer than B.

## The three gaps

1. **Silent return on an unknown `entity_type`.** A returns without comparing
   anything when the type is not one it recognises. B refuses, on the ground
   that an unknown type is not evidence that the two halves agree. A record with
   a future or mistyped `entity_type` therefore passes A's helper unchecked.

2. **`payload.get(...)` yields `None` instead of refusing.** When the payload
   lacks the field being compared, A compares the envelope's value against
   `None` — so a payload with no `status` at all "disagrees" only if the
   envelope's status is also absent, and an envelope/payload pair can compare
   equal by both being missing. B refuses when the payload has no field to
   compare, because agreement cannot be established from an absence.

3. **Bare `!=`, so `True == 1` reads as agreement.** Python's `==` conflates
   booleans with numbers. An envelope `entity_revision` of `1` and a payload
   revision of `True` compare equal. B uses typed equality for exactly this
   reason — it is the same defect class WAVE-145 recorded in B's retired
   hand-written validator, where `record_version: true` satisfied `const: 1` and
   passed the contract's own kind/version gate.

## Why this is robustness, not a live defect

Verified: in A's real pipeline the helper is called after schema validation, and
the schemas already constrain `entity_type` to its enum, require the payload
fields, and type them. So none of the three is reachable through the pipeline
today. The exposure is that the helper is public, so the guarantee lives in the
call order rather than in the function, and nothing states that dependency.

## Scope

- Refuse an unknown `entity_type` rather than returning.
- Refuse when the payload lacks the field being compared, rather than comparing
  against `None`.
- Use typed equality: a boolean is never a number; an int and a float of equal
  mathematical value are equal, so a revision emitted as `2.0` still agrees
  with `2`.
- Either way, state in the docstring whether the helper may be called before
  schema validation. If it may not, the three fixes above are what make that
  claim survive somebody calling it anyway.

## Out Of Scope

- Any schema change. This is a cross-field rule over two documents that each
  contract already accepts, and it must move none of the three branch digests.
- B's implementation, which already does all three.
- The exporter's selection logic, which WAVE-134 item 7 covered.

## Prior Art

- **Repo A** — `src/kansas_accountability/services/civic_impact/entity_contract_validation.py`: `validate_envelope_payload_agreement`.
- **Repo B** — [packages/svs_common/svs_common/statecivics_record_adapter.py](../packages/svs_common/svs_common/statecivics_record_adapter.py): `assert_envelope_payload_agreement`, `_json_equal_scalar`, `PAYLOAD_AGREEMENT_KEYS` — the same rule with the three cases closed, and the refusal messages naming both values.
- **Repo B** — [tickets/WAVE-145-adopt-jsonschema-and-retire-the-hand-written-evaluator.md](WAVE-145-adopt-jsonschema-and-retire-the-hand-written-evaluator.md): the `True == 1` defect in its original form, and why it was expensive.

## Acceptance Criteria

- Each of the three inputs above is refused by A's helper, proved by a test that
  calls the helper DIRECTLY rather than through the pipeline — the pipeline is
  what currently hides them.
- A positive control: the two real HB 2513 revision-2 records still agree.
- The three branch digests are unchanged.
- The 26-record cross-repository comparison is re-run and still reports zero
  asymmetries.

## Verification

```sh
# repo A, via its own gate runner
scripts/run_gate.sh
```

## Risks

Low. Tightening a helper that nothing currently reaches with these inputs. The
only way it breaks a caller is if some caller was relying on the silent return
for an unknown `entity_type`, which would itself be the defect.

## Rollback

Revert the commit.

## Implementation Log

Filed by WAVE-134 lane B at the owner's direction, in the same commit that names
it, after a cross-repository comparison of the two implementations of the same
rule.
