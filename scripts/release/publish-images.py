from __future__ import annotations

import argparse

from release_common import APP_IMAGES, image_tag, normalize_registry_prefix, run, version


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
            "Accept: application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json, application/vnd.docker.distribution.manifest.list.v2+json",
            f"http://127.0.0.1:5000/v2/{repository}/manifests/{product_version}",
        ])
        return
    raise SystemExit(result.returncode)


def main() -> None:
    parser = argparse.ArgumentParser(description="Push all versioned app images to a registry namespace.")
    parser.add_argument("--registry-prefix", default=None)
    parser.add_argument("--version", default=version())
    parser.add_argument("--service", choices=sorted(APP_IMAGES), action="append")
    args = parser.parse_args()
    services = args.service or list(APP_IMAGES)
    registry_prefix = normalize_registry_prefix(args.registry_prefix)
    for service in services:
        tag = image_tag(service, registry_prefix, args.version)
        run(["docker", "push", tag])
    for service in services:
        tag = image_tag(service, registry_prefix, args.version)
        inspect_manifest(tag, registry_prefix)


if __name__ == "__main__":
    main()
