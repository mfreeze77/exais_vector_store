"""Offline document locator mechanics and opt-in retained Session Laws proof.

Synthetic strings exercise parser rejection, never legal or graph acceptance.
The real tests require a read-only SVS_FISCAL_SESSION_LAWS_ROOT mount; an
explicitly configured but missing corpus fails rather than silently skipping.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from svs_common.fiscal_graph_artifact import (
    DOCUMENT_PAGE_LINES_CONVENTION,
    DOCUMENT_PAGE_MARKER_LINES_CONVENTION,
    MAX_DOCUMENT_EXTRACTION_BYTES,
    MAX_DOCUMENT_QUOTE_CHARACTERS,
    FiscalGraphArtifactError,
    build_fiscal_graph_artifact,
    validate_built_artifact,
    verify_document_page_lines_evidence,
)

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/release/kansas-fiscal-graphrag.py"
EXTRACTION_SHA256 = "3c336e663f4f84fd6ae99b088be30ffa733a8a10118b8c602362bf1112934be7"
QUOTE_SHA256 = "3833a0e9a8eff099d9a070eb169ee36596ac9470d0d0bbc71b8eb36d9bca61c6"
# Independent expected text, preserving the extractor's em space, hyphenation,
# and three internal trailing spaces. This is a quote, not a copied corpus file.
SB125_QUOTE = (
    "(j)\u2003 On July 1, 2025, of the $601,800,000 appropriated for the above \n"
    "agency for the fiscal year ending June 30, 2026, by section 3(a) of chap-\n"
    "ter 111 of the 2024 Session Laws of Kansas from the state general fund \n"
    "in the supplemental state aid account (652-00-1000-0840), the sum of \n"
    "$4,000,000 is hereby lapsed."
)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _verify(raw=b"<!-- page 1 -->\nquote\n", quote="quote", **changes):
    args = {
        "extraction_bytes": raw, "expected_extraction_sha256": _sha(raw),
        "declared_page_count": 1, "page_1based": 1, "line_start_1based": 1,
        "line_end_1based": 1, "locator_convention": DOCUMENT_PAGE_LINES_CONVENTION,
        "quoted_text": quote, "expected_quote_sha256": _sha(quote.encode()),
    }
    args.update(changes)
    return verify_document_page_lines_evidence(**args)


def _cli():
    spec = importlib.util.spec_from_file_location("fiscal_document_evidence_cli", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _arguments(source, quote_file, raw, quote, *, page=1, start=1, end=1, pages=1):
    return [str(SCRIPT), "verify-document-evidence", "--extraction-md", str(source),
            "--extraction-sha256", _sha(raw), "--declared-page-count", str(pages), "--page", str(page),
            "--line-start", str(start), "--line-end", str(end), "--locator-convention", DOCUMENT_PAGE_LINES_CONVENTION,
            "--quote-text", str(quote_file), "--quote-sha256", _sha(quote.encode())]


def test_exact_lf_lines_preserve_blank_lines_whitespace_and_unicode_separators():
    raw = "préface\n<!-- page 1 -->\n\n  café\u2028form\fnext\x85space  \n\nend \n".encode()
    quote = "  café\u2028form\fnext\x85space  \n\nend "
    result = _verify(raw, quote, line_start_1based=2, line_end_1based=4)
    assert result["locator"] == {"page": 1, "line_start": 2, "line_end": 4}
    assert result["quote_sha256"] == _sha(quote.encode())
    assert result["quote_matches_locator"] is True
    offsets = result["resolved_offsets"]
    assert offsets["index_base"] == 0 and offsets["end_exclusive"] is True
    chars = offsets["artifact_unicode_codepoints"]
    byte_range = offsets["artifact_utf8_bytes"]
    assert raw.decode()[chars["start"]:chars["end"]] == quote
    assert raw[byte_range["start"]:byte_range["end"]] == quote.encode()
    assert chars["start"] != byte_range["start"]
    assert offsets["page_body_unicode_codepoints"]["start"] == 1


def test_last_line_without_lf_and_final_empty_line_have_precise_boundaries():
    assert _verify(b"<!-- page 1 -->\nquote")["quote_utf8_bytes"] == 5
    assert _verify(b"<!-- page 1 -->\nquote\n\n", "quote\n", line_end_1based=2)["quote_unicode_characters"] == 6
    with pytest.raises(FiscalGraphArtifactError, match="exceeds the selected page"):
        _verify(line_end_1based=2)
    with pytest.raises(FiscalGraphArtifactError, match="exceeds the selected page"):
        _verify(b"<!-- page 1 -->\n")


def test_marker_line_convention_preserves_marker_blank_lines_and_unicode_units():
    raw = "préface\n<!-- page 1 -->\n\n  café\u2028same line  \n".encode()
    quote = "<!-- page 1 -->\n\n  café\u2028same line  "
    result = _verify(raw, quote, line_end_1based=3,
                     locator_convention=DOCUMENT_PAGE_MARKER_LINES_CONVENTION)
    assert result["locator"] == {"page": 1, "line_start": 1, "line_end": 3}
    offsets = result["resolved_offsets"]
    assert offsets["page_local_origin"] == "page_marker_start"
    assert offsets["page_body_unicode_codepoints"] == {"start": 0, "end": len(quote)}
    assert offsets["page_body_utf8_bytes"] == {"start": 0, "end": len(quote.encode())}
    assert offsets["artifact_unicode_codepoints"]["start"] == len("préface\n")
    assert offsets["artifact_utf8_bytes"]["start"] == len("préface\n".encode())


def test_marker_line_convention_rejects_phantom_eof_line_and_empty_quote():
    args = {"locator_convention": DOCUMENT_PAGE_MARKER_LINES_CONVENTION,
            "line_start_1based": 2, "line_end_1based": 2}
    assert _verify(b"<!-- page 1 -->\nquote", **args)["quote_matches_locator"] is True
    assert _verify(**args)["quote_matches_locator"] is True
    with pytest.raises(FiscalGraphArtifactError, match="exceeds the selected page"):
        _verify(b"<!-- page 1 -->\n", **args)
    with pytest.raises(FiscalGraphArtifactError, match="exceeds the selected page"):
        _verify(line_start_1based=3, line_end_1based=3, locator_convention=DOCUMENT_PAGE_MARKER_LINES_CONVENTION)
    with pytest.raises(FiscalGraphArtifactError, match="1..65536 Unicode characters"):
        _verify(b"<!-- page 1 -->\n\n", "", **args)


def test_identical_quotes_at_distinct_locators_remain_distinct_without_invented_identity():
    raw = b"<!-- page 1 -->\nquote\n<!-- page 2 -->\nquote\n"
    first = _verify(raw, declared_page_count=2)
    second = _verify(raw, declared_page_count=2, page_1based=2)
    assert first["quote_sha256"] == second["quote_sha256"]
    assert first["locator"] != second["locator"]
    assert first["resolved_offsets"] != second["resolved_offsets"]
    for result in (first, second):
        assert result["evidence_only"] is True and result["publication_allowed"] is False
        assert result["raw_source_derivation_verified"] is False
        assert result["evidence_kind"] == "document_span" and result["span_type"] == "page_lines"
        for key in ("provision_id", "canonical_id", "source_revision_id", "source_span_id", "document_id", "chunk_id", "quoted_text"):
            assert key not in result
        with pytest.raises(FiscalGraphArtifactError, match="unsupported built artifact version"):
            validate_built_artifact(result)
        with pytest.raises(FiscalGraphArtifactError, match="unsupported fiscal publisher"):
            build_fiscal_graph_artifact(result, [], "vs_fiscal_test")


@pytest.mark.parametrize("field,maximum", [
    ("declared_page_count", 10000), ("page_1based", 10000),
    ("line_start_1based", 100000), ("line_end_1based", 100000),
])
@pytest.mark.parametrize("bad", [True, False, None, "1", 1.0, 0, -1, "over"])
def test_locator_fields_are_bounded_strict_integers(field, maximum, bad):
    with pytest.raises(FiscalGraphArtifactError, match="must be an integer"):
        _verify(**{field: maximum + 1 if bad == "over" else bad})


@pytest.mark.parametrize("changes", [{"page_1based": 2}, {"line_start_1based": 2, "line_end_1based": 1}])
def test_locator_order_and_declared_page_range(changes):
    with pytest.raises(FiscalGraphArtifactError, match="bounds are invalid"):
        _verify(**changes)


@pytest.mark.parametrize("convention", [None, True, {}, "page-lines", "", DOCUMENT_PAGE_LINES_CONVENTION + "-v2"])
def test_unknown_conventions_never_fall_back(convention):
    with pytest.raises(FiscalGraphArtifactError, match="unsupported document locator convention"):
        _verify(locator_convention=convention)


@pytest.mark.parametrize("raw,pages", [
    (b"quote\n", 1),
    (b"<!-- page 1 -->\nquote\n<!-- page 1 -->\nother\n", 2),
    (b"<!-- page 1 -->\nquote\n<!-- page 3 -->\nother\n", 2),
    (b"<!-- page 2 -->\nquote\n<!-- page 1 -->\nother\n", 2),
    (b"<!-- page 01 -->\nquote\n", 1),
    (b"<!-- page 1 -->\nquote\n<!-- PAGE 2 -->\nother\n", 1),
    (b"<!-- page 1 -->\nquote\n <!-- page 2 -->\n", 1),
    (b"<!-- page 1 -->\nquote\n<!-- page 2 -->", 1),
    (b"<!-- page 1 -->\nquote\ntext <!-- page 2 -->\n", 1),
    (b"<!-- page 1 -->\nquote\n<!--  page 2 -->\n", 1),
    (b"<!-- page 1 -->\r\nquote\r\n", 1),
    (b"<!-- page 1 -->\nquote\n<!-- page 2 -->\nother\n", 1),
    (b"<!-- page 1 -->\nquote\n", 2),
])
def test_missing_duplicate_out_of_order_extra_and_malformed_markers_reject(raw, pages):
    with pytest.raises(FiscalGraphArtifactError, match="marker|line endings"):
        _verify(raw, declared_page_count=pages)


@pytest.mark.parametrize("bad", ["text", bytearray(b"text"), None, b"a" * (MAX_DOCUMENT_EXTRACTION_BYTES + 1)])
def test_extraction_requires_bounded_bytes(bad):
    with pytest.raises(FiscalGraphArtifactError, match="bounded bytes"):
        _verify(extraction_bytes=bad)


@pytest.mark.parametrize("field", ["expected_extraction_sha256", "expected_quote_sha256"])
@pytest.mark.parametrize("bad", [None, "bad", "A" * 64])
def test_digest_shape_is_strict(field, bad):
    with pytest.raises(FiscalGraphArtifactError, match="lowercase SHA-256"):
        _verify(**{field: bad})


def test_matching_source_digest_does_not_allow_invalid_utf8_or_surrogate_quote():
    with pytest.raises(FiscalGraphArtifactError, match="valid UTF-8"):
        _verify(b"<!-- page 1 -->\n\xff\n")
    with pytest.raises(FiscalGraphArtifactError, match="valid UTF-8"):
        _verify(quoted_text="\ud800")


@pytest.mark.parametrize("quote", [None, True, b"quote", "", "q" * (MAX_DOCUMENT_QUOTE_CHARACTERS + 1)])
def test_quote_type_and_character_budget(quote):
    with pytest.raises(FiscalGraphArtifactError, match="Unicode characters"):
        _verify(quoted_text=quote)


@pytest.mark.parametrize("quote", ["café chapter", "cafe\u0301 chap-\nter ", "café chap-\nter", "café chap-\nter \n"])
def test_no_unicode_hyphenation_whitespace_or_final_newline_normalization(quote):
    raw = "<!-- page 1 -->\ncafé chap-\nter \n".encode()
    with pytest.raises(FiscalGraphArtifactError, match="does not select quoted_text exactly"):
        _verify(raw, quote, line_end_1based=2)


@pytest.mark.parametrize("raw,match", [
    (b"<!-- page 1 -->\nquote\n" + b"\n" * 1000000, "1000000 physical lines"),
    (b"<!-- page 1 -->\nquote\n" + b"\n" * 100000, "100000 physical lines"),
    (b"<!-- page 1 -->\n" + b"x" * 65537, "selected document quote exceeds"),
])
def test_line_and_selection_budgets_are_enforced_before_acceptance(raw, match):
    with pytest.raises(FiscalGraphArtifactError, match=match):
        _verify(raw)


def test_caller_quote_hash_agreement_is_not_locator_verification():
    raw = b"<!-- page 1 -->\nother clause\nquote\n"
    with pytest.raises(FiscalGraphArtifactError, match="does not select quoted_text exactly"):
        _verify(raw)
    with pytest.raises(FiscalGraphArtifactError, match="selected document quote hash mismatch"):
        _verify(expected_quote_sha256="0" * 64)


def test_changed_prefix_cannot_silently_shift_an_existing_revision():
    original = b"<!-- page 1 -->\nquote\n"
    with pytest.raises(FiscalGraphArtifactError, match="extraction hash mismatch"):
        _verify(b"new preface\n" + original, expected_extraction_sha256=_sha(original))


def test_cli_offline_success_has_no_runtime_or_credentials_path(tmp_path, monkeypatch, capsys):
    cli = _cli()
    raw, quote = b"<!-- page 1 -->\nexact \nquote\n", "exact \nquote"
    source, quote_file = tmp_path / "source.md", tmp_path / "quote.txt"
    source.write_bytes(raw); quote_file.write_bytes(quote.encode())

    def forbidden(*args, **kwargs):
        pytest.fail("document evidence verification entered a runtime/API path")

    for name in ("_call", "_safe_api", "validate_built_artifact", "build_fiscal_graph_artifact"):
        monkeypatch.setattr(cli, name, forbidden)
    monkeypatch.setattr(sys, "argv", _arguments(source, quote_file, raw, quote, end=2))
    assert cli.main() == 0
    output = capsys.readouterr().out
    result = json.loads(output)
    assert result["publication_allowed"] is False and result["raw_source_derivation_verified"] is False
    assert result["quote_matches_locator"] is True
    assert quote not in output and str(source) not in output


@pytest.mark.parametrize("mutation", ["wrong_lines", "trailing_lf", "invalid_utf8", "unknown_convention"])
def test_cli_errors_exit_nonzero_and_emit_no_success_or_quote(tmp_path, mutation):
    raw, quote = b"<!-- page 1 -->\nother\nexact quote\n", "exact quote"
    source, quote_file = tmp_path / "source.md", tmp_path / "quote.txt"
    source.write_bytes(raw); quote_file.write_bytes(quote.encode())
    args = _arguments(source, quote_file, raw, quote, start=2, end=2)
    if mutation == "wrong_lines":
        args[args.index("--line-start") + 1] = "1"
    elif mutation == "trailing_lf":
        quote_file.write_bytes(quote.encode() + b"\n")
    elif mutation == "invalid_utf8":
        quote_file.write_bytes(b"\xff")
    else:
        args[args.index("--locator-convention") + 1] = "guess"
    completed = subprocess.run([sys.executable, *args], capture_output=True, text=True, timeout=20)
    assert completed.returncode == 2
    assert not completed.stdout and "error:" in completed.stderr
    assert quote not in completed.stderr and "Traceback" not in completed.stderr


def test_cli_bounded_file_reads_reject_directory_and_oversized_quote(tmp_path):
    cli = _cli()
    with pytest.raises(ValueError, match="regular file"):
        cli._read_document_bytes(tmp_path, 1024, "Quote text")
    source = tmp_path / "huge.txt"
    with source.open("wb") as stream:
        stream.truncate(MAX_DOCUMENT_QUOTE_CHARACTERS * 4 + 1)
    with pytest.raises(ValueError, match="regular file"):
        cli._read_document_bytes(source, MAX_DOCUMENT_QUOTE_CHARACTERS * 4, "Quote text")


@pytest.fixture(scope="module")
def retained_session_laws():
    corpus = os.environ.get("SVS_FISCAL_SESSION_LAWS_ROOT")
    if not corpus:
        pytest.skip("requires retained Session Laws read-only mount via SVS_FISCAL_SESSION_LAWS_ROOT")
    source = Path(corpus) / "markdown/2025-Session-Laws-Book-2.md"
    assert source.is_file(), "explicitly required retained Session Laws artifact is missing"
    raw = source.read_bytes()
    assert _sha(raw) == EXTRACTION_SHA256
    assert _sha(SB125_QUOTE.encode()) == QUOTE_SHA256
    return source, raw


def _real(raw, **changes):
    args = {"expected_extraction_sha256": EXTRACTION_SHA256, "declared_page_count": 1072,
            "page_1based": 358, "line_start_1based": 30, "line_end_1based": 34,
            "expected_quote_sha256": QUOTE_SHA256}
    args.update(changes)
    return _verify(raw, SB125_QUOTE, **args)


def test_real_complete_sb125_clause_exact_locator_hash_and_units(retained_session_laws):
    _, raw = retained_session_laws
    result = _real(raw)
    assert result["verified_page_count"] == 1072
    assert result["extraction_byte_size"] == 2954698
    assert result["extraction_unicode_characters"] == 2938536
    assert result["quote_sha256"] == QUOTE_SHA256
    assert result["quote_unicode_characters"] == 314 and result["quote_utf8_bytes"] == 316
    assert result["locator"] == {"page": 358, "line_start": 30, "line_end": 34}
    offsets = result["resolved_offsets"]
    assert offsets["artifact_unicode_codepoints"] == {"start": 986097, "end": 986411}
    assert offsets["artifact_utf8_bytes"] == {"start": 992620, "end": 992936}
    assert offsets["page_body_unicode_codepoints"] == {"start": 1589, "end": 1903}
    assert result["publication_allowed"] is False and result["raw_source_derivation_verified"] is False


def test_real_two_explicit_conventions_select_same_quote_and_absolute_offsets(retained_session_laws):
    _, raw = retained_session_laws
    old = _real(raw)
    marker = _real(raw, line_start_1based=31, line_end_1based=35,
                   locator_convention=DOCUMENT_PAGE_MARKER_LINES_CONVENTION)
    assert old["locator"] == {"page": 358, "line_start": 30, "line_end": 34}
    assert marker["locator"] == {"page": 358, "line_start": 31, "line_end": 35}
    for result in (old, marker):
        assert result["quote_sha256"] == QUOTE_SHA256
        assert result["quote_unicode_characters"] == 314 and result["quote_utf8_bytes"] == 316
        assert result["resolved_offsets"]["artifact_unicode_codepoints"] == {"start": 986097, "end": 986411}
        assert result["resolved_offsets"]["artifact_utf8_bytes"] == {"start": 992620, "end": 992936}
        assert result["publication_allowed"] is False and result["raw_source_derivation_verified"] is False
    assert old["resolved_offsets"]["page_local_origin"] == "after_page_marker_lf"
    assert marker["resolved_offsets"]["page_local_origin"] == "page_marker_start"
    assert old["resolved_offsets"]["page_body_unicode_codepoints"] == {"start": 1589, "end": 1903}
    assert marker["resolved_offsets"]["page_body_unicode_codepoints"] == {"start": 1607, "end": 1921}
    assert (marker["resolved_offsets"]["page_body_utf8_bytes"]["start"]
            - old["resolved_offsets"]["page_body_utf8_bytes"]["start"]) == len(b"<!-- page 358 -->\n")


@pytest.mark.parametrize("convention,start,end", [
    (DOCUMENT_PAGE_MARKER_LINES_CONVENTION, 30, 34),
    (DOCUMENT_PAGE_LINES_CONVENTION, 31, 35),
    (DOCUMENT_PAGE_MARKER_LINES_CONVENTION, 26, 30),
])
def test_real_conventions_never_auto_adjust_wrong_or_neighboring_lines(retained_session_laws, convention, start, end):
    _, raw = retained_session_laws
    with pytest.raises(FiscalGraphArtifactError, match="does not select quoted_text exactly"):
        _real(raw, locator_convention=convention, line_start_1based=start, line_end_1based=end)


@pytest.mark.parametrize("mutation", ["wrong_hash", "duplicate_marker"])
def test_real_marker_line_convention_keeps_hash_and_unique_marker_requirements(retained_session_laws, mutation):
    _, raw = retained_session_laws
    changes = {"line_start_1based": 31, "line_end_1based": 35,
               "locator_convention": DOCUMENT_PAGE_MARKER_LINES_CONVENTION}
    if mutation == "wrong_hash":
        changes["expected_extraction_sha256"] = "0" * 64
        match = "extraction hash mismatch"
    else:
        raw = raw.replace(b"<!-- page 359 -->\n", b"<!-- page 358 -->\n")
        changes["expected_extraction_sha256"] = _sha(raw)
        match = "page markers must be unique and contiguous"
    with pytest.raises(FiscalGraphArtifactError, match=match):
        _real(raw, **changes)


@pytest.mark.parametrize("changes", [
    {"page_1based": 357},
    {"line_start_1based": 25, "line_end_1based": 29},
    {"line_end_1based": 33},
    {"line_start_1based": 31},
])
def test_real_wrong_page_neighboring_lapse_and_truncated_clause_reject(retained_session_laws, changes):
    _, raw = retained_session_laws
    with pytest.raises(FiscalGraphArtifactError, match="does not select quoted_text exactly"):
        _real(raw, **changes)


def test_real_adjacent_different_account_is_exactly_verifiable_but_not_the_requested_quote(retained_session_laws):
    _, raw = retained_session_laws
    # Independent selection from the explicitly named neighboring subsection.
    page = raw.decode().partition("<!-- page 358 -->\n")[2].partition("<!-- page 359 -->\n")[0]
    neighbor = "\n".join(page.split("\n")[24:29])
    assert "$156,085,651 is hereby lapsed." in neighbor and "652-00-1000-0820" in neighbor
    accepted = _real(raw, line_start_1based=25, line_end_1based=29,
                     quoted_text=neighbor, expected_quote_sha256=_sha(neighbor.encode()))
    assert accepted["quote_sha256"] != QUOTE_SHA256
    with pytest.raises(FiscalGraphArtifactError, match="does not select quoted_text exactly"):
        _real(raw, quoted_text=neighbor, expected_quote_sha256=_sha(neighbor.encode()))


@pytest.mark.parametrize("mutation", ["prefix", "amount", "expected_hash", "missing_marker"])
def test_real_changed_extraction_bytes_and_markers_reject(retained_session_laws, mutation):
    _, raw = retained_session_laws
    changes = {}
    match = "extraction hash mismatch"
    if mutation == "prefix":
        raw = b"edited preface\n" + raw
    elif mutation == "amount":
        raw = raw.replace(b"$4,000,000 is hereby lapsed.", b"$5,000,000 is hereby lapsed.")
    elif mutation == "expected_hash":
        changes["expected_extraction_sha256"] = "0" * 64
    else:
        raw = raw.replace(b"<!-- page 359 -->\n", b"")
        changes["expected_extraction_sha256"] = _sha(raw)
        match = "page markers must be unique and contiguous"
    with pytest.raises(FiscalGraphArtifactError, match=match):
        _real(raw, **changes)


def test_real_cli_verifies_without_emitting_the_appropriation_text(retained_session_laws, tmp_path, monkeypatch, capsys):
    source, raw = retained_session_laws
    quote_file = tmp_path / "sb125-quote.txt"
    quote_file.write_bytes(SB125_QUOTE.encode())
    monkeypatch.setattr(sys, "argv", _arguments(source, quote_file, raw, SB125_QUOTE, page=358, start=30, end=34, pages=1072))
    assert _cli().main() == 0
    output = capsys.readouterr().out
    result = json.loads(output)
    assert result["quote_sha256"] == QUOTE_SHA256 and result["quote_matches_locator"] is True
    assert "$4,000,000" not in output and "652-00-1000-0840" not in output
    assert result["publication_allowed"] is False


def test_real_cli_requires_explicit_marker_line_convention_for_lines31_to35(
    retained_session_laws, tmp_path, monkeypatch, capsys,
):
    source, raw = retained_session_laws
    quote_file = tmp_path / "sb125-quote.txt"
    quote_file.write_bytes(SB125_QUOTE.encode())
    args = _arguments(source, quote_file, raw, SB125_QUOTE, page=358, start=31, end=35, pages=1072)
    convention_index = args.index("--locator-convention") + 1
    args[convention_index] = DOCUMENT_PAGE_MARKER_LINES_CONVENTION
    monkeypatch.setattr(sys, "argv", args)
    assert _cli().main() == 0
    output = capsys.readouterr().out
    result = json.loads(output)
    assert result["locator_convention"] == DOCUMENT_PAGE_MARKER_LINES_CONVENTION
    assert result["quote_sha256"] == QUOTE_SHA256 and result["quote_matches_locator"] is True
    assert result["publication_allowed"] is False
    assert SB125_QUOTE not in output

    args[convention_index] = DOCUMENT_PAGE_LINES_CONVENTION
    with pytest.raises(SystemExit) as exc:
        _cli().main()
    assert exc.value.code == 2
    error = capsys.readouterr()
    assert not error.out and "does not select quoted_text exactly" in error.err

    # A numerically plausible range cannot substitute for the required convention.
    del args[convention_index - 1:convention_index + 1]
    with pytest.raises(SystemExit) as exc:
        _cli().main()
    assert exc.value.code == 2
    error = capsys.readouterr()
    assert not error.out and "required: --locator-convention" in error.err
