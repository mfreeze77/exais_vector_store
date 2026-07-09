from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from provenance_common import ImageDigest, format_manifest_report, verify_release_manifest
from release_common import normalize_registry_prefix, printable_command, release_dir, release_manifest_path, run, version

PROOF_SCHEMA_VERSION = 1
PROOF_FILENAME = "external-registry-proof.json"
CLAIM_BOUNDARY = (
    "External registry push and clean pull-by-digest proof only; this does not "
    "prove VPS readiness or customer-cell readiness."
)


@dataclass(frozen=True)
class CommandRecord:
    args: tuple[str, ...]
    returncode: int
    stdout: str

    def to_json(self) -> dict[str, object]:
        return {
            "args": list(self.args),
            "command": printable_command(list(self.args)),
            "returncode": self.returncode,
            "stdout": self.stdout,
        }


CommandRunner = Callable[[list[str]], subprocess.CompletedProcess[str]]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def proof_output_path(cell: str) -> Path:
    return release_dir(cell) / PROOF_FILENAME


def validate_external_registry_prefix(registry_prefix: str) -> str:
    normalized = normalize_registry_prefix(registry_prefix)
    host = normalized.split("/", 1)[0].lower()
    if not normalized or "/" not in normalized:
        raise ValueError("registry prefix must include a registry host and namespace, for example docker.io/expertaiservices")
    if "://" in normalized or "@" in normalized:
        raise ValueError("registry prefix must not include credentials or a URL scheme; run docker login separately")
    if host.startswith("localhost") or host.startswith("127.") or host.startswith("0.0.0.0"):
        raise ValueError("external registry proof requires a non-local registry prefix")
    return normalized


def validate_product_version(product_version: str) -> str:
    fixed = product_version.strip()
    if not fixed or fixed.lower() == "latest":
        raise ValueError("external registry proof requires a fixed VERSION value, not latest")
    return fixed


def python_script_command(script_name: str, *args: str) -> list[str]:
    return [sys.executable or "python", str(Path(__file__).resolve().parent / script_name), *args]


def initial_commands(registry_prefix: str, product_version: str, cell: str, manifest_path: Path) -> list[list[str]]:
    return [
        python_script_command("build-images.py", "--registry-prefix", registry_prefix, "--version", product_version),
        python_script_command(
            "publish-images.py",
            "--registry-prefix",
            registry_prefix,
            "--version",
            product_version,
            "--cell",
            cell,
            "--manifest-output",
            str(manifest_path),
        ),
        python_script_command("remove-local-app-images.py", "--registry-prefix", registry_prefix, "--version", product_version),
    ]


def repository_digest_reference(image: ImageDigest) -> str:
    if not image.digest:
        raise ValueError(f"release manifest image for {image.service} does not include a digest")
    tail = image.image.rsplit("/", 1)[-1]
    repository = image.image.rsplit(":", 1)[0] if ":" in tail else image.image
    return f"{repository}@{image.digest}"


def pull_digest_commands(images: tuple[ImageDigest, ...]) -> list[tuple[ImageDigest, list[str], list[str]]]:
    commands: list[tuple[ImageDigest, list[str], list[str]]] = []
    for image in images:
        digest_ref = repository_digest_reference(image)
        commands.append(
            (
                image,
                ["docker", "pull", digest_ref],
                [
                    "docker",
                    "image",
                    "inspect",
                    "--format",
                    "{{.Id}}\t{{.Size}}\t{{json .RepoDigests}}",
                    digest_ref,
                ],
            )
        )
    return commands


def run_recorded(args: list[str], runner: CommandRunner, records: list[CommandRecord]) -> subprocess.CompletedProcess[str]:
    completed = runner(args)
    record = CommandRecord(tuple(str(arg) for arg in args), int(completed.returncode), completed.stdout or "")
    records.append(record)
    if completed.returncode != 0:
        raise subprocess.CalledProcessError(completed.returncode, args, completed.stdout)
    return completed


def verify_manifest_for_external_proof(manifest_path: Path, registry_prefix: str, product_version: str) -> tuple[ImageDigest, ...]:
    report = verify_release_manifest(manifest_path)
    if not report.ok:
        print(format_manifest_report(report))
        raise SystemExit(1)
    issues: list[str] = []
    if report.registry_prefix != registry_prefix:
        issues.append(f"manifest registry_prefix {report.registry_prefix!r} does not match {registry_prefix!r}")
    if report.product_version != product_version:
        issues.append(f"manifest product_version {report.product_version!r} does not match {product_version!r}")
    if issues:
        for issue in issues:
            print(f"- EXTERNAL_REGISTRY_PROOF: {issue}")
        raise SystemExit(1)
    return report.images


def manifest_sha256(manifest_path: Path) -> str:
    return hashlib.sha256(manifest_path.read_bytes()).hexdigest()


def write_external_registry_proof(
    *,
    cell: str,
    registry_prefix: str,
    product_version: str,
    manifest_path: Path,
    proof_output: Path,
    images: tuple[ImageDigest, ...],
    records: list[CommandRecord],
) -> Path:
    pull_evidence = []
    for image in images:
        pull_evidence.append(
            {
                "service": image.service,
                "tagged_image": image.image,
                "digest": image.digest,
                "digest_reference": repository_digest_reference(image),
            }
        )
    payload = {
        "schema_version": PROOF_SCHEMA_VERSION,
        "proof_type": "external_registry_push",
        "generated_at": utc_now(),
        "cell": cell,
        "registry_prefix": registry_prefix,
        "product_version": product_version,
        "claim_boundary": CLAIM_BOUNDARY,
        "operator_prerequisites": [
            "Run docker login for the selected registry before this proof command.",
            "Do not put registry credentials in command arguments or committed files.",
        ],
        "release_manifest": str(manifest_path),
        "release_manifest_sha256": manifest_sha256(manifest_path),
        "pull_by_digest": pull_evidence,
        "commands": [record.to_json() for record in records],
        "verdict": "pass",
    }
    proof_output.parent.mkdir(parents=True, exist_ok=True)
    proof_output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return proof_output


def run_external_registry_proof(
    *,
    cell: str,
    registry_prefix: str,
    product_version: str,
    manifest_path: Path | None = None,
    proof_output: Path | None = None,
    runner: CommandRunner = run,
) -> Path:
    registry_prefix = validate_external_registry_prefix(registry_prefix)
    product_version = validate_product_version(product_version)
    manifest_path = manifest_path or release_manifest_path(cell)
    proof_output = proof_output or proof_output_path(cell)
    records: list[CommandRecord] = []

    commands = initial_commands(registry_prefix, product_version, cell, manifest_path)
    for command in commands[:2]:
        run_recorded(command, runner, records)

    images = verify_manifest_for_external_proof(manifest_path, registry_prefix, product_version)
    run_recorded(commands[2], runner, records)
    for _image, pull_command, inspect_command in pull_digest_commands(images):
        run_recorded(pull_command, runner, records)
        run_recorded(inspect_command, runner, records)

    return write_external_registry_proof(
        cell=cell,
        registry_prefix=registry_prefix,
        product_version=product_version,
        manifest_path=manifest_path,
        proof_output=proof_output,
        images=images,
        records=records,
    )


def print_dry_run(cell: str, registry_prefix: str, product_version: str, manifest_path: Path) -> None:
    registry_prefix = validate_external_registry_prefix(registry_prefix)
    product_version = validate_product_version(product_version)
    print("Dry run only; no Docker commands executed and no proof JSON written.")
    print(f"CELL={cell}")
    print(f"REGISTRY_PREFIX={registry_prefix}")
    print(f"VERSION={product_version}")
    print("Planned commands:")
    for command in initial_commands(registry_prefix, product_version, cell, manifest_path):
        print("$ " + printable_command(command))
    if manifest_path.exists():
        images = verify_manifest_for_external_proof(manifest_path, registry_prefix, product_version)
        for _image, pull_command, inspect_command in pull_digest_commands(images):
            print("$ " + printable_command(pull_command))
            print("$ " + printable_command(inspect_command))
    else:
        print(f"Pull-by-digest commands will be derived from {manifest_path} after publish-images.py writes it.")
    print(CLAIM_BOUNDARY)


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture external registry push and clean pull-by-digest proof.")
    parser.add_argument("--registry-prefix", required=True, help="External registry namespace, for example docker.io/expertaiservices")
    parser.add_argument("--version", default=version())
    parser.add_argument("--cell", default="external-registry")
    parser.add_argument("--manifest-output", type=Path, default=None)
    parser.add_argument("--proof-output", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    manifest_path = args.manifest_output or release_manifest_path(args.cell)
    if args.dry_run:
        print_dry_run(args.cell, args.registry_prefix, args.version, manifest_path)
        return

    proof_path = run_external_registry_proof(
        cell=args.cell,
        registry_prefix=args.registry_prefix,
        product_version=args.version,
        manifest_path=manifest_path,
        proof_output=args.proof_output,
    )
    print(f"Wrote external registry proof: {proof_path}")
    print(CLAIM_BOUNDARY)


if __name__ == "__main__":
    main()
