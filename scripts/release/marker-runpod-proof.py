from __future__ import annotations

import argparse
import asyncio
import hashlib
from pathlib import Path

from svs_common.marker_client import MarkerRunpodClient, extract_markdown


def make_text_pdf(text: str) -> bytes:
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = f"BT /F1 24 Tf 72 720 Td ({escaped}) Tj ET".encode("ascii", errors="ignore")
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


async def run_proof(args: argparse.Namespace) -> int:
    if args.pdf:
        pdf_path = Path(args.pdf).resolve()
        pdf_name = pdf_path.name
        pdf_bytes = pdf_path.read_bytes()
    else:
        pdf_name = "generated-marker-proof.pdf"
        pdf_bytes = make_text_pdf(args.text_fixture)
    print("env_names_present=MARKER_RUNPOD_API_KEY,MARKER_RUNPOD_ENDPOINT_ID,MARKER_MODE")
    print("retry_names=MARKER_MAX_ATTEMPTS,MARKER_RETRY_BACKOFF_SEC")
    print(f"pdf_name={pdf_name}")
    print(f"pdf_bytes={len(pdf_bytes)}")
    print(f"pdf_sha256={hashlib.sha256(pdf_bytes).hexdigest()[:16]}")

    def log(line: str) -> None:
        print(f"marker_log={line}")

    result = await MarkerRunpodClient(
        poll_interval_sec=args.poll_interval_sec,
        timeout_sec=args.timeout_seconds,
        max_attempts=args.attempts,
        retry_backoff_sec=args.retry_backoff_seconds,
    ).process_pdf_bytes(
        filename=pdf_name,
        pdf_bytes=pdf_bytes,
        log_callback=log,
    )
    print(f"marker_result_present={result is not None}")
    if result is None:
        return 1
    markdown = extract_markdown(result)
    print(f"markdown_chars={len(markdown)}")
    print(f"markdown_sha256={hashlib.sha256(markdown.encode('utf-8')).hexdigest()[:16]}")
    print(f"output_keys={sorted(result.keys())}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Secret-safe RunPod Marker conversion proof.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--pdf", help="Path to a local PDF fixture.")
    source.add_argument("--text-fixture", help="Generate a one-page text PDF with this text.")
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--retry-backoff-seconds", type=int, default=10)
    parser.add_argument("--poll-interval-sec", type=int, default=5)
    parser.add_argument("--timeout-seconds", type=int, default=300)
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run_proof(args)))


if __name__ == "__main__":
    main()
