from __future__ import annotations

import argparse

from release_common import DEFAULT_CELL, api_base, compose_base, compose_network_name, ensure_env, env_file, run
from secret_runtime import cleanup_runtime_secret_env, runtime_env_path


def restore_workers(base: list[str], worker_scale: int) -> None:
    pulled = run(
        base + ["up", "-d", "--no-deps", "--pull", "always", "--scale", f"worker={worker_scale}", "worker"],
        check=False,
    )
    if pulled.returncode == 0:
        return
    print("Registry pull failed; restoring workers from the pinned local image.")
    run(base + ["up", "-d", "--no-deps", "--pull", "never", "--scale", f"worker={worker_scale}", "worker"])


def run_smoke(cell: str, worker_scale: int) -> None:
    source_path = env_file(cell)
    try:
        prepared_env_path = runtime_env_path(source_path)
        base = compose_base(cell, prepared_env_path=prepared_env_path)
        api = api_base(cell)

        run(base + ["ps"])
        run(base + ["exec", "-T", "api", "curl", "-fsS", "-w", "\n%{http_code}\n", "http://127.0.0.1:8080/readyz"])
        host = run(["curl", "-fsS", "-w", "\n%{http_code}\n", f"{api}/readyz"], check=False)
        if host.returncode != 0:
            print("Host loopback curl failed; checking through an external curl container on the cell network.")
            run([
                "docker",
                "run",
                "--rm",
                "--network",
                compose_network_name(cell),
                "curlimages/curl:8.10.1",
                "-fsS",
                "-w",
                "\n%{http_code}\n",
                "http://api:8080/readyz",
            ])
        logs = run(base + ["logs", "--no-color", "--tail", "300", "api", "worker"], check=False)
        unsafe_count = (logs.stdout or "").count("Unsafe SVS startup configuration")
        print(f"Unsafe SVS startup configuration occurrences: {unsafe_count}")
        if unsafe_count:
            raise SystemExit(1)

        run(base + [
            "exec",
            "-T",
            "api",
            "python",
            "-m",
            "compileall",
            "-f",
            "-q",
            "/app/packages",
            "/app/apps",
            "/app/tests",
        ])
        run(base + [
            "exec",
            "-T",
            "api",
            "python",
            "-m",
            "pytest",
            "-q",
            "-rs",
            "/app/tests",
            "--ignore=/app/tests/integration",
        ])
        run(base + ["stop", "worker"])
        try:
            run(base + [
                "exec",
                "-T",
                "api",
                "env",
                "SVS_RUN_INTEGRATION=1",
                "python",
                "-m",
                "pytest",
                "-q",
                "-rs",
                "/app/tests/integration",
            ])
        finally:
            restore_workers(base, worker_scale)
    finally:
        cleanup_runtime_secret_env(source_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run publish-gate smoke checks against a registry-pulled cell.")
    parser.add_argument("--cell", default=DEFAULT_CELL)
    parser.add_argument("--worker-scale", type=int, default=4)
    args = parser.parse_args()
    ensure_env(args.cell)
    run_smoke(args.cell, args.worker_scale)


if __name__ == "__main__":
    main()
