from __future__ import annotations

import argparse
import os
import shlex
import subprocess
from pathlib import Path

from release_common import DEFAULT_CELL, compose_cmd

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_API_IMAGE = "localhost:5000/expertaiservices/exai-vector-store-api:0.9.8-production-candidate"
DEFAULT_NODE_IMAGE = "node:22-bookworm-slim"
DEFAULT_NODE_MODULES_VOLUME = "exais-admin-ui-node-modules"
PYTHONPATH = "/work/packages/svs_common:/work/apps/api:/work/apps/worker:/work/apps/model_gateway:/work/apps/instance_agent"


def printable(args: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in args)


def run(args: list[str], *, cwd: Path = ROOT, check: bool = True, quiet: bool = False) -> subprocess.CompletedProcess[str]:
    if not quiet:
        print(f"$ {printable(args)}")
    proc = subprocess.run(
        args,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if proc.stdout and not quiet:
        print(proc.stdout, end="" if proc.stdout.endswith("\n") else "\n")
    if check and proc.returncode != 0:
        raise subprocess.CalledProcessError(proc.returncode, args, proc.stdout)
    return proc


def docker_image_exists(image: str) -> bool:
    return run(["docker", "image", "inspect", image], check=False, quiet=True).returncode == 0


def running_api_image(cell: str) -> str | None:
    container = f"exais-vector-store-{cell}-api-1"
    proc = run(["docker", "inspect", "--format", "{{.Image}}", container], check=False, quiet=True)
    if proc.returncode == 0:
        image = (proc.stdout or "").strip()
        return image or None
    return None


def resolve_api_image(cell: str, requested: str | None) -> str:
    candidates = [
        requested,
        os.environ.get("SVS_TEST_API_IMAGE"),
        running_api_image(cell),
        DEFAULT_API_IMAGE,
    ]
    for image in candidates:
        if image and docker_image_exists(image):
            return image
    raise SystemExit(
        "No API image is available for Docker proof. "
        "Start a cell or pass --api-image with an existing local image/tag."
    )


def run_compose_config() -> None:
    run(compose_cmd() + ["-f", str(ROOT / "docker-compose.yml"), "config", "--quiet"])


def run_container_ready(cell: str) -> None:
    container = f"exais-vector-store-{cell}-api-1"
    proc = run(["docker", "inspect", container], check=False, quiet=True)
    if proc.returncode != 0:
        print(f"Skipping container ready check; {container} is not running.")
        return
    run([
        "docker",
        "exec",
        container,
        "python",
        "-c",
        "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8080/readyz', timeout=10).read().decode())",
    ])


def run_python_proof(api_image: str, tests: list[str]) -> None:
    mount = f"{ROOT}:/work"
    run([
        "docker",
        "run",
        "--rm",
        "-v",
        mount,
        "-w",
        "/work",
        "-e",
        f"PYTHONPATH={PYTHONPATH}",
        api_image,
        "python",
        "-m",
        "compileall",
        "-f",
        "-q",
        "packages",
        "apps",
        "tests",
        "scripts",
    ])
    run([
        "docker",
        "run",
        "--rm",
        "-v",
        mount,
        "-w",
        "/work",
        "-e",
        f"PYTHONPATH={PYTHONPATH}",
        api_image,
        "python",
        "-m",
        "pytest",
        "-q",
        "-rs",
        *tests,
    ])


def run_admin_ui_build(node_image: str, node_modules_volume: str) -> None:
    run([
        "docker",
        "run",
        "--rm",
        "-v",
        f"{ROOT}:/work",
        "-v",
        f"{node_modules_volume}:/work/apps/admin_ui/node_modules",
        "-w",
        "/work/apps/admin_ui",
        node_image,
        "sh",
        "-lc",
        "npm install --no-package-lock && npm run build",
    ])


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run local proof through Docker so host Python/npm and Compose-plugin drift do not block validation."
    )
    parser.add_argument("--cell", default=DEFAULT_CELL)
    parser.add_argument("--api-image", default=None)
    parser.add_argument("--node-image", default=DEFAULT_NODE_IMAGE)
    parser.add_argument("--node-modules-volume", default=DEFAULT_NODE_MODULES_VOLUME)
    parser.add_argument("--skip-compose", action="store_true")
    parser.add_argument("--skip-ready", action="store_true")
    parser.add_argument("--skip-python", action="store_true")
    parser.add_argument("--skip-admin-ui", action="store_true")
    parser.add_argument("tests", nargs="*", default=["tests"])
    args = parser.parse_args()

    if not args.skip_compose:
        run_compose_config()
    if not args.skip_ready:
        run_container_ready(args.cell)
    if not args.skip_python:
        image = resolve_api_image(args.cell, args.api_image)
        print(f"Using API image for Python proof: {image}")
        run_python_proof(image, args.tests)
    if not args.skip_admin_ui:
        run_admin_ui_build(args.node_image, args.node_modules_volume)


if __name__ == "__main__":
    main()
