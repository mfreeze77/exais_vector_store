#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import sys
import time
from typing import Any
from urllib import error, parse, request


ROOT = Path(__file__).resolve().parents[2]


class LifecycleProofError(RuntimeError):
    pass


@dataclass(frozen=True)
class LifecycleConfig:
    api_base: str
    admin_key: str | None = None
    ingest_key: str | None = None
    search_key: str | None = None
    max_security_level: int = 5
    label_prefix: str = "instance-caller-proof"
    query: str = "Kansas caller lifecycle proof unique precedent"
    output: Path | None = None
    keep_created_keys: bool = False
    timeout_seconds: int = 120


def redact_token(value: str | None) -> str | None:
    if value is None:
        return None
    return value[:9] + "..." + value[-6:] if len(value) > 16 else "<redacted>"


def ensure_no_secret_material(value: Any, tokens: list[str | None]) -> None:
    raw = json.dumps(value, sort_keys=True, default=str)
    leaked = [token for token in tokens if token and token in raw]
    if leaked:
        raise LifecycleProofError("proof payload contains raw API-key material")


class ApiClient:
    def __init__(self, api_base: str, *, timeout: int = 120):
        self.api_base = api_base.rstrip("/")
        self.timeout = timeout

    def post_json(self, path: str, token: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {token}"}
        body = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(payload).encode("utf-8")
        return self._request("POST", path, token, body=body, headers=headers)

    def delete_json(self, path: str, token: str) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {token}"}
        return self._request("DELETE", path, token, headers=headers)

    def post_multipart(
        self,
        path: str,
        token: str,
        *,
        fields: dict[str, str],
        files: dict[str, tuple[str, bytes, str]],
    ) -> dict[str, Any]:
        body, content_type = multipart_body(fields, files)
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": content_type,
        }
        return self._request("POST", path, token, body=body, headers=headers)

    def _request(
        self,
        method: str,
        path: str,
        token: str,
        *,
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        req = request.Request(f"{self.api_base}{path}", data=body, headers=headers or {}, method=method)
        try:
            with request.urlopen(req, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
        except error.HTTPError as exc:
            response_body = exc.read().decode("utf-8", errors="replace")
            response_body = response_body.replace(token, "<redacted>")
            raise LifecycleProofError(f"HTTP {exc.code} {method} {path}: {response_body}") from exc
        return json.loads(raw) if raw else {}


def multipart_body(
    fields: dict[str, str],
    files: dict[str, tuple[str, bytes, str]],
) -> tuple[bytes, str]:
    boundary = "----exais-lifecycle-" + secrets.token_hex(12)
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.extend([
            f"--{boundary}\r\n".encode("ascii"),
            f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("ascii"),
            str(value).encode("utf-8"),
            b"\r\n",
        ])
    for name, (filename, content, content_type) in files.items():
        safe_filename = filename.replace('"', "")
        chunks.extend([
            f"--{boundary}\r\n".encode("ascii"),
            f'Content-Disposition: form-data; name="{name}"; filename="{safe_filename}"\r\n'.encode("ascii"),
            f"Content-Type: {content_type}\r\n\r\n".encode("ascii"),
            content,
            b"\r\n",
        ])
    chunks.append(f"--{boundary}--\r\n".encode("ascii"))
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def create_instance_api_key(
    client: Any,
    admin_key: str,
    *,
    label: str,
    scopes: list[str],
    max_security_level: int,
) -> dict[str, Any]:
    query = parse.urlencode({
        "label": label,
        "scopes": ",".join(scopes),
        "max_security_level": str(max_security_level),
    })
    result = client.post_json(f"/api/v1/admin/api-keys?{query}", admin_key, None)
    if not result.get("api_key") or not result.get("id"):
        raise LifecycleProofError(f"API-key create response for {label} did not include one-time key material and id")
    return result


def revoke_instance_api_key(client: Any, admin_key: str, key_id: str) -> dict[str, Any]:
    return client.delete_json(f"/api/v1/admin/api-keys/{key_id}", admin_key)


def create_vector_store(client: Any, token: str, name: str, corpus: str) -> dict[str, Any]:
    result = client.post_json("/v1/vector_stores", token, {
        "name": name,
        "metadata": {
            "corpus": corpus,
            "proof": "instance_caller_lifecycle",
        },
    })
    if not result.get("id"):
        raise LifecycleProofError(f"vector store create response for {name} did not include id")
    return result


def upload_fixture_file(client: Any, token: str, query: str) -> dict[str, Any]:
    content = (
        f"{query}\n"
        "This fixture proves an instance-scoped ingestion key can upload a file, "
        "attach it to multiple vector stores, and return cited search evidence.\n"
    ).encode("utf-8")
    result = client.post_multipart(
        "/v1/files",
        token,
        fields={"purpose": "assistants"},
        files={"file": ("instance-caller-lifecycle-proof.txt", content, "text/plain")},
    )
    if not result.get("id"):
        raise LifecycleProofError("file upload response did not include id")
    return result


def attach_file(client: Any, token: str, vector_store_id: str, file_id: str) -> dict[str, Any]:
    result = client.post_json(f"/v1/vector_stores/{vector_store_id}/files", token, {"file_id": file_id})
    if not result.get("id"):
        raise LifecycleProofError(f"file attach response for {vector_store_id} did not include id")
    return result


def create_file_batch(client: Any, token: str, vector_store_id: str, file_id: str) -> dict[str, Any]:
    result = client.post_json(f"/v1/vector_stores/{vector_store_id}/file_batches", token, {"file_ids": [file_id]})
    if not result.get("id"):
        raise LifecycleProofError(f"file batch response for {vector_store_id} did not include id")
    return result


def search_vector_store(client: Any, token: str, vector_store_id: str, query: str) -> dict[str, Any]:
    result = client.post_json(
        f"/v1/vector_stores/{vector_store_id}/search",
        token,
        {
            "query": query,
            "max_num_results": 8,
            "rewrite_query": True,
            "include_content": True,
            "include_metadata": True,
        },
    )
    if not result.get("data"):
        raise LifecycleProofError(f"search for {vector_store_id} returned no data")
    if not search_page_has_citation(result):
        raise LifecycleProofError(f"search for {vector_store_id} returned no citation proof")
    return result


def search_page_has_citation(page: dict[str, Any]) -> bool:
    for item in page.get("data") or []:
        if not isinstance(item, dict):
            continue
        if item.get("annotations"):
            return True
        citation = item.get("citation")
        if isinstance(citation, dict) and (citation.get("annotation") or citation.get("file_id")):
            return True
        for content in item.get("content") or []:
            if isinstance(content, dict) and content.get("annotations"):
                return True
    return False


def responses_file_search(client: Any, token: str, vector_store_ids: list[str], query: str) -> dict[str, Any]:
    result = client.post_json(
        "/v1/responses",
        token,
        {
            "model": "exais-retrieval",
            "input": query,
            "tools": [{
                "type": "file_search",
                "vector_store_ids": vector_store_ids,
                "max_num_results": 8,
            }],
            "include": ["file_search_call.results"],
            "store": False,
        },
    )
    if not response_has_citation(result):
        raise LifecycleProofError("Responses file_search returned no citation proof")
    return result


def response_has_citation(response: dict[str, Any]) -> bool:
    if response.get("citations"):
        return True
    for output in response.get("output") or []:
        if not isinstance(output, dict):
            continue
        for content in output.get("content") or []:
            if isinstance(content, dict) and content.get("annotations"):
                return True
    return False


def result_count(page: dict[str, Any]) -> int:
    data = page.get("data")
    return len(data) if isinstance(data, list) else 0


def citation_count(payload: dict[str, Any]) -> int:
    citations = payload.get("citations")
    if isinstance(citations, list):
        return len(citations)
    total = 0
    for output in payload.get("output") or []:
        if isinstance(output, dict):
            for content in output.get("content") or []:
                if isinstance(content, dict):
                    total += len(content.get("annotations") or [])
    return total


def run_lifecycle(config: LifecycleConfig, *, client: Any | None = None) -> dict[str, Any]:
    client = client or ApiClient(config.api_base, timeout=config.timeout_seconds)
    admin_key = config.admin_key
    ingest_key = config.ingest_key
    search_key = config.search_key
    created_keys: list[dict[str, Any]] = []
    revoked_keys: list[str] = []
    proof: dict[str, Any] | None = None

    if not ingest_key:
        if not admin_key:
            raise LifecycleProofError("provide --ingest-key or --admin-key so an ingestion key can be created")
        created = create_instance_api_key(
            client,
            admin_key,
            label=f"{config.label_prefix}-ingest",
            scopes=["retrieval:read", "vector_stores:read", "vector_stores:write", "documents:write"],
            max_security_level=config.max_security_level,
        )
        ingest_key = created["api_key"]
        created_keys.append({"id": created["id"], "label": created["label"], "purpose": "ingest"})

    if not search_key:
        if not admin_key:
            raise LifecycleProofError("provide --search-key or --admin-key so a search-only key can be created")
        created = create_instance_api_key(
            client,
            admin_key,
            label=f"{config.label_prefix}-search",
            scopes=["retrieval:read", "vector_stores:read"],
            max_security_level=config.max_security_level,
        )
        search_key = created["api_key"]
        created_keys.append({"id": created["id"], "label": created["label"], "purpose": "search"})

    assert ingest_key is not None
    assert search_key is not None

    try:
        suffix = str(int(time.time()))
        law_store = create_vector_store(client, ingest_key, f"{config.label_prefix} KS Law {suffix}", "ks_law")
        court_store = create_vector_store(
            client,
            ingest_key,
            f"{config.label_prefix} Kansas Supreme Court and Appeals {suffix}",
            "ks_courts",
        )
        file_payload = upload_fixture_file(client, ingest_key, config.query)
        attach_payload = attach_file(client, ingest_key, law_store["id"], file_payload["id"])
        batch_payload = create_file_batch(client, ingest_key, court_store["id"], file_payload["id"])
        law_search = search_vector_store(client, search_key, law_store["id"], config.query)
        court_search = search_vector_store(client, search_key, court_store["id"], config.query)
        response_payload = responses_file_search(client, search_key, [law_store["id"], court_store["id"]], config.query)
        proof = {
            "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "api_base": config.api_base.rstrip("/"),
            "instance_scoped_api_key_model": True,
            "per_key_vector_store_grants": False,
            "created_keys": created_keys,
            "keys": {
                "ingest_key_source": "provided" if config.ingest_key else "temporary_created",
                "search_key_source": "provided" if config.search_key else "temporary_created",
                "ingest_key": redact_token(ingest_key),
                "search_key": redact_token(search_key),
            },
            "vector_stores": [
                {"id": law_store["id"], "name": law_store.get("name"), "corpus": "ks_law"},
                {"id": court_store["id"], "name": court_store.get("name"), "corpus": "ks_courts"},
            ],
            "file": {
                "id": file_payload["id"],
                "filename": file_payload.get("filename"),
            },
            "attachments": {
                "single_file_attach_id": attach_payload["id"],
                "file_batch_id": batch_payload["id"],
                "file_batch_status": batch_payload.get("status"),
            },
            "search": {
                law_store["id"]: {
                    "result_count": result_count(law_search),
                    "has_citations": search_page_has_citation(law_search),
                },
                court_store["id"]: {
                    "result_count": result_count(court_search),
                    "has_citations": search_page_has_citation(court_search),
                },
            },
            "responses_file_search": {
                "searched_vector_store_ids": [law_store["id"], court_store["id"]],
                "citation_count": citation_count(response_payload),
                "has_citations": response_has_citation(response_payload),
            },
        }
        ensure_no_secret_material(proof, [admin_key, ingest_key, search_key])
        return proof
    finally:
        if admin_key and created_keys and not config.keep_created_keys:
            for key in created_keys:
                revoke_instance_api_key(client, admin_key, key["id"])
                revoked_keys.append(key["id"])
        if proof is not None:
            proof["temporary_keys_revoked"] = revoked_keys


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prove instance-scoped API keys can create stores, upload files, attach batches, and search with citations."
    )
    parser.add_argument("--api-base", default=os.getenv("EXAIS_API_BASE") or os.getenv("SVS_API_BASE"))
    parser.add_argument("--admin-key", default=os.getenv("EXAIS_ADMIN_KEY"))
    parser.add_argument("--ingest-key", default=os.getenv("EXAIS_INGEST_KEY"))
    parser.add_argument("--search-key", default=os.getenv("EXAIS_SEARCH_KEY"))
    parser.add_argument("--max-security-level", type=int, default=5)
    parser.add_argument("--label-prefix", default="instance-caller-proof")
    parser.add_argument("--query", default="Kansas caller lifecycle proof unique precedent")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--keep-created-keys", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=120)
    return parser


def config_from_args(args: argparse.Namespace) -> LifecycleConfig:
    if not args.api_base:
        raise ValueError("EXAIS_API_BASE, SVS_API_BASE, or --api-base is required")
    if args.max_security_level < 0 or args.max_security_level > 5:
        raise ValueError("--max-security-level must be between 0 and 5")
    return LifecycleConfig(
        api_base=args.api_base.rstrip("/"),
        admin_key=args.admin_key,
        ingest_key=args.ingest_key,
        search_key=args.search_key,
        max_security_level=args.max_security_level,
        label_prefix=args.label_prefix,
        query=args.query,
        output=args.output,
        keep_created_keys=bool(args.keep_created_keys),
        timeout_seconds=args.timeout_seconds,
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        config = config_from_args(parser.parse_args(argv))
        proof = run_lifecycle(config)
    except (ValueError, LifecycleProofError) as exc:
        parser.error(str(exc))
    output = json.dumps(proof, indent=2, sort_keys=True)
    if config.output:
        config.output.parent.mkdir(parents=True, exist_ok=True)
        config.output.write_text(output + "\n", encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
