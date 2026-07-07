from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from release_common import ROOT, api_base  # noqa: E402


HEADERS = {
    "Content-Type": "application/json",
    "X-SVS-Tenant-Id": "ten_dev",
    "X-SVS-Business-Instance-Id": "biz_dev",
    "X-SVS-User-Id": "usr_dev",
    "X-SVS-Groups": "grp_admin,grp_eng",
    "X-SVS-Roles": "owner,admin",
    "X-SVS-Max-Security-Level": "5",
}


def api_json(method: str, url: str, payload: dict[str, Any] | None = None, *, timeout: int = 120) -> dict[str, Any]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, method=method, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def load_cases(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    cases = raw.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError(f"{path} must contain a non-empty cases list")
    return cases


def validate_cases(cases: list[dict[str, Any]], root: Path) -> None:
    for case in cases:
        if not case.get("name"):
            raise ValueError("each case needs a name")
        fixture = root / str(case.get("file", ""))
        if not fixture.exists():
            raise FileNotFoundError(f"missing fixture for {case.get('name')}: {fixture}")
        queries = case.get("queries")
        if not isinstance(queries, list) or not queries:
            raise ValueError(f"case {case['name']} needs at least one query")


def result_text(response: dict[str, Any]) -> str:
    parts: list[str] = []
    for item in response.get("data") or []:
        if item.get("filename"):
            parts.append(str(item["filename"]))
        for content in item.get("content") or []:
            parts.append(str(content.get("text") or ""))
    return "\n".join(parts)


def score_response(query_case: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    data = response.get("data") or []
    text = result_text(response).lower()
    must_contain = [str(token) for token in query_case.get("must_contain") or []]
    missing = [token for token in must_contain if token.lower() not in text]
    min_results = int(query_case.get("min_results", 1))
    passed = len(data) >= min_results and not missing
    return {
        "passed": passed,
        "result_count": len(data),
        "missing": missing,
        "search_query": response.get("search_query"),
    }


def create_vector_store(api: str) -> str:
    response = api_json("POST", f"{api}/v1/vector_stores", {
        "name": f"openai-file-search-parity-{int(time.time())}",
        "attributes": {"eval": "openai_file_search_parity", "source": "tickets"},
    })
    return str(response["id"])


def attach_case(api: str, vector_store_id: str, case: dict[str, Any], root: Path) -> str:
    fixture = root / case["file"]
    attributes = {"force_sync": True, **dict(case.get("attributes") or {})}
    response = api_json("POST", f"{api}/v1/vector_stores/{vector_store_id}/files", {
        "title": case.get("title") or fixture.name,
        "filename": fixture.name,
        "mime_type": "text/markdown",
        "mode": "markdown_docs_v1",
        "content": fixture.read_text(encoding="utf-8"),
        "attributes": attributes,
        "security_level": int(case.get("security_level", 1)),
    })
    return str(response.get("id") or "")


def run_eval(api: str, cases_path: Path, root: Path) -> int:
    cases = load_cases(cases_path)
    validate_cases(cases, root)
    vector_store_id = create_vector_store(api)
    print(f"vector_store_id={vector_store_id}", flush=True)
    for case in cases:
        file_id = attach_case(api, vector_store_id, case, root)
        print(f"attached case={case['name']} file_id={file_id}", flush=True)

    passed = 0
    total = 0
    for case in cases:
        for query_case in case["queries"]:
            total += 1
            payload = {
                "query": query_case["query"],
                "rewrite_query": bool(query_case.get("rewrite_query", False)),
                "filters": query_case.get("filters"),
                "ranking_options": query_case.get("ranking_options", {"ranker": "auto"}),
                "max_num_results": int(query_case.get("max_num_results", 5)),
                "include_content": True,
                "include_metadata": True,
            }
            response = api_json("POST", f"{api}/v1/vector_stores/{vector_store_id}/search", payload)
            scored = score_response(query_case, response)
            if scored["passed"]:
                passed += 1
            print(
                f"query case={case['name']} passed={scored['passed']} "
                f"results={scored['result_count']} search_query={scored['search_query']} missing={scored['missing']}",
                flush=True,
            )
    print(f"summary passed={passed} total={total}", flush=True)
    return 0 if passed == total else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Run OpenAI File Search parity evals against ticket fixtures.")
    parser.add_argument("--cell", default="local")
    parser.add_argument("--api", default=None)
    parser.add_argument("--cases", default="evals/openai-file-search-parity/ticket_golden.json")
    parser.add_argument("--root", default=str(ROOT))
    args = parser.parse_args()
    api = (args.api or api_base(args.cell)).rstrip("/")
    return run_eval(api, Path(args.cases), Path(args.root))


if __name__ == "__main__":
    raise SystemExit(main())
