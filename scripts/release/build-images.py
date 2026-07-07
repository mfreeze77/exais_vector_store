from __future__ import annotations

import argparse

from release_common import APP_IMAGES, ROOT, image_tag, run, version


def main() -> None:
    parser = argparse.ArgumentParser(description="Build all app images with the repo VERSION tag.")
    parser.add_argument("--registry-prefix", default=None)
    parser.add_argument("--version", default=version())
    parser.add_argument("--service", choices=sorted(APP_IMAGES), action="append")
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
    for service in services:
        run([
            "docker",
            "image",
            "inspect",
            "--format",
            "{{index .RepoTags 0}}\t{{.Id}}\t{{.Size}}",
            image_tag(service, args.registry_prefix, args.version),
        ])


if __name__ == "__main__":
    main()
