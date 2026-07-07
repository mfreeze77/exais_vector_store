from __future__ import annotations

import argparse
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass

from release_common import DEFAULT_CELL, api_base, compose_network_name, ensure_env, printable_command, read_env


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
    print("Cell access proof complete.")


if __name__ == "__main__":
    main()
