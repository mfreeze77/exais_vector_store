from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib import error, request
from urllib.parse import urlsplit, urlunsplit

from release_common import compose_network_name, project_name

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CELL = "ks-state-civics"
DEFAULT_TENANT_ID = "ten_ks_state_civics"
DEFAULT_BUSINESS_INSTANCE_ID = "biz_ks_state_civics"
DEFAULT_USER_ID = "usr_ks_state_civics_admin"
DEFAULT_KNOWLEDGE_BASE_ID = "kb_ks_state_civics"
DEFAULT_VECTOR_STORE_NAME = "Topeka Municipal Code"
DEFAULT_VECTOR_STORE_ID = "vs_topeka_municipal_code_pending"

INSTANCE_ROOT = ROOT / "instances" / "ks-state-civics" / "vector-stores" / "topeka-municipal-code"
CODIFIED_SEED = INSTANCE_ROOT / "sources" / "topeka-codified-code" / "seed"
ORDINANCE_SEED = INSTANCE_ROOT / "sources" / "topeka-ordinances" / "seed"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_number}: invalid JSONL row: {exc}") from exc
            if not isinstance(row, dict):
                raise ValueError(f"{path}:{line_number}: expected JSON object row")
            rows.append(row)
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def stable_id(prefix: str, *parts: object, length: int = 24) -> str:
    raw = "|".join(str(part or "") for part in parts)
    return f"{prefix}:{sha256_text(raw)[:length]}"


def safe_filename(value: str, *, suffix: str = "") -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip(".-")
    cleaned = re.sub(r"-{2,}", "-", cleaned) or "topeka-record"
    if suffix and not cleaned.lower().endswith(suffix.lower()):
        cleaned += suffix
    return cleaned[:180]


def citation_map_by_id(path: Path) -> dict[str, dict[str, Any]]:
    return {str(row.get("id")): row for row in read_jsonl(path) if row.get("id")}


def maybe_read_env(cell: str) -> dict[str, str]:
    path = ROOT / ".release" / "cells" / cell / ".env.cell"
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value
    return values


def default_api_base(cell: str) -> str:
    env = maybe_read_env(cell)
    return os.getenv("EXAIS_API_BASE") or os.getenv("SVS_RECALL_API") or env.get("SVS_PUBLIC_API_BASE") or f"http://127.0.0.1:{env.get('SVS_API_PORT', '28080')}"


def read_token_file(path: Path | None) -> str:
    if not path or not path.exists():
        return ""
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            return line
    return ""


def default_headers(
    *,
    cell: str,
    auth_token: str | None = None,
    auth_token_file: Path | None = None,
    content_type: str = "application/json",
) -> dict[str, str]:
    env = maybe_read_env(cell)
    token = auth_token or os.getenv("SVS_OPERATOR_KEY") or os.getenv("EXAIS_API_KEY") or read_token_file(auth_token_file)
    headers = {
        "Content-Type": content_type,
        "X-SVS-Tenant-Id": os.getenv("SVS_TENANT_ID", env.get("SVS_DEV_TENANT_ID", DEFAULT_TENANT_ID)),
        "X-SVS-Business-Instance-Id": os.getenv("SVS_BUSINESS_INSTANCE_ID", env.get("SVS_DEV_BUSINESS_INSTANCE_ID", DEFAULT_BUSINESS_INSTANCE_ID)),
        "X-SVS-User-Id": os.getenv("SVS_USER_ID", env.get("SVS_DEV_USER_ID", DEFAULT_USER_ID)),
        "X-SVS-Roles": os.getenv("SVS_ROLES", env.get("SVS_DEV_ROLES", "owner,admin")),
        "X-SVS-Max-Security-Level": os.getenv("SVS_MAX_SECURITY_LEVEL", env.get("SVS_DEV_MAX_SECURITY_LEVEL", "5")),
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def api_json(
    method: str,
    api_base: str,
    path: str,
    payload: dict[str, Any] | None,
    *,
    headers: dict[str, str],
    timeout: int = 120,
    idempotency_key: str | None = None,
    cell: str = DEFAULT_CELL,
    transport: str = "auto",
) -> dict[str, Any]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request_headers = dict(headers)
    if idempotency_key:
        request_headers["Idempotency-Key"] = idempotency_key
    url = f"{api_base.rstrip('/')}{path}"
    if transport == "host-curl":
        return api_json_via_host_curl(method, url, body, headers=request_headers, timeout=timeout)
    if transport == "api-container":
        return api_json_via_api_container(method, url, body, headers=request_headers, timeout=timeout, cell=cell)
    if transport == "docker-network":
        return api_json_via_cell_network(method, url, body, headers=request_headers, timeout=timeout, cell=cell)
    if transport != "auto":
        raise ValueError(f"Unsupported API transport: {transport}")

    req = request.Request(url, data=body, headers=request_headers, method=method)
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} failed with HTTP {exc.code}: {raw[:1200]}") from exc
    except error.URLError:
        try:
            return api_json_via_host_curl(method, url, body, headers=request_headers, timeout=timeout)
        except Exception:
            try:
                return api_json_via_api_container(
                    method,
                    url,
                    body,
                    headers=request_headers,
                    timeout=timeout,
                    cell=cell,
                )
            except Exception:
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
) -> dict[str, Any]:
    curl = shutil.which("curl.exe") or shutil.which("curl")
    if not curl:
        raise RuntimeError("curl executable was not found")
    args = [curl, "-sS", "-w", "\n%{http_code}\n", "-X", method]
    for key, value in headers.items():
        args += ["-H", f"{key}: {value}"]
    if body is not None:
        args += ["--data-binary", "@-"]
    args.append(url)
    return _run_curl_json(args, body, timeout=timeout, display_url=url, method=method)


def api_json_via_api_container(
    method: str,
    url: str,
    body: bytes | None,
    *,
    headers: dict[str, str],
    timeout: int,
    cell: str,
) -> dict[str, Any]:
    parts = urlsplit(url)
    cell_url = urlunsplit((parts.scheme, "127.0.0.1:8080", parts.path, parts.query, parts.fragment))
    args = ["docker", "exec", "-i", f"{project_name(cell)}-api-1", "curl", "-sS", "-w", "\n%{http_code}\n", "-X", method]
    for key, value in headers.items():
        args += ["-H", f"{key}: {value}"]
    if body is not None:
        args += ["--data-binary", "@-"]
    args.append(cell_url)
    return _run_curl_json(args, body, timeout=timeout, display_url=cell_url, method=method)


def api_json_via_cell_network(
    method: str,
    url: str,
    body: bytes | None,
    *,
    headers: dict[str, str],
    timeout: int,
    cell: str,
) -> dict[str, Any]:
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
    return _run_curl_json(args, body, timeout=timeout, display_url=cell_url, method=method)


def _run_curl_json(
    args: list[str],
    body: bytes | None,
    *,
    timeout: int,
    display_url: str,
    method: str,
) -> dict[str, Any]:
    print("$ " + redact_command(args))
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
    print(f"{method} {display_url} -> {status}")
    if status >= 400:
        raise RuntimeError(f"{method} {display_url} failed with HTTP {status}: {raw[:1000]}")
    return json.loads(raw) if raw else {}


def redact_command(args: list[str]) -> str:
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


def ensure_vector_store(
    *,
    api_base: str,
    headers: dict[str, str],
    vector_store_id: str | None,
    vector_store_name: str,
    knowledge_base_id: str,
    allow_create: bool,
    timeout: int,
    cell: str = DEFAULT_CELL,
    transport: str = "auto",
) -> str:
    if vector_store_id and vector_store_id != DEFAULT_VECTOR_STORE_ID:
        return vector_store_id
    page = api_json(
        "GET",
        api_base,
        "/v1/vector_stores?limit=100",
        None,
        headers=headers,
        timeout=timeout,
        cell=cell,
        transport=transport,
    )
    for item in page.get("data", []):
        if item.get("name") == vector_store_name:
            return str(item["id"])
    if not allow_create:
        raise RuntimeError(
            f"Vector store {vector_store_name!r} was not found and --allow-create-vector-store was not supplied."
        )
    payload = {
        "name": vector_store_name,
        "knowledge_base_id": knowledge_base_id,
        "attributes": {
            "corpus": "topeka_municipal_code",
            "source_collection": "topeka-municipal-code",
            "created_by": "scripts/release/topeka_pipeline_common.py",
        },
    }
    created = api_json(
        "POST",
        api_base,
        "/v1/vector_stores",
        payload,
        headers=headers,
        timeout=timeout,
        idempotency_key="topeka-vector-store-" + sha256_text(vector_store_name)[:32],
        cell=cell,
        transport=transport,
    )
    if not created.get("id"):
        raise RuntimeError("Vector store create response did not include id")
    return str(created["id"])


def submit_document(
    *,
    api_base: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    idempotency_key: str,
    timeout: int,
    cell: str = DEFAULT_CELL,
    transport: str = "auto",
) -> dict[str, Any]:
    return api_json(
        "POST",
        api_base,
        "/api/v1/documents/ingest",
        payload,
        headers=headers,
        timeout=timeout,
        idempotency_key=idempotency_key,
        cell=cell,
        transport=transport,
    )


def public_url(value: str | None) -> bool:
    return bool(value and value.startswith(("http://", "https://")))
