from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from release_common import DEFAULT_CELL, api_base, compose_network_name, ensure_env, release_dir, run
from scale_common import api_json


DEV_HEADERS = [
    "-H",
    "x-svs-tenant-id: ten_dev",
    "-H",
    "x-svs-business-instance-id: biz_dev",
    "-H",
    "x-svs-user-id: usr_dev",
    "-H",
    "x-svs-groups: grp_admin,grp_eng,admins,engineering",
    "-H",
    "x-svs-roles: owner,admin",
    "-H",
    "x-svs-max-security-level: 5",
]


def make_text_pdf(text: str) -> bytes:
    lines = text.splitlines() or [text]
    commands: list[str] = ["BT /F1 22 Tf 72 720 Td"]
    first = True
    for line in lines:
        escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        if not first:
            commands.append("0 -32 Td")
        commands.append(f"({escaped}) Tj")
        first = False
    commands.append("ET")
    stream = " ".join(commands).encode("ascii", errors="ignore")
    objects = [
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n",
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>\nendobj\n",
        b"4 0 obj\n<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream\nendobj\n",
        b"5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for obj in objects:
        offsets.append(len(out))
        out.extend(obj)
    xref_offset = len(out)
    out.extend(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode("ascii"))
    for offset in offsets[1:]:
        out.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    out.extend(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    )
    return bytes(out)


def write_fixture(cell: str, text: str) -> Path:
    proof_dir = release_dir(cell) / "marker-proof"
    proof_dir.mkdir(parents=True, exist_ok=True)
    path = proof_dir / "generated-marker-upload-proof.pdf"
    path.write_bytes(make_text_pdf(text))
    return path


def parse_curl_json(output: str) -> tuple[int, dict]:
    lines = output.rstrip().splitlines()
    status = int(lines[-1]) if lines and lines[-1].isdigit() else 0
    raw = "\n".join(lines[:-1])
    return status, json.loads(raw) if raw else {}


def upload_pdf(cell: str, api: str, pdf_path: Path, vector_store_id: str, timeout: int) -> dict:
    form = [
        "-F",
        f"file=@{pdf_path};type=application/pdf",
        "-F",
        "mode=auto_detect_v1",
        "-F",
        f"vector_store_id={vector_store_id}",
        "-F",
        "knowledge_base_id=kb_dev",
        "-F",
        "title=Marker Upload Search Proof",
    ]
    host = run(
        [
            "curl",
            "-fsS",
            "-w",
            "\n%{http_code}\n",
            "-X",
            "POST",
            *DEV_HEADERS,
            *form,
            f"{api}/api/v1/documents/upload",
        ],
        check=False,
        timeout=timeout,
    )
    if host.returncode == 0:
        status, payload = parse_curl_json(host.stdout or "")
        print(f"upload_host_status={status}")
        if 200 <= status < 300:
            return payload

    container_path = f"/proof/{pdf_path.name}"
    cell_form = [
        "-F",
        f"file=@{container_path};type=application/pdf",
        "-F",
        "mode=auto_detect_v1",
        "-F",
        f"vector_store_id={vector_store_id}",
        "-F",
        "knowledge_base_id=kb_dev",
        "-F",
        "title=Marker Upload Search Proof",
    ]
    fallback = run(
        [
            "docker",
            "run",
            "--rm",
            "--network",
            compose_network_name(cell),
            "-v",
            f"{pdf_path.parent}:/proof:ro",
            "curlimages/curl:8.10.1",
            "-fsS",
            "-w",
            "\n%{http_code}\n",
            "-X",
            "POST",
            *DEV_HEADERS,
            *cell_form,
            "http://api:8080/api/v1/documents/upload",
        ],
        timeout=timeout,
    )
    status, payload = parse_curl_json(fallback.stdout or "")
    print(f"upload_cell_network_status={status}")
    if not 200 <= status < 300:
        raise RuntimeError(f"PDF upload failed with HTTP {status}")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Upload a generated PDF through the cell API, then prove the converted document is searchable."
    )
    parser.add_argument("--cell", default=DEFAULT_CELL)
    parser.add_argument("--vector-store-id", help="Reuse an existing vector store.")
    parser.add_argument("--pdf", help="Use a representative local PDF instead of a generated fixture.")
    parser.add_argument("--text-fixture", default="Page 1\nHello Marker Upload Search Proof")
    parser.add_argument("--query", default="Hello Marker Upload Search Proof")
    parser.add_argument("--timeout-seconds", type=int, default=600)
    parser.add_argument("--require-page-start", action="store_true")
    args = parser.parse_args()

    ensure_env(args.cell)
    api = api_base(args.cell)
    pdf_path = Path(args.pdf).resolve() if args.pdf else write_fixture(args.cell, args.text_fixture)
    if not pdf_path.exists():
        raise FileNotFoundError(pdf_path)
    print(f"pdf_fixture={pdf_path}")
    print(f"pdf_bytes={pdf_path.stat().st_size}")

    store_id = args.vector_store_id
    if not store_id:
        store = api_json(
            "POST",
            f"{api}/v1/vector_stores",
            {"name": f"Marker PDF Upload Search Proof {int(time.time())}", "knowledge_base_id": "kb_dev"},
            cell=args.cell,
        )
        store_id = store["id"]
    print(f"VECTOR_STORE_ID={store_id}")

    upload = upload_pdf(args.cell, api, pdf_path, store_id, args.timeout_seconds)
    print(f"upload_status={upload.get('status')}")
    print(f"document_id={upload.get('document_id')}")
    print(f"vector_store_file_id={upload.get('vector_store_file_id')}")

    deadline = time.time() + args.timeout_seconds
    last_result: dict | None = None
    while time.time() < deadline:
        last_result = api_json(
            "POST",
            f"{api}/api/v1/retrieval/search",
            {
                "query": args.query,
                "vector_store_id": store_id,
                "mode": "pdf_markdown_external_v1",
                "top_k": 5,
                "include_content": True,
                "include_metadata": True,
            },
            timeout=120,
            cell=args.cell,
        )
        results = last_result.get("results") or []
        print(f"search_results={len(results)}")
        if results:
            first = results[0]
            print(f"first_chunk_id={first.get('id')}")
            print(f"first_page_start={first.get('page_start')}")
            print(f"first_page_end={first.get('page_end')}")
            print(f"first_source={first.get('source')}")
            if args.require_page_start and first.get("page_start") is None:
                raise RuntimeError("Search result did not include page_start; use a representative PDF that Marker emits page markers for.")
            return
        time.sleep(5)
    print(json.dumps(last_result or {}, indent=2))
    raise TimeoutError("Converted PDF document was not searchable before timeout.")


if __name__ == "__main__":
    main()
