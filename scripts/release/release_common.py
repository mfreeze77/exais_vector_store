from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[2]
VERSION_FILE = ROOT / "VERSION"
COMPOSE_FILE = ROOT / "infra" / "docker" / "compose.cell.yml"
DEFAULT_REGISTRY_PREFIX = "localhost:5000/expertaiservices"
DEFAULT_CELL = "local"

APP_IMAGES = {
    "api": ("apps/api/Dockerfile", "exai-vector-store-api"),
    "worker": ("apps/worker/Dockerfile", "exai-vector-store-worker"),
    "model-gateway": ("apps/model_gateway/Dockerfile", "exai-vector-store-model-gateway"),
    "admin-ui": ("apps/admin_ui/Dockerfile", "exai-vector-store-admin-ui"),
    "instance-agent": ("apps/instance_agent/Dockerfile", "exai-vector-store-instance-agent"),
}


def version() -> str:
    return VERSION_FILE.read_text(encoding="utf-8").strip()


def release_dir(cell: str = DEFAULT_CELL) -> Path:
    return ROOT / ".release" / "cells" / cell


def env_file(cell: str = DEFAULT_CELL) -> Path:
    return release_dir(cell) / ".env.cell"


def project_name(cell: str = DEFAULT_CELL) -> str:
    safe = "".join(c if c.isalnum() else "-" for c in cell.lower()).strip("-") or DEFAULT_CELL
    return f"exais-vector-store-{safe}"


def compose_network_name(cell: str = DEFAULT_CELL) -> str:
    return f"{project_name(cell)}_default"


def normalize_registry_prefix(registry_prefix: str | None = None) -> str:
    return (registry_prefix or os.getenv("SVS_REGISTRY_PREFIX") or DEFAULT_REGISTRY_PREFIX).rstrip("/")


def image_tag(service: str, registry_prefix: str | None = None, product_version: str | None = None) -> str:
    if service not in APP_IMAGES:
        raise KeyError(f"unknown app service: {service}")
    return f"{normalize_registry_prefix(registry_prefix)}/{APP_IMAGES[service][1]}:{product_version or version()}"


def all_image_tags(registry_prefix: str | None = None, product_version: str | None = None) -> list[str]:
    return [image_tag(service, registry_prefix, product_version) for service in APP_IMAGES]


def compose_cmd() -> list[str]:
    if shutil.which("docker-compose"):
        return ["docker-compose"]
    if shutil.which("docker"):
        probe = subprocess.run(["docker", "compose", "version"], cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if probe.returncode == 0:
            return ["docker", "compose"]
    raise RuntimeError("Docker Compose was not found. Install docker-compose or the Docker compose plugin.")


def compose_base(cell: str = DEFAULT_CELL) -> list[str]:
    return compose_cmd() + ["--env-file", str(env_file(cell)), "-f", str(COMPOSE_FILE), "-p", project_name(cell)]


def printable_command(args: list[str]) -> str:
    return " ".join(quote_arg(str(a)) for a in args)


def quote_arg(value: str) -> str:
    if not value:
        return "''"
    if any(ch.isspace() for ch in value) or any(ch in value for ch in ['"', "'", "$", "&", "(", ")"]):
        return '"' + value.replace('"', '\\"') + '"'
    return value


def run(args: list[str], *, check: bool = True, cwd: Path = ROOT, env: dict[str, str] | None = None, timeout: int | None = None) -> subprocess.CompletedProcess[str]:
    print(f"$ {printable_command(args)}", flush=True)
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    proc = subprocess.run(
        args,
        cwd=cwd,
        env=merged_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    if proc.stdout:
        print(proc.stdout, end="" if proc.stdout.endswith("\n") else "\n", flush=True)
    print(f"[exit {proc.returncode}]", flush=True)
    if check and proc.returncode != 0:
        raise subprocess.CalledProcessError(proc.returncode, args, proc.stdout)
    return proc


def wait_for_services(cell: str, services: list[str], timeout_seconds: int = 240) -> None:
    deadline = time.time() + timeout_seconds
    names = [f"{project_name(cell)}-{service}-1" for service in services]
    while time.time() < deadline:
        unhealthy: list[str] = []
        for name in names:
            proc = run(
                ["docker", "inspect", "--format", "{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}", name],
                check=False,
            )
            status = (proc.stdout or "").strip()
            if status not in {"healthy", "running"}:
                unhealthy.append(name)
        if not unhealthy:
            return
        print(f"Waiting for healthy services: {', '.join(unhealthy)}", flush=True)
        time.sleep(5)
    raise TimeoutError(f"Timed out waiting for services: {', '.join(names)}")


def read_env(cell: str = DEFAULT_CELL) -> dict[str, str]:
    values: dict[str, str] = {}
    path = env_file(cell)
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value
    return values


def api_base(cell: str = DEFAULT_CELL) -> str:
    values = read_env(cell)
    return values.get("SVS_PUBLIC_API_BASE") or f"http://localhost:{values.get('SVS_API_PORT', '18080')}"


def ensure_env(cell: str = DEFAULT_CELL) -> None:
    if not env_file(cell).exists():
        raise FileNotFoundError(f"Missing generated env file: {env_file(cell)}. Run generate-cell-env.py first.")


def main_guard() -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
