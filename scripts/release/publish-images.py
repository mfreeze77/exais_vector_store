from __future__ import annotations

import argparse
import json
from pathlib import Path

from release_common import APP_IMAGES, DEFAULT_CELL, image_tag, normalize_registry_prefix, release_manifest_path, run, version
from provenance_common import ImageDigest, format_manifest_report, verify_release_manifest, write_release_manifest

ACCEPT_HEADER = (
    "Accept: application/vnd.oci.image.manifest.v1+json, "
    "application/vnd.docker.distribution.manifest.v2+json, "
    "application/vnd.docker.distribution.manifest.list.v2+json"
)


def _loads_json(value: str) -> object:
    value = value.strip()
    if not value or value == "<no value>":
        return None
    return json.loads(value)


def inspect_manifest(tag: str, registry_prefix: str) -> None:
    result = run(["docker", "manifest", "inspect", tag], check=False)
    if result.returncode == 0:
        return
    host = registry_prefix.split("/", 1)[0]
    if host.startswith("localhost:") or host.startswith("127.0.0.1:"):
        repository_tag = tag.split("/", 1)[1]
        repository, product_version = repository_tag.rsplit(":", 1)
        run([
            "docker",
            "run",
            "--rm",
            "--network",
            "container:exais-local-registry",
            "curlimages/curl:8.10.1",
            "-fsS",
            "-H",
            ACCEPT_HEADER,
            f"http://127.0.0.1:5000/v2/{repository}/manifests/{product_version}",
        ])
        return
    raise SystemExit(result.returncode)


def local_registry_digest(tag: str, registry_prefix: str) -> str | None:
    host = registry_prefix.split("/", 1)[0]
    if not (host.startswith("localhost:") or host.startswith("127.0.0.1:")):
        return None
    repository_tag = tag.split("/", 1)[1]
    repository, product_version = repository_tag.rsplit(":", 1)
    result = run([
        "docker",
        "run",
        "--rm",
        "--network",
        "container:exais-local-registry",
        "curlimages/curl:8.10.1",
        "-fsS",
        "-D",
        "-",
        "-o",
        "/dev/null",
        "-H",
        ACCEPT_HEADER,
        f"http://127.0.0.1:5000/v2/{repository}/manifests/{product_version}",
    ], check=False)
    if result.returncode != 0:
        return None
    for raw in (result.stdout or "").splitlines():
        if raw.lower().startswith("docker-content-digest:"):
            return raw.split(":", 1)[1].strip()
    return None


def inspect_published_image(service: str, tag: str, product_version: str, registry_prefix: str) -> ImageDigest:
    result = run([
        "docker",
        "image",
        "inspect",
        "--format",
        "{{.Id}}\t{{.Size}}\t{{json .RepoDigests}}\t{{json .Config.Labels}}",
        tag,
    ])
    line = (result.stdout or "").strip().splitlines()[-1]
    image_id, size_raw, repo_digests_raw, labels_raw = line.split("\t", 3)
    repo_digests = _loads_json(repo_digests_raw) or []
    labels = _loads_json(labels_raw) or {}
    repository = tag.rsplit(":", 1)[0]
    repository_digest = next((digest for digest in repo_digests if digest.startswith(repository + "@")), None)
    registry_digest = local_registry_digest(tag, registry_prefix)
    digest = registry_digest or (repository_digest.rsplit("@", 1)[1] if repository_digest else image_id)
    provenance = {
        "source": "docker-push",
        "dockerfile": APP_IMAGES[service][0],
        "digest_source": "registry_header" if registry_digest else "repository_digest" if repository_digest else "local_image_id",
    }
    if repository_digest:
        provenance["repository_digest"] = repository_digest
    return ImageDigest(
        service=service,
        image=tag,
        tag=product_version,
        digest=digest,
        image_id=image_id,
        size=int(size_raw),
        labels={str(key): str(value) for key, value in labels.items()},
        provenance=provenance,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Push all versioned app images to a registry namespace.")
    parser.add_argument("--registry-prefix", default=None)
    parser.add_argument("--version", default=version())
    parser.add_argument("--service", choices=sorted(APP_IMAGES), action="append")
    parser.add_argument("--cell", default=DEFAULT_CELL)
    parser.add_argument("--manifest-output", type=Path, default=None)
    args = parser.parse_args()
    services = args.service or list(APP_IMAGES)
    registry_prefix = normalize_registry_prefix(args.registry_prefix)
    for service in services:
        tag = image_tag(service, registry_prefix, args.version)
        run(["docker", "push", tag])
    for service in services:
        tag = image_tag(service, registry_prefix, args.version)
        inspect_manifest(tag, registry_prefix)
    if set(services) != set(APP_IMAGES):
        print("Partial service publish complete; release manifest requires the full APP_IMAGES set and was not written.")
        return
    images = [inspect_published_image(service, image_tag(service, registry_prefix, args.version), args.version, registry_prefix) for service in services]
    manifest_path = write_release_manifest(images, args.manifest_output or release_manifest_path(args.cell))
    report = verify_release_manifest(manifest_path)
    print(format_manifest_report(report))
    if not report.ok:
        raise SystemExit(1)
    print(f"Wrote release manifest: {manifest_path}")


if __name__ == "__main__":
    main()
