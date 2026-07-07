from __future__ import annotations

import argparse

from release_common import DEFAULT_CELL, compose_base, ensure_env, run, wait_for_services

CORE_SERVICES = ["postgres", "redis", "qdrant", "minio", "model-gateway", "api", "worker", "admin-ui"]


def main() -> None:
    parser = argparse.ArgumentParser(description="Pull and boot a clean local cell from registry images.")
    parser.add_argument("--cell", default=DEFAULT_CELL)
    parser.add_argument("--worker-scale", type=int, default=1)
    parser.add_argument("--timeout-seconds", type=int, default=300)
    parser.add_argument("--no-wait", action="store_true")
    args = parser.parse_args()
    ensure_env(args.cell)
    base = compose_base(args.cell)
    run(base + ["pull", *CORE_SERVICES])
    run(base + ["up", "-d", "--pull", "always", "--scale", f"worker={args.worker_scale}", *CORE_SERVICES])
    if not args.no_wait:
        wait_for_services(args.cell, ["postgres", "redis", "qdrant", "minio", "model-gateway", "api", "worker", "admin-ui"], args.timeout_seconds)
    run(base + ["ps"])


if __name__ == "__main__":
    main()
