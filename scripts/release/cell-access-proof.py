from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from release_common import DEFAULT_CELL, api_base, compose_network_name, ensure_env, printable_command, read_env


DEFAULT_ADMIN_KEY_ENV = "EXAIS_ADMIN_KEY"
DEFAULT_PROOF_EXPERT_ID = "kansas-court-decisions"
DEFAULT_PROOF_MESSAGE = "WAVE-125 attribution proof: name one Kansas appellate decision in the corpus."


class AttributionProofError(RuntimeError):
    """The per-user attribution path did not produce the expected rows."""


def _json_request(
    method: str,
    url: str,
    token: str,
    payload: dict[str, Any] | None = None,
    *,
    timeout: int = 60,
) -> tuple[int, dict[str, Any]]:
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    body = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, method=method, data=body, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            parsed = {"detail": raw}
        return exc.code, parsed


def ensure_no_secret_material(value: Any, tokens: list[str | None]) -> None:
    raw = json.dumps(value, sort_keys=True, default=str)
    if any(token and token in raw for token in tokens):
        raise AttributionProofError("proof output contains raw API-key material")


def attribution_proof(
    base_url: str,
    admin_key: str,
    *,
    expert_id: str = DEFAULT_PROOF_EXPERT_ID,
    external_user_id: str | None = None,
    message: str = DEFAULT_PROOF_MESSAGE,
    timeout: int = 60,
    keep_key: bool = False,
) -> dict[str, Any]:
    """WAVE-125: mint a user-bound key, send one expert message, show attribution.

    Steps: provision the user by ``external_id``; mint a ``retrieval:read`` key
    bound to it; send one expert message with that key; read the usage rows
    filtered by ``user_id`` and ``api_key_id`` with the admin key; read the
    per-user summary; revoke the minted key unless ``keep_key``.
    Returns a redacted result dict (never the raw minted key).
    """
    base = base_url.rstrip("/")
    external_user_id = external_user_id or f"wave125-proof-{int(time.time())}"
    status, user = _json_request(
        "POST", f"{base}/api/v1/admin/users", admin_key,
        {"external_id": external_user_id, "display_name": "WAVE-125 attribution proof"}, timeout=timeout,
    )
    if status != 200 or not user.get("id"):
        raise AttributionProofError(f"user provisioning failed: {status} {user}")
    user_id = user["id"]
    query = urllib.parse.urlencode({"label": f"wave125-proof-{external_user_id}", "user_id": user_id})
    status, key = _json_request("POST", f"{base}/api/v1/admin/api-keys?{query}", admin_key, timeout=timeout)
    if status != 200 or not key.get("api_key"):
        raise AttributionProofError(f"user-bound key creation failed: {status} {key}")
    user_key = key["api_key"]
    key_id = key["id"]
    result: dict[str, Any] = {
        "external_user_id": external_user_id,
        "user_id": user_id,
        "api_key_id": key_id,
        "key_scopes": list(key.get("scopes") or []),
        "key_user_id": key.get("user_id"),
    }
    try:
        status, answer = _json_request(
            "POST", f"{base}/v1/experts/{expert_id}/messages", user_key,
            {"message": message, "external_user_id": external_user_id, "conversation_id": f"conv-{external_user_id}"},
            timeout=timeout,
        )
        result["message_status"] = status
        result["session_id"] = answer.get("session_id") if status == 200 else None
        if status != 200:
            raise AttributionProofError(f"expert message failed: {status} {answer.get('detail')}")
        usage_query = urllib.parse.urlencode({"user_id": user_id, "api_key_id": key_id, "limit": 50})
        status, usage = _json_request("GET", f"{base}/api/v1/admin/usage?{usage_query}", admin_key, timeout=timeout)
        if status != 200:
            raise AttributionProofError(f"usage listing failed: {status} {usage.get('detail')}")
        rows = [row for row in usage.get("data", []) if row.get("user_id") == user_id and row.get("api_key_id") == key_id]
        result["usage_rows_attributed"] = len(rows)
        result["usage_event_types"] = sorted({row.get("event_type") for row in rows})
        if not rows:
            raise AttributionProofError("no usage rows attributed to the user-bound key")
        status, summary = _json_request(
            "GET", f"{base}/api/v1/admin/usage/summary?group_by=user", admin_key, timeout=timeout,
        )
        if status != 200:
            raise AttributionProofError(f"usage summary failed: {status} {summary.get('detail')}")
        user_rows = [row for row in summary.get("data", []) if row.get("group_id") == user_id]
        result["summary_user_rows"] = len(user_rows)
        result["summary_quantity"] = user_rows[0].get("quantity") if user_rows else None
        if len(user_rows) != 1:
            raise AttributionProofError("usage summary did not return exactly one row for the proof user")
    finally:
        if not keep_key:
            status, _ = _json_request("DELETE", f"{base}/api/v1/admin/api-keys/{key_id}", admin_key, timeout=timeout)
            result["key_revoked"] = status == 200
    ensure_no_secret_material(result, [user_key, admin_key])
    return result


def attribution_lines(result: dict[str, Any]) -> list[str]:
    ordered = (
        "external_user_id",
        "user_id",
        "api_key_id",
        "key_user_id",
        "key_scopes",
        "message_status",
        "session_id",
        "usage_rows_attributed",
        "usage_event_types",
        "summary_user_rows",
        "summary_quantity",
        "key_revoked",
    )
    lines = []
    for name in ordered:
        if name not in result:
            continue
        value = result[name]
        if isinstance(value, list):
            value = ",".join(str(item) for item in value)
        lines.append(f"ATTRIBUTION_{name.upper()}={value}")
    return lines


@dataclass(frozen=True)
class AccessTarget:
    name: str
    host_url: str
    cell_url: str


def host_status(url: str, timeout: int = 10) -> tuple[int | None, str]:
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, "OK"
    except urllib.error.HTTPError as exc:
        return exc.code, "HTTP_ERROR"
    except Exception as exc:
        return None, type(exc).__name__


def cell_network_status(cell: str, url: str, timeout: int = 60) -> int:
    args = [
        "docker",
        "run",
        "--rm",
        "--network",
        compose_network_name(cell),
        "curlimages/curl:8.10.1",
        "-fsS",
        "-o",
        "/dev/null",
        "-w",
        "%{http_code}",
        url,
    ]
    print("$ " + printable_command(args), flush=True)
    proc = subprocess.run(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    output = (proc.stdout or "").strip()
    if output:
        print(output, flush=True)
    print(f"[exit {proc.returncode}]", flush=True)
    if proc.returncode != 0:
        raise subprocess.CalledProcessError(proc.returncode, args, output)
    return int(output) if output.isdigit() else 0


def access_targets(cell: str) -> list[AccessTarget]:
    values = read_env(cell)
    admin_port = values.get("SVS_ADMIN_UI_PORT", "13080")
    return [
        AccessTarget("api", f"{api_base(cell).rstrip('/')}/readyz", "http://api:8080/readyz"),
        AccessTarget("admin-ui", f"http://localhost:{admin_port}/", "http://admin-ui:3000/"),
    ]


def label_name(name: str) -> str:
    return name.upper().replace("-", "_")


def main() -> None:
    parser = argparse.ArgumentParser(description="Prove API/admin access through host loopback or Docker cell-network fallback.")
    parser.add_argument("--cell", default=DEFAULT_CELL)
    parser.add_argument("--timeout-seconds", type=int, default=60)
    parser.add_argument(
        "--attribution-proof",
        action="store_true",
        help="WAVE-125: mint a user-bound key, send one expert message, and show the attributed usage row.",
    )
    parser.add_argument(
        "--admin-key-env",
        default=DEFAULT_ADMIN_KEY_ENV,
        help=f"Environment variable holding a cell admin key with api_keys:write and usage:read (default {DEFAULT_ADMIN_KEY_ENV}).",
    )
    parser.add_argument("--expert-id", default=DEFAULT_PROOF_EXPERT_ID)
    parser.add_argument("--external-user-id", default=None)
    parser.add_argument("--keep-user-key", action="store_true", help="Do not revoke the minted user-bound key.")
    args = parser.parse_args()
    ensure_env(args.cell)

    print(f"CELL={args.cell}")
    fallback_used = False
    for target in access_targets(args.cell):
        label = label_name(target.name)
        print(f"{label}_HOST_URL={target.host_url}")
        status, reason = host_status(target.host_url)
        if status:
            print(f"{label}_HOST_STATUS={status}")
        else:
            print(f"{label}_HOST_STATUS=UNAVAILABLE")
            print(f"{label}_HOST_REASON={reason}")
        if status == 200:
            continue
        fallback_used = True
        print(f"{label}_CELL_NETWORK_URL={target.cell_url}")
        cell_status = cell_network_status(args.cell, target.cell_url, args.timeout_seconds)
        print(f"{label}_CELL_NETWORK_STATUS={cell_status}")
        if cell_status != 200:
            raise SystemExit(1)

    print(f"ACCESS_PATH={'cell-network-fallback' if fallback_used else 'host-loopback'}")
    if args.attribution_proof:
        admin_key = os.environ.get(args.admin_key_env, "").strip()
        if not admin_key:
            raise SystemExit(f"--attribution-proof requires a cell admin key in ${args.admin_key_env}")
        if fallback_used:
            raise SystemExit("attribution proof needs host loopback API access; cell-network fallback is not supported")
        result = attribution_proof(
            api_base(args.cell),
            admin_key,
            expert_id=args.expert_id,
            external_user_id=args.external_user_id,
            timeout=args.timeout_seconds,
            keep_key=args.keep_user_key,
        )
        for line in attribution_lines(result):
            print(line)
    print("Cell access proof complete.")


if __name__ == "__main__":
    main()
