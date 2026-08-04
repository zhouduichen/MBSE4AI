from __future__ import annotations

import argparse
from collections.abc import Sequence

from rflp_lite import __version__


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rflp")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("version", help="show the installed version")
    args = parser.parse_args(argv)
    if args.command == "version":
        print(f"rflp-lite {__version__}")
        return 0
    return 2


def entrypoint() -> None:
    raise SystemExit(main())

