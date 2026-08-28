from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tarfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from backup_common import BackupArtifact, format_backup_manifest_report, validate_backup_manifest, write_backup_manifest
from release_common import (
    ROOT,
    compose_network_name,
    pinned_image_env_file,
    printable_command,
    project_name,
    release_dir,
    release_manifest_path,
    version,
)


BUNDLE_SCHEMA_VERSION = 1
DEFAULT_CELL = "ks-state-civics"
DEFAULT_CURL_IMAGE = "curlimages/curl:8.10.1"
DEFAULT_ALPINE_IMAGE = "alpine:3.20"
QDRANT_URL = "http://qdrant:6333"
WRITE_SERVICE_NAMES = ("api", "worker")
OBJECT_VOLUME_NAMES = ("object-store", "minio-data")


@dataclass(frozen=True)
class SnapshotRecord:
    collection: str
    snapshot_name: str
    relative_path: str
    size_bytes: int
    sha256: str
    create_response: str

    def to_json(self) -> dict[str, object]:
        return {
            "collection": self.collection,
            "snapshot_name": self.snapshot_name,
            "relative_path": self.relative_path,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "create_response": self.create_response,
        }


@dataclass(frozen=True)
class VolumeRecord:
    compose_volume: str
    source_volume: str
    relative_path: str
    size_bytes: int
    sha256: str

    def to_json(self) -> dict[str, object]:
        return {
            "compose_volume": self.compose_volume,
            "source_volume": self.source_volume,
            "relative_path": self.relative_path,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
        }


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def safe_component(value: str, fallback: str = "item") -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", value.strip()).strip(".-")
    return safe or fallback


def bundle_id(cell: str, stamp: str | None = None) -> str:
    return f"{safe_component(cell, 'cell')}-vps-restore-{stamp or utc_stamp()}"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_marker(path: Path, *, kind: str, status: str, message: str) -> None:
    write_json(
        path,
        {
            "kind": kind,
            "capture_status": status,
            "message": message,
            "generated_at": utc_now(),
        },
    )


def redact_command(args: Sequence[str]) -> str:
    return printable_command([str(arg) for arg in args])


def run_text(args: Sequence[str], *, check: bool = True, timeout: int = 300) -> subprocess.CompletedProcess[str]:
    print("$ " + redact_command(args), flush=True)
    result = subprocess.run(
        [str(arg) for arg in args],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    if result.stdout:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n", flush=True)
    print(f"[exit {result.returncode}]", flush=True)
    if check and result.returncode != 0:
        raise subprocess.CalledProcessError(result.returncode, [str(arg) for arg in args], result.stdout)
    return result


def compose_service_containers(project: str, service: str) -> list[str]:
    result = run_text(
        [
            "docker",
            "ps",
            "--filter",
            f"label=com.docker.compose.project={project}",
            "--filter",
            f"label=com.docker.compose.service={service}",
            "--format",
            "{{.Names}}",
        ],
        check=False,
        timeout=60,
    )
    return [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]


def first_service_container(project: str, service: str) -> str:
    containers = compose_service_containers(project, service)
    if not containers:
        raise RuntimeError(f"No running container found for compose project {project!r} service {service!r}")
    return containers[0]


def stop_write_services(project: str) -> list[str]:
    containers: list[str] = []
    for service in WRITE_SERVICE_NAMES:
        containers.extend(compose_service_containers(project, service))
    if containers:
        run_text(["docker", "stop", *containers], timeout=180)
    return containers


def restart_containers(containers: Sequence[str]) -> None:
    if containers:
        run_text(["docker", "start", *containers], timeout=180)


def docker_volume_exists(name: str) -> bool:
    result = run_text(["docker", "volume", "inspect", name], check=False, timeout=60)
    return result.returncode == 0


def pg_dump_from_container(project: str, destination: Path, *, timeout: int) -> None:
    postgres = first_service_container(project, "postgres")
    destination.parent.mkdir(parents=True, exist_ok=True)
    args = [
        "docker",
        "exec",
        postgres,
        "sh",
        "-lc",
        'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom',
    ]
    print("$ " + redact_command(args) + f" > {destination}", flush=True)
    with destination.open("wb") as handle:
        result = subprocess.run(
            args,
            cwd=ROOT,
            stdout=handle,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
    stderr = result.stderr.decode("utf-8", errors="replace") if result.stderr else ""
    if stderr:
        print(stderr, end="" if stderr.endswith("\n") else "\n", flush=True)
    print(f"[exit {result.returncode}]", flush=True)
    if result.returncode != 0:
        raise subprocess.CalledProcessError(result.returncode, args, stderr)


def qdrant_path(*parts: str, query: str = "") -> str:
    path = "/" + "/".join(quote(part, safe="") for part in parts)
    return f"{path}?{query}" if query else path


def qdrant_curl_args(
    *,
    network: str,
    method: str,
    path: str,
    curl_image: str,
    qdrant_api_key_env: str,
    output_relative_path: str | None = None,
    bundle_dir: Path | None = None,
) -> list[str]:
    script = """set -eu
if [ -n "${QDRANT_OUTPUT:-}" ]; then
  if [ -n "${SVS_QDRANT_API_KEY:-}" ]; then
    curl -fsS -X "$QDRANT_METHOD" -H "api-key: $SVS_QDRANT_API_KEY" "$QDRANT_URL$QDRANT_PATH" --output "$QDRANT_OUTPUT"
  else
    curl -fsS -X "$QDRANT_METHOD" "$QDRANT_URL$QDRANT_PATH" --output "$QDRANT_OUTPUT"
  fi
else
  if [ -n "${SVS_QDRANT_API_KEY:-}" ]; then
    curl -fsS -X "$QDRANT_METHOD" -H "api-key: $SVS_QDRANT_API_KEY" "$QDRANT_URL$QDRANT_PATH"
  else
    curl -fsS -X "$QDRANT_METHOD" "$QDRANT_URL$QDRANT_PATH"
  fi
fi
"""
    args = [
        "docker",
        "run",
        "--rm",
        "--network",
        network,
        "-e",
        "SVS_QDRANT_API_KEY",
        "-e",
        f"QDRANT_METHOD={method}",
        "-e",
        f"QDRANT_URL={QDRANT_URL}",
        "-e",
        f"QDRANT_PATH={path}",
    ]
    if output_relative_path:
        if bundle_dir is None:
            raise ValueError("bundle_dir is required when output_relative_path is set")
        args.extend(
            [
                "--mount",
                f"type=bind,source={bundle_dir.resolve()},target=/bundle",
                "-e",
                f"QDRANT_OUTPUT=/bundle/{output_relative_path}",
            ]
        )
    args.extend(["--entrypoint", "sh", curl_image, "-c", script])
    return args


def qdrant_subprocess_env(qdrant_api_key_env: str) -> dict[str, str]:
    env = os.environ.copy()
    if qdrant_api_key_env != "SVS_QDRANT_API_KEY":
        env["SVS_QDRANT_API_KEY"] = os.getenv(qdrant_api_key_env, "")
    return env


def run_qdrant_json(
    *,
    network: str,
    method: str,
    path: str,
    curl_image: str,
    qdrant_api_key_env: str,
    timeout: int,
) -> dict[str, object]:
    args = qdrant_curl_args(
        network=network,
        method=method,
        path=path,
        curl_image=curl_image,
        qdrant_api_key_env=qdrant_api_key_env,
    )
    print("$ " + redact_command(args), flush=True)
    result = subprocess.run(
        args,
        cwd=ROOT,
        env=qdrant_subprocess_env(qdrant_api_key_env),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    if result.stdout:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n", flush=True)
    print(f"[exit {result.returncode}]", flush=True)
    if result.returncode != 0:
        raise subprocess.CalledProcessError(result.returncode, [str(arg) for arg in args], result.stdout)
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Qdrant response was not JSON for {method} {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"Qdrant response must be a JSON object for {method} {path}")
    return payload


def run_qdrant_download(
    *,
    network: str,
    path: str,
    destination_relative: str,
    bundle_dir: Path,
    curl_image: str,
    qdrant_api_key_env: str,
    timeout: int,
) -> None:
    args = qdrant_curl_args(
        network=network,
        method="GET",
        path=path,
        curl_image=curl_image,
        qdrant_api_key_env=qdrant_api_key_env,
        output_relative_path=destination_relative,
        bundle_dir=bundle_dir,
    )
    print("$ " + redact_command(args), flush=True)
    result = subprocess.run(
        args,
        cwd=ROOT,
        env=qdrant_subprocess_env(qdrant_api_key_env),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    if result.stdout:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n", flush=True)
    print(f"[exit {result.returncode}]", flush=True)
    if result.returncode != 0:
        raise subprocess.CalledProcessError(result.returncode, [str(arg) for arg in args], result.stdout)


def qdrant_collections(payload: Mapping[str, object]) -> list[str]:
    result = payload.get("result")
    if not isinstance(result, Mapping):
        return []
    raw_collections = result.get("collections")
    if not isinstance(raw_collections, list):
        return []
    collections: list[str] = []
    for item in raw_collections:
        if isinstance(item, Mapping) and isinstance(item.get("name"), str) and item["name"]:
            collections.append(str(item["name"]))
    return sorted(collections)


def qdrant_snapshot_name(payload: Mapping[str, object]) -> str:
    result = payload.get("result")
    if isinstance(result, Mapping) and isinstance(result.get("name"), str) and result["name"]:
        return str(result["name"])
    raise RuntimeError("Qdrant snapshot response did not include result.name")


def export_qdrant_snapshots(
    *,
    bundle_dir: Path,
    network: str,
    collections: Sequence[str] | None,
    curl_image: str,
    qdrant_api_key_env: str,
    timeout: int,
) -> list[SnapshotRecord]:
    qdrant_dir = bundle_dir / "qdrant"
    qdrant_dir.mkdir(parents=True, exist_ok=True)
    if collections:
        selected = sorted(set(collections))
    else:
        selected = qdrant_collections(
            run_qdrant_json(
                network=network,
                method="GET",
                path="/collections",
                curl_image=curl_image,
                qdrant_api_key_env=qdrant_api_key_env,
                timeout=timeout,
            )
        )
    records: list[SnapshotRecord] = []
    for collection in selected:
        create_response = run_qdrant_json(
            network=network,
            method="POST",
            path=qdrant_path("collections", collection, "snapshots", query="wait=true"),
            curl_image=curl_image,
            qdrant_api_key_env=qdrant_api_key_env,
            timeout=timeout,
        )
        snapshot_name = qdrant_snapshot_name(create_response)
        collection_dir = f"qdrant/{safe_component(collection, 'collection')}"
        response_relative = f"{collection_dir}/create-response.json"
        write_json(bundle_dir / response_relative, create_response)
        snapshot_relative = f"{collection_dir}/{safe_component(snapshot_name, 'snapshot.snapshot')}"
        (bundle_dir / snapshot_relative).parent.mkdir(parents=True, exist_ok=True)
        run_qdrant_download(
            network=network,
            path=qdrant_path("collections", collection, "snapshots", snapshot_name),
            destination_relative=snapshot_relative,
            bundle_dir=bundle_dir,
            curl_image=curl_image,
            qdrant_api_key_env=qdrant_api_key_env,
            timeout=timeout,
        )
        snapshot_path = bundle_dir / snapshot_relative
        records.append(
            SnapshotRecord(
                collection=collection,
                snapshot_name=snapshot_name,
                relative_path=snapshot_relative,
                size_bytes=snapshot_path.stat().st_size,
                sha256=sha256_file(snapshot_path),
                create_response=response_relative,
            )
        )
    write_json(
        qdrant_dir / "snapshots.json",
        {
            "schema_version": BUNDLE_SCHEMA_VERSION,
            "generated_at": utc_now(),
            "qdrant_url": QDRANT_URL,
            "snapshot_count": len(records),
            "collections": [record.to_json() for record in records],
            "restore": {
                "method": "POST /collections/{collection_name}/snapshots/upload?wait=true&priority=snapshot",
                "notes": "Use the same Qdrant minor version or the next minor version when restoring collection snapshots.",
            },
        },
    )
    return records


def archive_volume(
    *,
    cell: str,
    compose_volume: str,
    bundle_dir: Path,
    alpine_image: str,
    timeout: int,
) -> VolumeRecord | None:
    project = project_name(cell)
    source_volume = f"{project}_{compose_volume}"
    if not docker_volume_exists(source_volume):
        return None
    relative_path = f"object-store/volumes/{safe_component(compose_volume, 'volume')}.tar.gz"
    destination = bundle_dir / relative_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    args = [
        "docker",
        "run",
        "--rm",
        "--mount",
        f"type=volume,source={source_volume},target=/source,readonly",
        "--mount",
        f"type=bind,source={destination.parent.resolve()},target=/dest",
        "-e",
        f"SVS_TAR_NAME={destination.name}",
        "--entrypoint",
        "sh",
        alpine_image,
        "-c",
        'cd /source && tar -czf "/dest/$SVS_TAR_NAME" .',
    ]
    run_text(args, timeout=timeout)
    return VolumeRecord(
        compose_volume=compose_volume,
        source_volume=source_volume,
        relative_path=relative_path,
        size_bytes=destination.stat().st_size,
        sha256=sha256_file(destination),
    )


def export_object_volumes(
    *,
    cell: str,
    bundle_dir: Path,
    alpine_image: str,
    timeout: int,
    allow_missing_volumes: bool,
) -> list[VolumeRecord]:
    records: list[VolumeRecord] = []
    missing: list[str] = []
    for compose_volume in OBJECT_VOLUME_NAMES:
        record = archive_volume(
            cell=cell,
            compose_volume=compose_volume,
            bundle_dir=bundle_dir,
            alpine_image=alpine_image,
            timeout=timeout,
        )
        if record is None:
            missing.append(f"{project_name(cell)}_{compose_volume}")
        else:
            records.append(record)
    if missing and not allow_missing_volumes:
        raise RuntimeError("Required object-store Docker volumes are missing: " + ", ".join(missing))
    write_json(
        bundle_dir / "object-store" / "volumes.json",
        {
            "schema_version": BUNDLE_SCHEMA_VERSION,
            "generated_at": utc_now(),
            "volume_count": len(records),
            "missing_volumes": missing,
            "volumes": [record.to_json() for record in records],
        },
    )
    return records


def copy_optional_config(cell: str, bundle_dir: Path) -> list[str]:
    copied: list[str] = []
    config_dir = bundle_dir / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    candidates = [
        (ROOT / "instances" / cell / "instance.yaml", "config/instance.yaml"),
        (release_manifest_path(cell), "config/local-release-manifest.json"),
        (pinned_image_env_file(cell), "config/local-env-images.txt"),
    ]
    for source, relative in candidates:
        if source.is_file():
            target = bundle_dir / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())
            copied.append(relative)
    write_json(
        config_dir / "config-metadata.json",
        {
            "capture_status": "captured",
            "cell": cell,
            "compose_project": project_name(cell),
            "product_version": version(),
            "copied_files": copied,
            "notes": (
                "Secret env files are intentionally excluded. Local release-manifest and image-pin "
                "files are copied only as source-cell provenance; the VPS must use a separately "
                "approved external-registry release manifest."
            ),
            "generated_at": utc_now(),
        },
    )
    return copied


def write_checksums(bundle_dir: Path) -> Path:
    files = sorted(
        path
        for path in bundle_dir.rglob("*")
        if path.is_file() and path.name not in {"CHECKSUMS.sha256", "manifest.json"}
    )
    checksum_path = bundle_dir / "CHECKSUMS.sha256"
    checksum_path.write_text(
        "".join(f"{sha256_file(path)}  ./{path.relative_to(bundle_dir).as_posix()}\n" for path in files),
        encoding="utf-8",
    )
    return checksum_path


def write_restore_notes(bundle_dir: Path, *, cell: str, snapshots: Sequence[SnapshotRecord], volumes: Sequence[VolumeRecord]) -> None:
    lines = [
        f"# {cell} VPS Restore Bundle",
        "",
        "This bundle is a data handoff artifact for a freshly booted ExAIS customer cell.",
        "Do not commit extracted secret env files. This bundle intentionally excludes `.env.cell`.",
        "",
        "## Preflight",
        "",
        "```bash",
        "python scripts/release/backup_common.py validate <bundle-dir>/manifest.json --print-artifacts",
        "( cd <bundle-dir> && sha256sum -c CHECKSUMS.sha256 )",
        "```",
        "",
        "## Postgres",
        "",
        "Stop API and worker writes before restore, then run:",
        "",
        "```bash",
        "docker exec -i exais-vector-store-ks-state-civics-postgres-1 sh -lc 'pg_restore --clean --if-exists --no-owner -U \"$POSTGRES_USER\" -d \"$POSTGRES_DB\"' < postgres/svs.dump",
        "```",
        "",
        "## Qdrant",
        "",
        "Restore each collection snapshot with snapshot priority:",
        "",
        "```bash",
    ]
    for record in snapshots:
        checksum_arg = f"&checksum={record.sha256}"
        lines.append(
            "docker run --rm --network exais-vector-store-ks-state-civics_default "
            "-v \"$PWD\":/bundle curlimages/curl:8.10.1 -fsS -X POST "
            f"'http://qdrant:6333/collections/{quote(record.collection, safe='')}/snapshots/upload?wait=true&priority=snapshot{checksum_arg}' "
            f"-F 'snapshot=@/bundle/{record.relative_path}'"
        )
    if not snapshots:
        lines.append("# No Qdrant collections were found in the source cell.")
    lines.extend(
        [
            "```",
            "",
            "## Object Volumes",
            "",
            "Restore volume tarballs only while services using those volumes are stopped.",
            "",
            "```bash",
        ]
    )
    for record in volumes:
        lines.append(
            f"docker run --rm -v {record.source_volume}:/dest -v \"$PWD\":/bundle alpine:3.20 "
            f"sh -lc 'cd /dest && tar -xzf /bundle/{record.relative_path}'"
        )
    if not volumes:
        lines.append("# No object-store volume tarballs were exported.")
    lines.extend(["```", ""])
    (bundle_dir / "RESTORE.md").write_text("\n".join(lines), encoding="utf-8")


def write_bundle_metadata(
    bundle_dir: Path,
    *,
    cell: str,
    snapshots: Sequence[SnapshotRecord],
    volumes: Sequence[VolumeRecord],
    quiesced_containers: Sequence[str],
) -> None:
    write_json(
        bundle_dir / "bundle-metadata.json",
        {
            "schema_version": BUNDLE_SCHEMA_VERSION,
            "generated_at": utc_now(),
            "cell": cell,
            "compose_project": project_name(cell),
            "compose_network": compose_network_name(cell),
            "product_version": version(),
            "quiesced_write_containers": list(quiesced_containers),
            "qdrant_snapshot_count": len(snapshots),
            "object_volume_count": len(volumes),
            "claim_boundary": (
                "Local restore bundle export only. VPS readiness also requires external registry proof, "
                "production env preflight, edge TLS, firewall rules, and caller lifecycle proof."
            ),
        },
    )


def backup_artifacts() -> list[BackupArtifact]:
    return [
        BackupArtifact("postgres_metadata", "postgres/svs.dump", True, "docker_exec_pg_dump"),
        BackupArtifact("qdrant_vectors", "qdrant/snapshots.json", True, "qdrant_collection_snapshot_api"),
        BackupArtifact("opensearch_sparse", "opensearch/sparse-unavailable.json", True, "metadata_marker"),
        BackupArtifact("object_store", "object-store/volumes.json", True, "docker_volume_tar"),
        BackupArtifact("config_metadata", "config/config-metadata.json", True, "instance_manifest"),
        BackupArtifact("audit_export", "audit/audit-unavailable.json", True, "metadata_marker"),
        BackupArtifact("checksum_metadata", "CHECKSUMS.sha256", True, "sha256sum"),
    ]


def create_bundle_archive(bundle_dir: Path) -> tuple[Path, Path]:
    archive_path = bundle_dir.with_suffix(".tar.gz")
    with tarfile.open(archive_path, "w:gz") as archive:
        archive.add(bundle_dir, arcname=bundle_dir.name)
    checksum_path = Path(str(archive_path) + ".sha256")
    checksum_path.write_text(f"{sha256_file(archive_path)}  {archive_path.name}\n", encoding="utf-8")
    return archive_path, checksum_path


def export_cell_restore_bundle(
    *,
    cell: str,
    output_root: Path,
    collections: Sequence[str] | None,
    quiesce_writes: bool,
    curl_image: str,
    alpine_image: str,
    qdrant_api_key_env: str,
    timeout: int,
    allow_missing_volumes: bool,
) -> Path:
    cell_project = project_name(cell)
    bundle_dir = output_root / bundle_id(cell)
    if bundle_dir.exists():
        raise FileExistsError(f"Bundle directory already exists: {bundle_dir}")
    for relative in ("postgres", "qdrant", "opensearch", "object-store", "config", "audit"):
        (bundle_dir / relative).mkdir(parents=True, exist_ok=True)

    stopped: list[str] = []
    try:
        if quiesce_writes:
            stopped = stop_write_services(cell_project)
        pg_dump_from_container(cell_project, bundle_dir / "postgres" / "svs.dump", timeout=timeout)
        snapshots = export_qdrant_snapshots(
            bundle_dir=bundle_dir,
            network=compose_network_name(cell),
            collections=collections,
            curl_image=curl_image,
            qdrant_api_key_env=qdrant_api_key_env,
            timeout=timeout,
        )
        volumes = export_object_volumes(
            cell=cell,
            bundle_dir=bundle_dir,
            alpine_image=alpine_image,
            timeout=timeout,
            allow_missing_volumes=allow_missing_volumes,
        )
        copy_optional_config(cell, bundle_dir)
        write_marker(
            bundle_dir / "opensearch" / "sparse-unavailable.json",
            kind="opensearch_sparse",
            status="not_configured",
            message="OpenSearch sparse index export is not configured for this cell.",
        )
        write_marker(
            bundle_dir / "audit" / "audit-unavailable.json",
            kind="audit_export",
            status="not_configured",
            message="Audit export path is not configured for this cell restore bundle.",
        )
        write_restore_notes(bundle_dir, cell=cell, snapshots=snapshots, volumes=volumes)
        write_bundle_metadata(bundle_dir, cell=cell, snapshots=snapshots, volumes=volumes, quiesced_containers=stopped)
        write_checksums(bundle_dir)
        manifest_path = write_backup_manifest(bundle_dir, backup_artifacts())
        report = validate_backup_manifest(manifest_path)
        print(format_backup_manifest_report(report, include_artifacts=True), flush=True)
        if not report.ok:
            raise RuntimeError("Generated restore bundle manifest did not validate")
        archive_path, checksum_path = create_bundle_archive(bundle_dir)
        print(f"Wrote VPS restore bundle: {archive_path}", flush=True)
        print(f"Wrote VPS restore checksum: {checksum_path}", flush=True)
        return archive_path
    finally:
        restart_containers(stopped)


def print_dry_run(args: argparse.Namespace) -> None:
    output_root = args.output_root or release_dir(args.cell) / "vps-handoff"
    print("Dry run only; no Docker commands executed and no bundle written.")
    print(f"CELL={args.cell}")
    print(f"COMPOSE_PROJECT={project_name(args.cell)}")
    print(f"COMPOSE_NETWORK={compose_network_name(args.cell)}")
    print(f"OUTPUT_ROOT={output_root}")
    print(f"COLLECTIONS={','.join(args.collection or ['<all-qdrant-collections>'])}")
    print(f"QUIESCE_WRITES={bool(args.quiesce_writes)}")
    print("Planned artifacts: postgres/svs.dump, qdrant/snapshots.json, object-store/volumes.json, config/config-metadata.json, manifest.json, CHECKSUMS.sha256")
    print("Secret env files are excluded.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Export a restorable data bundle for moving a customer cell to a VPS.")
    parser.add_argument("--cell", default=DEFAULT_CELL)
    parser.add_argument("--output-root", type=Path, default=None)
    parser.add_argument("--collection", action="append", help="Qdrant collection to snapshot. Repeat to limit the export; omitted means all collections.")
    parser.add_argument("--quiesce-writes", action="store_true", help="Temporarily stop API and worker containers while capturing Postgres/Qdrant.")
    parser.add_argument("--curl-image", default=DEFAULT_CURL_IMAGE)
    parser.add_argument("--alpine-image", default=DEFAULT_ALPINE_IMAGE)
    parser.add_argument("--qdrant-api-key-env", default="SVS_QDRANT_API_KEY")
    parser.add_argument("--timeout-seconds", type=int, default=600)
    parser.add_argument("--allow-missing-volumes", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.dry_run:
        print_dry_run(args)
        return

    output_root = args.output_root or release_dir(args.cell) / "vps-handoff"
    output_root.mkdir(parents=True, exist_ok=True)
    export_cell_restore_bundle(
        cell=args.cell,
        output_root=output_root,
        collections=args.collection,
        quiesce_writes=args.quiesce_writes,
        curl_image=args.curl_image,
        alpine_image=args.alpine_image,
        qdrant_api_key_env=args.qdrant_api_key_env,
        timeout=args.timeout_seconds,
        allow_missing_volumes=args.allow_missing_volumes,
    )


if __name__ == "__main__":
    main()
