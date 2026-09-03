from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from release_common import DEFAULT_CELL, ROOT, api_base, compose_network_name, ensure_env, project_name, read_env, release_dir
from scale_common import chunk_vector_store_where, job_vector_store_where, parse_int_row, psql, sql_literal


# The collector repo is a sibling checkout of this one; override with KSCOURTS_SOURCE_ROOT.
DEFAULT_SOURCE_ROOT = Path(os.environ.get("KSCOURTS_SOURCE_ROOT") or ROOT.parent / "ksa-diff-collector-main")
DEFAULT_MANIFEST = Path(r"data\raw\kscourts-decisions\decisions_manifest.csv")
DEFAULT_STATE_RELATIVE = Path("kscourts-ingest") / "progress.jsonl"
DEFAULT_VECTOR_STORE_NAME = "Kansas Court Decisions"
DEFAULT_KNOWLEDGE_BASE_ID = "kb_dev"
SOURCE_COLLECTION = "kscourts-decisions"
LOW_TEXT_THRESHOLD_CHARS = 400
API_TRANSPORT = "auto"
MARKER_ENV_KEYS = (
    "MARKER_RUNPOD_API_KEY",
    "MARKER_RUNPOD_ENDPOINT_ID",
    "RUNPOD_API_KEY",
    "RUNPOD_ENDPOINT_ID",
    "MARKER_MODE",
    "MARKER_TIMEOUT_SEC",
    "MARKER_POLL_INTERVAL_SEC",
    "MARKER_MAX_ATTEMPTS",
    "MARKER_RETRY_BACKOFF_SEC",
)

ROOT = Path(__file__).resolve().parents[2]
COMMON_PACKAGE = ROOT / "packages" / "svs_common"
if COMMON_PACKAGE.exists():
    sys.path.insert(0, str(COMMON_PACKAGE))


@dataclass(frozen=True)
class ManifestDocument:
    row: dict[str, str]
    row_key: str
    pdf_path: Path
    year: str


@dataclass(frozen=True)
class ExtractionResult:
    markdown: str
    pages: int
    text_chars: int
    parser: str = "pypdf"
    metadata: dict[str, str | int | float | bool] = field(default_factory=dict)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_manifest(source_root: Path, manifest: Path) -> list[ManifestDocument]:
    manifest_path = manifest if manifest.is_absolute() else source_root / manifest
    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")

    docs: list[ManifestDocument] = []
    with manifest_path.open("r", encoding="utf-8-sig", newline="") as handle:
        for raw in csv.DictReader(handle):
            row = {str(k): (v or "").strip() for k, v in raw.items()}
            saved_path = row.get("saved_path") or row.get("filename")
            if not saved_path:
                continue
            pdf_path = Path(saved_path)
            if not pdf_path.is_absolute():
                pdf_path = source_root / pdf_path
            year = _year_from_row(row, pdf_path)
            docs.append(ManifestDocument(row=row, row_key=row_key(row), pdf_path=pdf_path, year=year))
    return docs


def row_key(row: dict[str, str]) -> str:
    identity = "|".join(
        [
            row.get("document_id") or "",
            row.get("docket_number") or "",
            row.get("filename") or "",
            row.get("sha256") or "",
        ]
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]


def idempotency_key(doc: ManifestDocument) -> str:
    raw = f"{SOURCE_COLLECTION}|{doc.row_key}|{doc.row.get('sha256') or ''}"
    return "kscourts-ingest-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:48]


def _year_from_row(row: dict[str, str], pdf_path: Path) -> str:
    decision_date = row.get("decision_date") or ""
    match = re.match(r"^(\d{4})-", decision_date)
    if match:
        return match.group(1)
    for part in reversed(pdf_path.parts):
        if re.fullmatch(r"\d{4}", part):
            return part
    return "unknown"


def load_state(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    latest: dict[str, dict] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            key = str(event.get("row_key") or "")
            if key:
                latest[key] = event
    return latest


def append_state(path: Path, event: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, sort_keys=True) + "\n")


def inventory(docs: list[ManifestDocument]) -> dict:
    pdf_docs = [doc for doc in docs if doc.pdf_path.suffix.lower() == ".pdf"]
    existing = [doc for doc in pdf_docs if doc.pdf_path.exists()]
    missing = [doc for doc in pdf_docs if not doc.pdf_path.exists()]
    bytes_values: list[int] = []
    duplicate_hashes: Counter[str] = Counter()
    courts: Counter[str] = Counter()
    statuses: Counter[str] = Counter()
    years: Counter[str] = Counter()
    over_limit_files = 0

    for doc in pdf_docs:
        row = doc.row
        courts[row.get("court") or "unknown"] += 1
        statuses[row.get("status") or "unknown"] += 1
        years[doc.year] += 1
        sha = row.get("sha256") or ""
        if sha:
            duplicate_hashes[sha] += 1
        size = parse_int(row.get("bytes"))
        if size is None and doc.pdf_path.exists():
            size = doc.pdf_path.stat().st_size
        if size is not None:
            bytes_values.append(size)
            if size > 50 * 1024 * 1024:
                over_limit_files += 1

    duplicate_hash_count = sum(1 for _sha, count in duplicate_hashes.items() if count > 1)
    return {
        "manifest_rows": len(docs),
        "pdf_rows": len(pdf_docs),
        "existing_pdfs": len(existing),
        "missing_pdfs": len(missing),
        "total_pdf_bytes": sum(bytes_values),
        "total_pdf_gb": round(sum(bytes_values) / (1024**3), 3),
        "courts": dict(sorted(courts.items())),
        "statuses": dict(sorted(statuses.items())),
        "years": dict(sorted(years.items())),
        "duplicate_hashes": duplicate_hash_count,
        "over_50mb_files": over_limit_files,
        "largest_pdf_bytes": max(bytes_values) if bytes_values else 0,
    }


def parse_int(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except ValueError:
        return None


def print_inventory(inv: dict) -> None:
    print("Kansas court decisions inventory")
    print(f"manifest_rows={inv['manifest_rows']}")
    print(f"pdf_rows={inv['pdf_rows']}")
    print(f"existing_pdfs={inv['existing_pdfs']}")
    print(f"missing_pdfs={inv['missing_pdfs']}")
    print(f"total_pdf_bytes={inv['total_pdf_bytes']}")
    print(f"total_pdf_gb={inv['total_pdf_gb']}")
    print(f"duplicate_hashes={inv['duplicate_hashes']}")
    print(f"over_50mb_files={inv['over_50mb_files']}")
    print(f"largest_pdf_bytes={inv['largest_pdf_bytes']}")
    print("courts=" + json.dumps(inv["courts"], sort_keys=True))
    print("statuses=" + json.dumps(inv["statuses"], sort_keys=True))
    year_items = sorted(inv["years"].items())
    print(f"years_first={year_items[:5]}")
    print(f"years_last={year_items[-5:]}")


def select_pilot_documents(docs: list[ManifestDocument], limit: int) -> list[ManifestDocument]:
    eligible: list[ManifestDocument] = []
    for doc in docs:
        if not doc.pdf_path.exists():
            continue
        eligible.append(doc)

    buckets: dict[tuple[str, str, str], list[ManifestDocument]] = defaultdict(list)
    for doc in eligible:
        year_band = _year_band(doc.year)
        buckets[(doc.row.get("court") or "unknown", doc.row.get("status") or "unknown", year_band)].append(doc)

    selected: list[ManifestDocument] = []
    seen: set[str] = set()
    for _bucket, bucket_docs in sorted(buckets.items(), key=lambda item: item[0]):
        for doc in bucket_docs:
            if doc.row_key not in seen:
                selected.append(doc)
                seen.add(doc.row_key)
                break
        if len(selected) >= limit:
            return selected[:limit]

    for doc in sorted(eligible, key=lambda item: (item.year, item.row.get("court") or "", item.row.get("status") or "", item.row_key)):
        if doc.row_key in seen:
            continue
        selected.append(doc)
        seen.add(doc.row_key)
        if len(selected) >= limit:
            break
    return selected


def _year_band(year: str) -> str:
    try:
        value = int(year)
    except ValueError:
        return "unknown"
    start = (value // 5) * 5
    return f"{start}-{start + 4}"


def extract_pdf_text(path: Path, *, low_text_threshold: int) -> ExtractionResult:
    try:
        from pypdf import PdfReader
    except ImportError as exc:
        raise RuntimeError("Missing pypdf. Install it in this Python environment before running the importer.") from exc

    reader = PdfReader(str(path))
    pages: list[str] = []
    for index, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception as exc:  # pypdf reports encrypted/problem pages with provider-specific errors.
            raise RuntimeError(f"page {index} extraction failed: {exc}") from exc
        text = normalize_text(text)
        if text:
            pages.append(f"<!-- page: {index} -->\n\n{text}")
    markdown = "\n\n".join(pages).strip()
    text_chars = len(markdown)
    if text_chars < low_text_threshold:
        raise ValueError(f"low extracted text volume: {text_chars} chars below threshold {low_text_threshold}")
    return ExtractionResult(markdown=markdown, pages=len(reader.pages), text_chars=text_chars)


def apply_marker_env_from_cell(cell: str) -> None:
    env = read_env(cell)
    for key in MARKER_ENV_KEYS:
        value = env.get(key)
        if value and not os.getenv(key):
            os.environ[key] = value


def marker_extraction_from_output(
    output: dict,
    *,
    job_ids: list[str],
    low_text_threshold: int,
) -> ExtractionResult:
    from svs_common.marker_client import extract_markdown

    markdown = extract_markdown(output).strip()
    text_chars = len(markdown)
    if text_chars < low_text_threshold:
        raise ValueError(f"Marker low extracted text volume: {text_chars} chars below threshold {low_text_threshold}")
    pages = parse_int(str(output.get("pages") or "")) or 0
    metadata: dict[str, str | int | float | bool] = {}
    if job_ids:
        metadata["marker_job_id"] = job_ids[-1]
    for source_key, attr_key in (
        ("pages", "marker_pages"),
        ("processing_time_seconds", "marker_processing_time_seconds"),
        ("output_format", "marker_output_format"),
    ):
        value = output.get(source_key)
        if isinstance(value, (str, int, float, bool)):
            metadata[attr_key] = value
    return ExtractionResult(
        markdown=markdown,
        pages=pages,
        text_chars=text_chars,
        parser="runpod_marker",
        metadata=metadata,
    )


def extract_pdf_text_with_marker(doc: ManifestDocument, args: argparse.Namespace, *, reason: str) -> ExtractionResult:
    import asyncio

    from svs_common.marker_client import MarkerRunpodClient

    apply_marker_env_from_cell(args.cell)
    pdf_bytes = doc.pdf_path.read_bytes()
    job_ids: list[str] = []

    def log(line: str) -> None:
        print(f"marker_log row_key={doc.row_key} {line}")

    print(f"marker_fallback row_key={doc.row_key} reason={reason}")
    output = asyncio.run(
        MarkerRunpodClient().process_pdf_bytes(
            filename=doc.pdf_path.name,
            pdf_bytes=pdf_bytes,
            log_callback=log,
            job_id_callback=job_ids.append,
        )
    )
    if output is None:
        raise RuntimeError("Marker RunPod PDF conversion failed")
    return marker_extraction_from_output(output, job_ids=job_ids, low_text_threshold=args.low_text_threshold)


def normalize_text(value: str) -> str:
    lines = [line.rstrip() for line in value.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    compacted: list[str] = []
    previous_blank = False
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if not previous_blank:
                compacted.append("")
            previous_blank = True
            continue
        compacted.append(stripped)
        previous_blank = False
    return "\n".join(compacted).strip()


def document_payload(doc: ManifestDocument, extraction: ExtractionResult, args: argparse.Namespace, vector_store_id: str) -> dict:
    row = doc.row
    source_uri = row.get("pdf_url") or doc.pdf_path.as_uri()
    attributes = {
        "source_collection": SOURCE_COLLECTION,
        "source_index": row.get("source_index") or "",
        "document_id": row.get("document_id") or "",
        "docket_number": row.get("docket_number") or "",
        "decision_date": row.get("decision_date") or "",
        "decision_year": doc.year,
        "court": row.get("court") or "",
        "status": row.get("status") or "",
        "title": row.get("title") or "",
        "pdf_url": row.get("pdf_url") or "",
        "saved_path": row.get("saved_path") or "",
        "source_pdf_path": str(doc.pdf_path),
        "source_pdf_filename": row.get("filename") or doc.pdf_path.name,
        "bytes": parse_int(row.get("bytes")) or 0,
        "sha256": row.get("sha256") or "",
        "downloaded_at_utc": row.get("downloaded_at_utc") or "",
        "extraction_parser": extraction.parser,
        "extraction_pages": extraction.pages,
        "extraction_text_chars": extraction.text_chars,
        "force_async": args.force_async,
    }
    attributes.update(extraction.metadata)
    title = row.get("title") or row.get("filename") or doc.pdf_path.stem
    filename = row.get("filename") or doc.pdf_path.name
    return {
        "vector_store_id": vector_store_id,
        "knowledge_base_id": args.knowledge_base_id,
        "title": title,
        "filename": filename.rsplit(".", 1)[0] + ".md",
        "mime_type": "text/markdown",
        "content": extraction.markdown,
        "mode": "pdf_markdown_external_v1",
        "source_uri": source_uri,
        "attributes": attributes,
        "security_level": args.security_level,
        "source_trust": "external_pdf_parser",
    }


def default_headers(cell: str, *, use_operator_key: bool, auth_token_file: Path | None) -> dict[str, str]:
    env = read_env(cell)
    headers = {
        "Content-Type": "application/json",
        "X-SVS-Tenant-Id": os.getenv("SVS_TENANT_ID", env.get("SVS_DEV_TENANT_ID", "ten_dev")),
        "X-SVS-Business-Instance-Id": os.getenv("SVS_BUSINESS_INSTANCE_ID", env.get("SVS_DEV_BUSINESS_INSTANCE_ID", "biz_dev")),
        "X-SVS-User-Id": os.getenv("SVS_USER_ID", env.get("SVS_DEV_USER_ID", "usr_dev")),
        "X-SVS-Roles": os.getenv("SVS_ROLES", env.get("SVS_DEV_ROLES", "owner,admin")),
        "X-SVS-Max-Security-Level": os.getenv("SVS_MAX_SECURITY_LEVEL", env.get("SVS_DEV_MAX_SECURITY_LEVEL", "5")),
    }
    if use_operator_key:
        token = os.getenv("SVS_OPERATOR_KEY") or read_token_file(auth_token_file or release_dir(cell) / "operator-admin-key.local.txt")
        if not token:
            raise RuntimeError("Operator key requested but no SVS_OPERATOR_KEY or token file was found.")
        headers["Authorization"] = f"Bearer {token}"
    return headers


def read_token_file(path: Path) -> str:
    if not path.exists():
        return ""
    token = ""
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            token = line
    return token


def api_json(
    method: str,
    url: str,
    payload: dict | None = None,
    *,
    headers: dict[str, str],
    timeout: int,
    cell: str,
    idempotency: str | None = None,
) -> dict:
    request_headers = dict(headers)
    if idempotency:
        request_headers["Idempotency-Key"] = idempotency
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    if API_TRANSPORT == "api-container":
        return api_json_via_api_container(method, url, body, headers=request_headers, timeout=timeout, cell=cell)
    if API_TRANSPORT == "docker-network":
        return api_json_via_cell_network(method, url, body, headers=request_headers, timeout=timeout, cell=cell)
    if API_TRANSPORT == "host-curl":
        return api_json_via_host_curl(method, url, body, headers=request_headers, timeout=timeout)
    req = urllib.request.Request(url, data=body, method=method, headers=request_headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            print(f"{method} {url} -> {resp.status}")
            if raw:
                print(raw[:600])
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        print(f"{method} {url} -> {exc.code}")
        print(raw[:1200])
        raise
    except urllib.error.URLError as exc:
        print(f"{method} {url} -> host request failed: {exc}")
        try:
            return api_json_via_host_curl(method, url, body, headers=request_headers, timeout=timeout)
        except Exception as curl_exc:
            print(f"{method} {url} -> host curl failed: {curl_exc}")
            try:
                return api_json_via_api_container(
                    method,
                    url,
                    body,
                    headers=request_headers,
                    timeout=timeout,
                    cell=cell,
                )
            except Exception as exec_exc:
                print(f"{method} {url} -> api-container curl failed: {exec_exc}")
                return api_json_via_cell_network(
                    method,
                    url,
                    body,
                    headers=request_headers,
                    timeout=timeout,
                    cell=cell,
                )


def api_json_via_host_curl(
    method: str,
    url: str,
    body: bytes | None,
    *,
    headers: dict[str, str],
    timeout: int,
) -> dict:
    curl = shutil.which("curl.exe") or shutil.which("curl")
    if not curl:
        raise RuntimeError("curl executable was not found")
    args = [
        curl,
        "-sS",
        "-w",
        "\n%{http_code}\n",
        "-X",
        method,
    ]
    for key, value in headers.items():
        args += ["-H", f"{key}: {value}"]
    if body is not None:
        args += ["--data-binary", "@-"]
    args.append(url)
    print("$ " + redact_args(args))
    proc = subprocess.run(
        args,
        input=body or b"",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
    )
    output = (proc.stdout or b"").decode("utf-8", errors="replace")
    print(output[:1200], end="" if output.endswith("\n") else "\n")
    print(f"[exit {proc.returncode}]")
    if proc.returncode != 0:
        raise subprocess.CalledProcessError(proc.returncode, args, output)
    lines = output.rstrip().splitlines()
    status = int(lines[-1]) if lines and lines[-1].isdigit() else 0
    raw = "\n".join(lines[:-1])
    print(f"{method} {url} -> {status}")
    if status >= 400:
        raise RuntimeError(f"{method} {url} failed with HTTP {status}: {raw[:1000]}")
    return json.loads(raw) if raw else {}


def api_json_via_api_container(
    method: str,
    url: str,
    body: bytes | None,
    *,
    headers: dict[str, str],
    timeout: int,
    cell: str,
) -> dict:
    parts = urlsplit(url)
    cell_url = urlunsplit((parts.scheme, "127.0.0.1:8080", parts.path, parts.query, parts.fragment))
    args = [
        "docker",
        "exec",
        "-i",
        f"{project_name(cell)}-api-1",
        "curl",
        "-sS",
        "-w",
        "\n%{http_code}\n",
        "-X",
        method,
    ]
    for key, value in headers.items():
        args += ["-H", f"{key}: {value}"]
    if body is not None:
        args += ["--data-binary", "@-"]
    args.append(cell_url)
    print("$ " + redact_args(args))
    proc = subprocess.run(
        args,
        input=body or b"",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
    )
    output = (proc.stdout or b"").decode("utf-8", errors="replace")
    print(output[:1200], end="" if output.endswith("\n") else "\n")
    print(f"[exit {proc.returncode}]")
    if proc.returncode != 0:
        raise subprocess.CalledProcessError(proc.returncode, args, output)
    lines = output.rstrip().splitlines()
    status = int(lines[-1]) if lines and lines[-1].isdigit() else 0
    raw = "\n".join(lines[:-1])
    print(f"{method} {cell_url} -> {status}")
    if status >= 400:
        raise RuntimeError(f"{method} {cell_url} failed with HTTP {status}: {raw[:1000]}")
    return json.loads(raw) if raw else {}


def api_json_via_cell_network(
    method: str,
    url: str,
    body: bytes | None,
    *,
    headers: dict[str, str],
    timeout: int,
    cell: str,
) -> dict:
    parts = urlsplit(url)
    cell_url = urlunsplit((parts.scheme, "api:8080", parts.path, parts.query, parts.fragment))
    args = [
        "docker",
        "run",
        "--rm",
        "-i",
        "--network",
        compose_network_name(cell),
        "curlimages/curl:8.10.1",
        "-sS",
        "-w",
        "\n%{http_code}\n",
        "-X",
        method,
    ]
    for key, value in headers.items():
        args += ["-H", f"{key}: {value}"]
    if body is not None:
        args += ["--data-binary", "@-"]
    args.append(cell_url)
    print("$ " + redact_args(args))
    proc = subprocess.run(
        args,
        input=body or b"",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
    )
    output = (proc.stdout or b"").decode("utf-8", errors="replace")
    print(output[:1200], end="" if output.endswith("\n") else "\n")
    print(f"[exit {proc.returncode}]")
    if proc.returncode != 0:
        raise subprocess.CalledProcessError(proc.returncode, args, output)
    lines = output.rstrip().splitlines()
    status = int(lines[-1]) if lines and lines[-1].isdigit() else 0
    raw = "\n".join(lines[:-1])
    print(f"{method} {cell_url} -> {status}")
    if status >= 400:
        raise RuntimeError(f"{method} {cell_url} failed with HTTP {status}: {raw[:1000]}")
    return json.loads(raw) if raw else {}


def redact_args(args: list[str]) -> str:
    rendered: list[str] = []
    redact_next_header = False
    for arg in args:
        if redact_next_header:
            if arg.lower().startswith("authorization:"):
                rendered.append("Authorization: Bearer <redacted>")
            else:
                rendered.append(arg)
            redact_next_header = False
            continue
        rendered.append(arg)
        if arg == "-H":
            redact_next_header = True
    return " ".join(rendered)


def ensure_vector_store(api: str, headers: dict[str, str], args: argparse.Namespace) -> str:
    page = api_json("GET", f"{api}/v1/vector_stores?limit=100", headers=headers, timeout=args.api_timeout_seconds, cell=args.cell)
    for item in page.get("data", []):
        if item.get("name") == args.vector_store_name:
            print(f"VECTOR_STORE_ID={item['id']} reused name={args.vector_store_name!r}")
            return str(item["id"])
    payload = {
        "name": args.vector_store_name,
        "knowledge_base_id": args.knowledge_base_id,
        "attributes": {
            "source_collection": SOURCE_COLLECTION,
            "pilot_created_by": "scripts/release/kscourts-ingest.py",
        },
    }
    created = api_json(
        "POST",
        f"{api}/v1/vector_stores",
        payload,
        headers=headers,
        timeout=args.api_timeout_seconds,
        cell=args.cell,
        idempotency="kscourts-vector-store-" + hashlib.sha256(args.vector_store_name.encode("utf-8")).hexdigest()[:32],
    )
    print(f"VECTOR_STORE_ID={created['id']} created name={args.vector_store_name!r}")
    return str(created["id"])


def submit_document(api: str, headers: dict[str, str], args: argparse.Namespace, vector_store_id: str, doc: ManifestDocument, extraction: ExtractionResult) -> dict:
    payload = document_payload(doc, extraction, args, vector_store_id)
    return api_json(
        "POST",
        f"{api}/api/v1/documents/ingest",
        payload,
        headers=headers,
        timeout=args.api_timeout_seconds,
        cell=args.cell,
        idempotency=idempotency_key(doc),
    )


def indexed_documents_by_sha(cell: str, vector_store_id: str) -> dict[str, dict]:
    output = psql(
        cell,
        f"""
SELECT jsonb_build_object(
  'sha256', COALESCE(vsf.attributes->>'sha256', ''),
  'document_api_id', d.id,
  'vector_store_file_id', vsf.id,
  'title', d.title,
  'status', vsf.status
)::text
FROM vector_store_files vsf
JOIN documents d
  ON d.id=vsf.document_id
 AND d.tenant_id=vsf.tenant_id
 AND d.business_instance_id=vsf.business_instance_id
WHERE vsf.vector_store_id={sql_literal(vector_store_id)}
  AND COALESCE(vsf.attributes->>'sha256', '') != '';
""",
        tuples_only=True,
    )
    indexed: dict[str, dict] = {}
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped.startswith("{"):
            continue
        try:
            item = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        sha = str(item.get("sha256") or "")
        if sha:
            indexed[sha] = item
    print(f"indexed_sha_count={len(indexed)}")
    return indexed


def poll_counts(cell: str, vector_store_id: str, expected_new_docs: int, timeout_seconds: int) -> dict[str, int]:
    job_where = job_vector_store_where(vector_store_id)
    chunk_where = chunk_vector_store_where(vector_store_id)
    deadline = time.time() + timeout_seconds
    final: dict[str, int] = {}
    while time.time() < deadline:
        rows = psql(
            cell,
            f"""
SELECT
  (SELECT count(*) FROM ingestion_jobs WHERE {job_where} AND status='failed')::int AS failed_jobs,
  (SELECT count(*) FROM ingestion_jobs WHERE {job_where} AND status IN ('queued','running'))::int AS active_jobs,
  (SELECT count(*) FROM documents WHERE vector_store_id={chunk_where.removeprefix('vector_store_id = ')})::int AS documents,
  (SELECT count(*) FROM chunks WHERE {chunk_where} AND active=true)::int AS active_chunks,
  (SELECT count(*) FROM chunks WHERE {chunk_where} AND active=true AND dense_index_status='indexed' AND sparse_index_status='indexed')::int AS indexed_chunks;
""",
            tuples_only=True,
        )
        fields = parse_int_row(rows)
        if len(fields) == 5:
            failed_jobs, active_jobs, documents, active_chunks, indexed_chunks = fields
            final = {
                "failed_jobs": failed_jobs,
                "active_jobs": active_jobs,
                "documents": documents,
                "active_chunks": active_chunks,
                "indexed_chunks": indexed_chunks,
            }
            print("poll_counts=" + json.dumps(final, sort_keys=True))
            if active_jobs == 0 and active_chunks == indexed_chunks and documents > 0 and indexed_chunks > 0:
                if documents < expected_new_docs:
                    print(
                        "poll_counts_notice=unique document count is below proof document count; "
                        f"documents={documents} proof_documents={expected_new_docs}. "
                        "Treating drained jobs and fully indexed chunks as complete."
                    )
                return final
        time.sleep(5)
    raise TimeoutError(f"Timed out waiting for ingestion counts: {json.dumps(final, sort_keys=True)}")


def run_search_proof(api: str, headers: dict[str, str], args: argparse.Namespace, vector_store_id: str, submitted: list[ManifestDocument]) -> list[dict]:
    if not submitted:
        return []
    first = submitted[0]
    title_query = first.row.get("title") or first.row.get("docket_number") or "Kansas"
    docket_query = first.row.get("docket_number") or title_query
    court = first.row.get("court") or ""
    status = first.row.get("status") or ""
    queries = [
        {"label": "title", "query": title_query, "filters": None},
        {"label": "docket_filter", "query": docket_query, "filters": {"type": "eq", "key": "docket_number", "value": docket_query}},
        {"label": "substantive", "query": "summary judgment jurisdiction statute", "filters": None},
    ]
    if court and status:
        queries.append(
            {
                "label": "court_status_filter",
                "query": title_query,
                "filters": {
                    "type": "and",
                    "filters": [
                        {"type": "eq", "key": "court", "value": court},
                        {"type": "eq", "key": "status", "value": status},
                    ],
                },
            }
        )
    other_court = next((doc for doc in submitted if (doc.row.get("court") or "") and doc.row.get("court") != court), None)
    if other_court:
        other_title = other_court.row.get("title") or other_court.row.get("docket_number") or title_query
        queries.append(
            {
                "label": "other_court_filter",
                "query": other_title,
                "filters": {"type": "eq", "key": "court", "value": other_court.row.get("court") or ""},
            }
        )
    other_status = next((doc for doc in submitted if (doc.row.get("status") or "") and doc.row.get("status") != status), None)
    if other_status:
        other_title = other_status.row.get("title") or other_status.row.get("docket_number") or title_query
        queries.append(
            {
                "label": "other_status_filter",
                "query": other_title,
                "filters": {"type": "eq", "key": "status", "value": other_status.row.get("status") or ""},
            }
        )

    proof: list[dict] = []
    for query in queries:
        payload = {
            "query": query["query"],
            "max_num_results": 3,
            "include_content": False,
            "include_metadata": True,
        }
        if query["filters"]:
            payload["filters"] = query["filters"]
        result = api_json(
            "POST",
            f"{api}/v1/vector_stores/{vector_store_id}/search",
            payload,
            headers=headers,
            timeout=args.api_timeout_seconds,
            cell=args.cell,
        )
        rows = result.get("data", [])
        top = rows[0] if rows else {}
        item = {
            "label": query["label"],
            "query": query["query"],
            "result_count": len(rows),
            "top_file_id": top.get("file_id") or top.get("id"),
            "top_filename": top.get("filename"),
            "top_score": top.get("score"),
        }
        print("search_proof=" + json.dumps(item, sort_keys=True))
        proof.append(item)
    return proof


def write_failure_report(state_path: Path, vector_store_id: str, state: dict[str, dict]) -> Path:
    failures = [
        event
        for event in state.values()
        if event.get("vector_store_id") == vector_store_id and event.get("status") in {"failed_extraction", "low_text", "marker_failed", "api_failed"}
    ]
    path = state_path.with_name("failures.json")
    path.write_text(json.dumps(failures, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"FAILURE_REPORT={path}")
    print(f"failure_count={len(failures)}")
    return path


def validate_run_mode(args: argparse.Namespace) -> None:
    env = read_env(args.cell)
    provider = env.get("DEFAULT_EMBEDDING_PROVIDER", "")
    print(f"DEFAULT_EMBEDDING_PROVIDER={provider or '<unset>'}")
    if provider == "hash_mock" and not args.allow_hash_mock and args.full_corpus:
        raise RuntimeError("Refusing full-corpus ingestion while DEFAULT_EMBEDDING_PROVIDER=hash_mock. Use --allow-hash-mock only for plumbing proof.")
    if args.marker_fallback_limit > 0:
        print(
            "REMOTE_MARKER_FALLBACK_WARNING=enabled "
            f"limit={args.marker_fallback_limit}; failed or low-text PDFs can be sent to RunPod Marker. "
            "Check provider pricing and endpoint throughput before raising this limit."
        )
    if args.marker_fallback_limit > args.pilot_limit and args.pilot_limit > 0:
        print(
            "WARNING: Marker fallback can incur remote cost. This run will not send more than "
            f"{args.marker_fallback_limit} fallback PDFs, which is larger than pilot_limit={args.pilot_limit}."
        )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ingest the Kansas court decisions PDF corpus through the ExAIS API.")
    parser.add_argument("--cell", default=DEFAULT_CELL)
    parser.add_argument("--source-root", type=Path, default=DEFAULT_SOURCE_ROOT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--state", type=Path, default=None)
    parser.add_argument("--vector-store-name", default=DEFAULT_VECTOR_STORE_NAME)
    parser.add_argument("--knowledge-base-id", default=DEFAULT_KNOWLEDGE_BASE_ID)
    parser.add_argument("--security-level", type=int, default=1)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--pilot-limit", type=int, default=50)
    parser.add_argument("--full-corpus", action="store_true")
    parser.add_argument("--allow-hash-mock", action="store_true")
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--force-sync", action="store_true")
    parser.add_argument("--api-timeout-seconds", type=int, default=300)
    parser.add_argument("--timeout-seconds", type=int, default=900)
    parser.add_argument("--low-text-threshold", type=int, default=LOW_TEXT_THRESHOLD_CHARS)
    parser.add_argument("--marker-fallback-limit", type=int, default=0)
    parser.add_argument("--use-operator-key", action="store_true")
    parser.add_argument("--auth-token-file", type=Path, default=None)
    parser.add_argument("--api-transport", choices=["auto", "host-curl", "api-container", "docker-network"], default="auto")
    parser.add_argument("--skip-search-proof", action="store_true")
    return parser


def main() -> None:
    global API_TRANSPORT
    args = build_arg_parser().parse_args()
    API_TRANSPORT = args.api_transport
    args.force_async = not args.force_sync
    if args.pilot_limit < 1 and not args.full_corpus and not args.dry_run:
        raise ValueError("--pilot-limit must be positive unless --full-corpus or --dry-run is used")

    ensure_env(args.cell)
    validate_run_mode(args)

    source_root = args.source_root.resolve()
    docs = load_manifest(source_root, args.manifest)
    inv = inventory(docs)
    print_inventory(inv)
    if args.dry_run:
        return

    state_path = args.state or release_dir(args.cell) / DEFAULT_STATE_RELATIVE
    state = load_state(state_path)
    selected = docs if args.full_corpus else select_pilot_documents(docs, args.pilot_limit)
    if not selected:
        print("No eligible documents selected; state may already contain this pilot sample.")
        return

    env = read_env(args.cell)
    token_file = args.auth_token_file or release_dir(args.cell) / "operator-admin-key.local.txt"
    has_operator_key = bool(os.getenv("SVS_OPERATOR_KEY") or read_token_file(token_file))
    use_operator_key = args.use_operator_key or has_operator_key or (env.get("SVS_DEV_MODE", "").lower() != "true")
    headers = default_headers(args.cell, use_operator_key=use_operator_key, auth_token_file=token_file)
    api = api_base(args.cell)
    vector_store_id = ensure_vector_store(api, headers, args)
    indexed_by_sha = indexed_documents_by_sha(args.cell, vector_store_id)

    submitted: list[ManifestDocument] = []
    proof_documents: list[ManifestDocument] = []
    skipped_or_failed = Counter()
    marker_fallbacks_used = 0
    for index, doc in enumerate(selected, start=1):
        print(f"[{index}/{len(selected)}] {doc.row.get('decision_date')} {doc.row.get('court')} {doc.row.get('status')} {doc.row.get('title')}")
        sha = doc.row.get("sha256") or ""
        if sha and sha in indexed_by_sha:
            event = event_for_doc(doc, vector_store_id, "completed", pdf_path=doc.pdf_path, response=indexed_by_sha[sha])
            append_state(state_path, event)
            state[doc.row_key] = event
            skipped_or_failed["already_indexed"] += 1
            proof_documents.append(doc)
            print(f"already_indexed row_key={doc.row_key} document_id={indexed_by_sha[sha].get('document_api_id')}")
            continue
        previous = state.get(doc.row_key)
        if previous and previous.get("sha256") == doc.row.get("sha256"):
            previous_status = previous.get("status")
            if previous_status in {"submitted", "completed", "already_submitted"}:
                event = event_for_doc(doc, vector_store_id, "already_submitted", pdf_path=doc.pdf_path, response=previous)
                append_state(state_path, event)
                state[doc.row_key] = event
                skipped_or_failed["already_submitted"] += 1
                proof_documents.append(doc)
                print(f"already_submitted row_key={doc.row_key} previous_status={previous_status}")
                continue
            if previous_status in {"failed_extraction", "low_text", "marker_failed", "api_failed"} and not args.retry_failed:
                skipped_or_failed[f"previous_{previous_status}"] += 1
                print(f"previous_{previous_status} row_key={doc.row_key}; use --retry-failed to retry")
                continue
        if not doc.pdf_path.exists():
            event = event_for_doc(doc, vector_store_id, "missing_pdf", error="source PDF does not exist", pdf_path=doc.pdf_path)
            append_state(state_path, event)
            state[doc.row_key] = event
            skipped_or_failed["missing_pdf"] += 1
            print(f"missing_pdf row_key={doc.row_key} path={doc.pdf_path}")
            continue
        try:
            extraction = extract_pdf_text(doc.pdf_path, low_text_threshold=args.low_text_threshold)
        except ValueError as exc:
            if marker_fallbacks_used < args.marker_fallback_limit:
                try:
                    marker_fallbacks_used += 1
                    extraction = extract_pdf_text_with_marker(doc, args, reason=str(exc))
                except Exception as marker_exc:
                    event = event_for_doc(
                        doc,
                        vector_store_id,
                        "marker_failed",
                        error=f"local low_text={exc}; marker fallback={marker_exc}",
                        pdf_path=doc.pdf_path,
                    )
                    append_state(state_path, event)
                    state[doc.row_key] = event
                    skipped_or_failed["marker_failed"] += 1
                    print(f"marker_failed row_key={doc.row_key} error={marker_exc}")
                    continue
            else:
                event = event_for_doc(doc, vector_store_id, "low_text", error=str(exc), pdf_path=doc.pdf_path)
                append_state(state_path, event)
                state[doc.row_key] = event
                skipped_or_failed["low_text"] += 1
                print(f"low_text row_key={doc.row_key} error={exc}")
                continue
        except Exception as exc:
            if marker_fallbacks_used < args.marker_fallback_limit:
                try:
                    marker_fallbacks_used += 1
                    extraction = extract_pdf_text_with_marker(doc, args, reason=str(exc))
                except Exception as marker_exc:
                    event = event_for_doc(
                        doc,
                        vector_store_id,
                        "marker_failed",
                        error=f"local failed_extraction={exc}; marker fallback={marker_exc}",
                        pdf_path=doc.pdf_path,
                    )
                    append_state(state_path, event)
                    state[doc.row_key] = event
                    skipped_or_failed["marker_failed"] += 1
                    print(f"marker_failed row_key={doc.row_key} error={marker_exc}")
                    continue
            else:
                event = event_for_doc(doc, vector_store_id, "failed_extraction", error=str(exc), pdf_path=doc.pdf_path)
                append_state(state_path, event)
                state[doc.row_key] = event
                skipped_or_failed["failed_extraction"] += 1
                print(f"failed_extraction row_key={doc.row_key} error={exc}")
                continue

        try:
            response = submit_document(api, headers, args, vector_store_id, doc, extraction)
        except Exception as exc:
            event = event_for_doc(doc, vector_store_id, "api_failed", error=str(exc), pdf_path=doc.pdf_path)
            append_state(state_path, event)
            state[doc.row_key] = event
            skipped_or_failed["api_failed"] += 1
            print(f"api_failed row_key={doc.row_key} error={exc}")
            continue

        event = event_for_doc(
            doc,
            vector_store_id,
            "submitted",
            pdf_path=doc.pdf_path,
            extraction=extraction,
            response=response,
        )
        append_state(state_path, event)
        state[doc.row_key] = event
        submitted.append(doc)
        proof_documents.append(doc)
        print(
            f"submitted row_key={doc.row_key} status={response.get('status')} "
            f"job_or_file_id={response.get('id')} chars={extraction.text_chars}"
        )

    print(f"STATE={state_path}")
    print(f"submitted_count={len(submitted)}")
    print(f"marker_fallbacks_used={marker_fallbacks_used}")
    print("skipped_or_failed=" + json.dumps(dict(skipped_or_failed), sort_keys=True))
    state = load_state(state_path)
    write_failure_report(state_path, vector_store_id, state)

    counts = {}
    if proof_documents:
        counts = poll_counts(args.cell, vector_store_id, len(proof_documents), args.timeout_seconds)
    if not proof_documents and selected:
        raise RuntimeError("Pilot selected documents, but none were submitted or found indexed.")
    proof = [] if args.skip_search_proof else run_search_proof(api, headers, args, vector_store_id, proof_documents)
    print(
        "PILOT_SUMMARY="
        + json.dumps(
            {
                "vector_store_id": vector_store_id,
                "submitted": len(submitted),
                "proof_documents": len(proof_documents),
                "counts": counts,
                "search_proof": proof,
            },
            sort_keys=True,
        )
    )


def event_for_doc(
    doc: ManifestDocument,
    vector_store_id: str,
    status: str,
    *,
    pdf_path: Path,
    error: str | None = None,
    extraction: ExtractionResult | None = None,
    response: dict | None = None,
) -> dict:
    row = doc.row
    response = response or {}
    event = {
        "timestamp": utc_now(),
        "status": status,
        "row_key": doc.row_key,
        "vector_store_id": vector_store_id,
        "source_index": row.get("source_index") or "",
        "document_id": row.get("document_id") or "",
        "docket_number": row.get("docket_number") or "",
        "decision_date": row.get("decision_date") or "",
        "court": row.get("court") or "",
        "publication_status": row.get("status") or "",
        "title": row.get("title") or "",
        "pdf_path": str(pdf_path),
        "sha256": row.get("sha256") or "",
        "idempotency_key": idempotency_key(doc),
    }
    if extraction:
        event.update(
            {
                "extraction_pages": extraction.pages,
                "extraction_parser": extraction.parser,
                "extraction_text_chars": extraction.text_chars,
                "extraction_status": "ok",
            }
        )
        event.update(extraction.metadata)
    if response:
        event.update(
            {
                "api_status": response.get("status"),
                "api_id": response.get("id"),
                "document_api_id": response.get("document_id") or response.get("document_api_id"),
                "vector_store_file_id": response.get("vector_store_file_id") or response.get("id"),
            }
        )
    if error:
        event["error"] = error
    return event


if __name__ == "__main__":
    main()
