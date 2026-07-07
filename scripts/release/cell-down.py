from __future__ import annotations

import argparse

from release_common import DEFAULT_CELL, compose_base, ensure_env, run


def main() -> None:
    parser = argparse.ArgumentParser(description="Stop a local cell. Add --volumes for a clean-cell reset.")
    parser.add_argument("--cell", default=DEFAULT_CELL)
    parser.add_argument("--volumes", action="store_true")
    args = parser.parse_args()
    ensure_env(args.cell)
    cmd = compose_base(args.cell) + ["down"]
    if args.volumes:
        cmd.append("--volumes")
    run(cmd)


if __name__ == "__main__":
    main()
