#!/usr/bin/env python3
"""Acquire discovered Topeka documents, resumably, without re-spending on bytes we hold.

Consumes the worklist written by ``topeka-collection-discover.py`` and fetches
each document into a per-collection acquisition root. Re-running is cheap and
safe: a document whose retained bytes still hash to the recorded value is
verified and skipped, and progress is checkpointed after every item, so an
interrupted run resumes where it stopped instead of starting over.

    python scripts/release/topeka-collection-acquire.py --worklist <dir>/worklist.jsonl \
        --output-dir <acquisition root> --limit 25

Read-only against the publisher: it issues GETs for listed documents and writes
nothing back. It does not extract, embed, ingest or touch a database. Raw bytes
land outside Git; the committed artifacts are the manifests and the lock.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib import error, request
from urllib.parse import quote, urlsplit, urlunsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))

from jurisdiction_release_contract import (  # noqa: E402
    COLLECTIONS_BY_ID,
    ROOT,
    sha256_bytes,
    sha256_file,
)

USER_AGENT = "ExAIS-Vector-Store-Topeka-Collector/1.0"

DEFAULT_WORKLIST = (
    ROOT / "instances" / "ks-state-civics" / "vector-stores" / "topeka-municipal-code"
    / "discovery" / "worklist.jsonl"
)
DEFAULT_OUTPUT = (
    ROOT / "instances" / "ks-state-civics" / "vector-stores" / "topeka-municipal-code" / "acquisition"
)
ORDINANCE_SEED = (
    ROOT / "instances" / "ks-state-civics" / "vector-stores" / "topeka-municipal-code"
    / "sources" / "topeka-ordinances" / "seed"
)

# Every outcome an item can reach. A worklist row that reaches none of these
# fails the run rather than vanishing from the totals.
OUTCOMES = (
    "reused_verified",      # retained bytes still hash to the recorded value
    "downloaded_new",       # not previously retained
    "downloaded_changed",   # publisher bytes differ from what we hold
    "unchanged_remote",     # already acquired here and the publisher still serves the same bytes
    "failed",               # retryable error (timeout, 5xx, write failure); the item stays pending
    "unavailable_at_source",  # the publisher's own link 404s; a terminal, reportable outcome
    "downloaded_corrected_url",  # listed link 404s; an evidenced correction on the official host resolved
    "skipped_unlisted",     # retained but absent from the current listing; nothing to fetch
)

# Outcomes that mean "this document is accounted for", as opposed to "try again".
# A publisher 404 is a fact about the publisher, not a defect in this run, so it
# is reported rather than failing the run -- but it is never counted as acquired.
TERMINAL_OUTCOMES = frozenset(OUTCOMES) - {"failed"}

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def safe_name(value: str) -> str:
    cleaned = _SAFE.sub("-", value).strip("-.") or "document"
    return cleaned[:150]


def encoded_url(url: str) -> str:
    """Percent-encode the path so URLs containing spaces are fetchable."""
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, quote(parts.path, safe="/%"), parts.query, ""))


def plus_as_space_url(url: str) -> str | None:
    """Re-read a path ``+`` as a space, the way the publisher evidently meant it.

    In a URL path ``+`` is a literal plus; only query strings treat it as a
    space. Topeka's document centre writes hrefs such as
    ``Ordinance20670+.docx`` for a file actually stored with a trailing space,
    so the literal reading 404s. This is a re-interpretation of the publisher's
    own href, not a guess at a different document, and it is only used after
    the literal form has failed -- so a 200 is what confirms it.
    """
    parts = urlsplit(url)
    if "+" not in parts.path:
        return None
    path = quote(parts.path.replace("+", " "), safe="/%")
    return urlunsplit((parts.scheme, parts.netloc, path, parts.query, ""))


def fetch(url: str, *, timeout: int) -> tuple[bytes, str]:
    """Fetch, retrying once with ``+`` read as a space when the literal form 404s."""
    attempts: list[tuple[str, str]] = [(encoded_url(url), "literal")]
    alternate = plus_as_space_url(url)
    if alternate:
        attempts.append((alternate, "plus_decoded_as_space"))

    last: Exception | None = None
    for candidate, resolution in attempts:
        req = request.Request(candidate, headers={"User-Agent": USER_AGENT})
        try:
            with request.urlopen(req, timeout=timeout) as response:
                content_type = response.headers.get("Content-Type", "")
                if resolution != "literal":
                    content_type = f"{content_type}; url_resolution={resolution}"
                return response.read(), content_type
        except error.HTTPError as exc:
            last = exc
            if exc.code != 404:
                raise
    raise last if last else RuntimeError(f"no attempt made for {url}")


class ObservationLog:
    """Append-only record of every observation, never rewritten.

    The checkpoint holds the latest state per document so a resume is cheap.
    That file is rewritten in full on every flush, so it cannot also serve as
    history. This log is the history: one line per observation, appended and
    never edited, so "what did the publisher serve, and when" stays answerable
    after a document changes.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, row: dict[str, Any]) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
            handle.flush()

    def observations_for(self, source_document_id: str) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        rows = []
        with self.path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    row = json.loads(line)
                    if row.get("source_document_id") == source_document_id:
                        rows.append(row)
        return rows


@dataclass
class Checkpoint:
    """Per-document acquisition state, rewritten after every item."""

    path: Path
    entries: dict[str, dict[str, Any]]

    @classmethod
    def load(cls, path: Path) -> "Checkpoint":
        entries: dict[str, dict[str, Any]] = {}
        if path.exists():
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if line.strip():
                        row = json.loads(line)
                        entries[row["source_document_id"]] = row
        return cls(path, entries)

    def record(self, row: dict[str, Any]) -> None:
        self.entries[row["source_document_id"]] = row
        self.flush()

    def flush(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(
            "".join(
                json.dumps(self.entries[key], sort_keys=True) + "\n"
                for key in sorted(self.entries)
            ),
            encoding="utf-8",
        )
        tmp.replace(self.path)


def document_dir(output_dir: Path, row: dict[str, Any]) -> Path:
    spec = COLLECTIONS_BY_ID.get(row["collection_id"])
    slug = spec.slug if spec else "unregistered"
    stem = row["source_document_id"].rsplit(":", 1)[-1]
    return output_dir / slug / "raw" / safe_name(stem)


def version_path(output_dir: Path, row: dict[str, Any], content_sha256: str) -> Path:
    """Immutable, content-addressed location for one observed version.

    Storage is keyed by the hash of the bytes, so a changed document lands
    beside its predecessor instead of on top of it. Nothing here is ever
    overwritten, which is what keeps an earlier acquisition receipt's hash
    resolvable after the publisher revises a document.
    """
    suffix = Path(urlsplit(row["official_url"]).path).suffix.lower() or ".bin"
    return document_dir(output_dir, row) / f"{content_sha256[:16]}{suffix}"


def held_versions(output_dir: Path, row: dict[str, Any]) -> list[str]:
    """Content hashes already stored for this document, oldest-agnostic."""
    folder = document_dir(output_dir, row)
    if not folder.is_dir():
        return []
    return sorted(sha256_file(path) for path in folder.iterdir() if path.is_file())


def _evidenced_correction(
    row: dict[str, Any],
    *,
    timeout: int,
    downloader: Callable[..., tuple[bytes, str]],
) -> tuple[bytes, str, str, dict[str, Any]] | None:
    """Try the candidate derived from the publisher's own naming convention.

    Retrieving a corrected URL from the official publisher can preserve
    provenance, but a 200 alone cannot: it only shows that *something* is there.
    A correction is accepted only when all of these hold, and every one of them
    is recorded alongside the bytes:

      * the candidate was constructed from the dominant filename pattern of the
        publisher's own other members of the same listing group, not invented;
      * it is on the same official host and directory as the broken link;
      * the listing label for this document appears in the candidate filename;
      * the fetch returns 200.

    The broken listing URL is retained either way, and the result is marked for
    review rather than treated as settled.
    """
    candidate = row.get("convention_candidate_url")
    if not candidate:
        return None

    listed = urlsplit(row["official_url"])
    target = urlsplit(candidate)
    if (target.scheme, target.netloc) != (listed.scheme, listed.netloc):
        return None
    if target.path.rsplit("/", 1)[0] != listed.path.rsplit("/", 1)[0]:
        return None

    evidence = dict(row.get("convention_evidence") or {})
    key = str(evidence.get("publisher_key") or "")
    if not key or key not in Path(target.path).name:
        return None

    try:
        payload, content_type = downloader(candidate, timeout=timeout)
    except (error.URLError, TimeoutError, OSError):
        return None
    if not payload:
        return None

    evidence.update({
        "broken_listing_url": row["official_url"],
        "fetched_url": candidate,
        "same_host_and_directory": True,
        "publisher_key_in_candidate_filename": True,
        "http_status": 200,
        "review_status": "evidenced_correction_pending_review",
        "limitation": (
            "the publisher's listing still points at the broken URL; this correction is evidenced by "
            "the publisher's own naming convention and label, not by an updated listing"
        ),
    })
    return payload, content_type, candidate, evidence


def acquire_row(
    row: dict[str, Any],
    *,
    output_dir: Path,
    seed: Path,
    previous: dict[str, Any] | None,
    timeout: int,
    downloader: Callable[..., tuple[bytes, str]],
    run_id: str = "",
    trust_checkpoint: bool = False,
) -> dict[str, Any]:
    doc_id = row["source_document_id"]
    base = {
        "source_document_id": doc_id,
        "collection_id": row["collection_id"],
        "official_url": row["official_url"],
        "observed_at": utc_now(),
        "run_id": run_id,
    }

    if row["outcome"] == "retained_but_unlisted":
        return {**base, "outcome": "skipped_unlisted", "reason": row["reason"],
                "sha256": row.get("retained_sha256"), "byte_count": None, "saved_path": None}

    stored = held_versions(output_dir, row)

    # Bytes we already hold, from the retained seed or an earlier run here.
    held_sha: str | None = None
    held_path: Path | None = None
    if row["outcome"] == "verify_then_reuse" and row.get("retained_path"):
        candidate = seed / row["retained_path"]
        if candidate.exists():
            held_path, held_sha = candidate, sha256_file(candidate)
            if held_sha != row.get("retained_sha256"):
                return {**base, "outcome": "failed", "sha256": held_sha, "byte_count": None,
                        "saved_path": str(candidate),
                        "error": (
                            f"retained original hashes to {held_sha} but the manifest records "
                            f"{row.get('retained_sha256')}; refusing to reuse unverified bytes"
                        )}
    if held_sha is None and previous and previous.get("remote_sha256") in stored:
        held_sha = previous["remote_sha256"]
        held_path = version_path(output_dir, row, held_sha)
    elif held_sha is None and len(stored) == 1:
        held_sha = stored[0]
        held_path = version_path(output_dir, row, held_sha)

    # Resume, not caching. An item is skipped only when THIS run already
    # confirmed it against the publisher (so an interrupted run does not redo
    # completed work), or when the caller explicitly opts into trusting an
    # earlier run's confirmation. Otherwise the publisher is asked again --
    # without that, a document whose bytes changed would never be noticed.
    already_confirmed_this_run = bool(previous and run_id and previous.get("run_id") == run_id)
    if held_sha and previous and previous.get("remote_sha256") == held_sha and (
        already_confirmed_this_run or trust_checkpoint
    ):
        return {**base, "outcome": "reused_verified" if held_path and seed in held_path.parents else "unchanged_remote",
                "sha256": held_sha, "remote_sha256": held_sha,
                "byte_count": held_path.stat().st_size if held_path else None,
                "saved_path": str(held_path) if held_path else None,
                "versions": stored,
                "run_id": run_id,
                "reason": (
                    "already confirmed against the publisher in this run" if already_confirmed_this_run
                    else "trusting an earlier run's confirmation (--trust-checkpoint)"
                )}

    try:
        payload, content_type = downloader(row["official_url"], timeout=timeout)
    except error.HTTPError as exc:
        if exc.code not in {404, 410}:
            return {**base, "outcome": "failed", "sha256": held_sha, "byte_count": None,
                    "saved_path": str(held_path) if held_path else None,
                    "http_status": exc.code, "error": f"{type(exc).__name__}: {exc}"}

        corrected = _evidenced_correction(row, timeout=timeout, downloader=downloader)
        if corrected is None:
            return {**base, "outcome": "unavailable_at_source", "sha256": held_sha, "byte_count": None,
                    "saved_path": str(held_path) if held_path else None,
                    "http_status": exc.code,
                    "listing_url": row["official_url"],
                    "error": f"HTTP {exc.code} at the publisher's own link",
                    "reason": (
                        "the publisher lists this document but the URL it links does not resolve, "
                        "and no evidenced correction on the official host was available. Recorded, "
                        "not repaired: a guessed URL would invent provenance"
                    )}

        payload, content_type, fetched_url, evidence = corrected
        # The broken listing URL is retained beside the one that actually served
        # the bytes, so the correction is auditable rather than a silent swap.
        base = {**base, "listing_url": row["official_url"], "fetched_url": fetched_url,
                "url_resolution": "evidenced_correction", "correction_evidence": evidence,
                "listing_url_status": exc.code}
    except (error.URLError, TimeoutError, OSError) as exc:
        return {**base, "outcome": "failed", "sha256": held_sha, "byte_count": None,
                "saved_path": str(held_path) if held_path else None,
                "error": f"{type(exc).__name__}: {exc}"}

    corrected_fetch = base.get("url_resolution") == "evidenced_correction"
    remote_sha = sha256_bytes(payload)
    if held_sha == remote_sha:
        outcome = "reused_verified" if held_path and seed in held_path.parents else "unchanged_remote"
        return {**base, "outcome": outcome, "sha256": remote_sha, "remote_sha256": remote_sha,
                "byte_count": len(payload), "saved_path": str(held_path),
                "versions": stored, "content_type": content_type,
                "reason": "publisher still serves the bytes we hold; no copy written"}

    destination = version_path(output_dir, row, remote_sha)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists():
        # Content-addressed, so this path is new by construction. Write to a
        # temporary name and rename, so an interrupted write cannot leave a
        # truncated file sitting at a hash that claims to describe it.
        staging = destination.with_name(destination.name + ".partial")
        staging.write_bytes(payload)
        staging.replace(destination)
    versions = sorted(set(stored) | {remote_sha})
    return {
        **base,
        "outcome": (
            "downloaded_corrected_url" if corrected_fetch
            else "downloaded_changed" if held_sha else "downloaded_new"
        ),
        "sha256": remote_sha,
        "remote_sha256": remote_sha,
        "prior_sha256": held_sha,
        "prior_saved_path": str(held_path) if held_sha and held_path else None,
        "byte_count": len(payload),
        "saved_path": str(destination),
        "versions": versions,
        "content_type": content_type,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--worklist", type=Path, default=DEFAULT_WORKLIST)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--ordinance-seed", type=Path, default=ORDINANCE_SEED)
    parser.add_argument("--collection", action="append", default=[],
                        help="restrict to one or more collection IDs")
    parser.add_argument("--limit", type=int, default=0, help="stop after N items (0 = all)")
    parser.add_argument("--delay", type=float, default=0.5, help="seconds between publisher requests")
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--trust-checkpoint", action="store_true",
                        help="skip items a PREVIOUS run confirmed unchanged; faster, but it will not "
                             "notice publisher bytes that changed since that run")
    parser.add_argument("--dry-run", action="store_true",
                        help="report what each item would do; issues no publisher request")
    args = parser.parse_args()

    if not args.worklist.exists():
        print(f"FAIL worklist {args.worklist} is absent; run topeka-collection-discover.py first")
        return 1

    rows = [json.loads(line) for line in args.worklist.read_text(encoding="utf-8").splitlines() if line.strip()]
    if args.collection:
        rows = [row for row in rows if row["collection_id"] in set(args.collection)]

    run_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{args.worklist.stat().st_mtime_ns:x}"
    checkpoint = Checkpoint.load(args.output_dir / "acquisition-checkpoint.jsonl")
    observations = ObservationLog(args.output_dir / "acquisition-observations.jsonl")
    counts: dict[str, int] = {outcome: 0 for outcome in OUTCOMES}
    failures: list[dict[str, Any]] = []
    processed = 0
    fetched = 0

    for row in rows:
        previous = checkpoint.entries.get(row["source_document_id"])
        if args.limit and processed >= args.limit:
            break

        if args.dry_run:
            would = (
                "skipped_unlisted" if row["outcome"] == "retained_but_unlisted"
                else "reused_verified" if row["outcome"] == "verify_then_reuse"
                else "unchanged_remote" if held_versions(args.output_dir, row)
                else "downloaded_new"
            )
            counts[would] += 1
            processed += 1
            continue

        result = acquire_row(
            row,
            output_dir=args.output_dir,
            seed=args.ordinance_seed,
            previous=previous,
            timeout=args.timeout,
            downloader=fetch,
            run_id=run_id,
            trust_checkpoint=args.trust_checkpoint,
        )
        if result["outcome"] not in counts:
            print(f"FAIL {row['source_document_id']} reached unknown outcome {result['outcome']!r}")
            return 1
        counts[result["outcome"]] += 1
        if result["outcome"] in {"failed", "unavailable_at_source", "downloaded_corrected_url"}:
            failures.append(result)
        if result["outcome"] in {"downloaded_new", "downloaded_changed"} or "content_type" in result:
            fetched += 1
            if args.delay:
                time.sleep(args.delay)
        checkpoint.record(result)
        observations.append({
            key: result.get(key)
            for key in (
                "source_document_id", "collection_id", "official_url", "observed_at", "run_id",
                "outcome", "sha256", "remote_sha256", "prior_sha256", "byte_count", "saved_path",
                "http_status", "content_type", "fetched_url", "url_resolution",
            )
        })
        processed += 1

    reconciled = sum(counts.values())
    report = {
        "artifact": "topeka_collection_acquisition",
        "schema_version": "1.0",
        "observed_at": utc_now(),
        "run_id": run_id,
        "trust_checkpoint": args.trust_checkpoint,
        "dry_run": args.dry_run,
        "worklist": str(args.worklist),
        "output_dir": str(args.output_dir),
        "observation_log": str(observations.path),
        "worklist_rows": len(rows),
        "processed": processed,
        "publisher_requests": fetched,
        "outcomes": counts,
        "failure_count": counts["failed"],
        "unavailable_at_source_count": counts["unavailable_at_source"],
        "corrected_url_count": counts["downloaded_corrected_url"],
        "failures": failures[:50],
        "remaining": len(rows) - processed,
        "passed": reconciled == processed and not counts["failed"],
    }
    target = args.output_dir / ("acquisition-dry-run.json" if args.dry_run else "acquisition-report.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"worklist rows      {len(rows)}")
    print(f"processed          {processed}  (remaining {report['remaining']})")
    print(f"publisher requests {fetched}")
    for outcome in OUTCOMES:
        print(f"  {outcome:20s} {counts[outcome]}")
    for failure in failures[:10]:
        label = {
            "failed": "FAILED",
            "unavailable_at_source": "UNAVAILABLE",
            "downloaded_corrected_url": "CORRECTED",
        }[failure["outcome"]]
        detail = failure.get("error") or f"listed {failure.get('listing_url','')} -> fetched {failure.get('fetched_url','')}"
        print(f"  {label} {failure['source_document_id']}: {detail[:120]}")
    print(f"report             {target}")
    print(f"result             {'PASS' if report['passed'] else 'FAIL'}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
