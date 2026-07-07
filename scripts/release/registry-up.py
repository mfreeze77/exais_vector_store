from __future__ import annotations

import argparse

from release_common import run


def main() -> None:
    parser = argparse.ArgumentParser(description="Start or reuse a local Docker registry.")
    parser.add_argument("--name", default="exais-local-registry")
    parser.add_argument("--port", type=int, default=5000)
    args = parser.parse_args()
    existing = run(["docker", "inspect", args.name], check=False)
    if existing.returncode == 0:
        run(["docker", "start", args.name], check=False)
    else:
        run([
            "docker",
            "run",
            "-d",
            "--restart",
            "unless-stopped",
            "-p",
            f"{args.port}:5000",
            "--name",
            args.name,
            "registry:2",
        ])
    run(["docker", "ps", "--filter", f"name={args.name}", "--format", "table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}"])


if __name__ == "__main__":
    main()
