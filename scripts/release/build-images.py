from __future__ import annotations

import argparse
import json
from pathlib import Path

from release_common import APP_IMAGES, ROOT, image_tag, run, version
from provenance_common import ImageDigest, format_manifest_report, verify_release_manifest, write_release_manifest


def _loads_json(value: str) -> object:
    value = value.strip()
    if not value or value == "<no value>":
        return None
    return json.loads(value)


def inspect_built_image(service: str, tag: str, product_version: str) -> ImageDigest:
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
    repository_digest = next((digest for digest in repo_digests if digest.startswith(tag.rsplit(":", 1)[0] + "@")), None)
    provenance = {
        "source": "docker-build",
        "dockerfile": APP_IMAGES[service][0],
        "digest_source": "local_image_id",
    }
    if repository_digest:
        provenance["repository_digest"] = repository_digest
        provenance["digest_source"] = "repository_digest"
    return ImageDigest(
        service=service,
        image=tag,
        tag=product_version,
        digest=repository_digest.rsplit("@", 1)[1] if repository_digest else image_id,
        image_id=image_id,
        size=int(size_raw),
        labels={str(key): str(value) for key, value in labels.items()},
        provenance=provenance,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Build all app images with the repo VERSION tag.")
    parser.add_argument("--registry-prefix", default=None)
    parser.add_argument("--version", default=version())
    parser.add_argument("--service", choices=sorted(APP_IMAGES), action="append")
    parser.add_argument("--manifest-output", type=Path, default=ROOT / ".release" / "image-build-manifest.json")
    args = parser.parse_args()
    services = args.service or list(APP_IMAGES)
    print(f"VERSION={args.version}")
    for service in services:
        dockerfile, _image_name = APP_IMAGES[service]
        tag = image_tag(service, args.registry_prefix, args.version)
        run([
            "docker",
            "build",
            "-f",
            dockerfile,
            "--build-arg",
            f"SVS_VERSION={args.version}",
            "--label",
            f"org.opencontainers.image.version={args.version}",
            "--label",
            f"com.exais.service={service}",
            "-t",
            tag,
            ".",
        ], cwd=ROOT)
    images: list[ImageDigest] = []
    for service in services:
        images.append(inspect_built_image(service, image_tag(service, args.registry_prefix, args.version), args.version))
    if set(services) != set(APP_IMAGES):
        print("Partial service build complete; release manifest requires the full APP_IMAGES set and was not written.")
        return
    manifest_path = write_release_manifest(images, args.manifest_output)
    report = verify_release_manifest(manifest_path)
    print(format_manifest_report(report))
    if not report.ok:
        raise SystemExit(1)
    print(f"Wrote release manifest: {manifest_path}")


if __name__ == "__main__":
    main()
