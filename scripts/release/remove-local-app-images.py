from __future__ import annotations

import argparse

from release_common import APP_IMAGES, image_tag, run, version


def main() -> None:
    parser = argparse.ArgumentParser(description="Remove local app image tags so the cell must pull from registry.")
    parser.add_argument("--registry-prefix", default=None)
    parser.add_argument("--version", default=version())
    parser.add_argument("--service", choices=sorted(APP_IMAGES), action="append")
    args = parser.parse_args()
    services = args.service or list(APP_IMAGES)
    tags = [image_tag(service, args.registry_prefix, args.version) for service in services]
    run(["docker", "image", "rm", *tags], check=False)
    for tag in tags:
        run(["docker", "image", "inspect", tag], check=False)


if __name__ == "__main__":
    main()
