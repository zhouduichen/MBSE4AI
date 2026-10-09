"""Fail-closed readiness checks for labelled GitHub Actions runners."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from urllib.request import Request, urlopen


RunnerTarget = tuple[str, tuple[str, ...]]


def parse_target(value: str) -> RunnerTarget:
    """Parse ``name=label,label`` into a normalized target contract."""

    name, separator, labels = value.partition("=")
    normalized_name = name.strip()
    normalized_labels = tuple(
        label.strip()
        for label in labels.split(",")
        if label.strip()
    )
    if not separator or not normalized_name or not normalized_labels:
        raise ValueError(
            "runner target must use name=label,label with at least one label"
        )
    return normalized_name, normalized_labels


def evaluate_runner_targets(
    payload: Mapping[str, object],
    targets: Sequence[RunnerTarget],
) -> dict[str, object]:
    """Return an auditable availability result without making network calls."""

    raw_runners = payload.get("runners", ())
    runners = [item for item in raw_runners if isinstance(item, Mapping)]
    target_results: dict[str, dict[str, object]] = {}
    for name, required_labels in targets:
        required = {label.casefold() for label in required_labels}
        matches: list[dict[str, object]] = []
        for runner in runners:
            labels = {
                str(item.get("name", "")).casefold()
                for item in runner.get("labels", ())
                if isinstance(item, Mapping)
            }
            if str(runner.get("status", "")).casefold() != "online":
                continue
            if not required.issubset(labels):
                continue
            matches.append({
                "name": str(runner.get("name", "")),
                "busy": bool(runner.get("busy", False)),
                "status": str(runner.get("status", "")),
            })
        target_results[name] = {
            "required_labels": list(required_labels),
            "available": bool(matches),
            "matches": matches,
        }
    return {
        "available": bool(targets) and all(
            bool(item["available"]) for item in target_results.values()
        ) if targets else True,
        "runner_count": len(runners),
        "targets": target_results,
    }


def fetch_runner_payload(api_url: str, token: str) -> Mapping[str, object]:
    """Fetch runner metadata using the ephemeral workflow token."""

    request = Request(
        api_url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urlopen(request, timeout=30) as response:  # noqa: S310 - fixed GitHub API URL from workflow
        payload = json.load(response)
    if not isinstance(payload, Mapping):
        raise ValueError("GitHub runner API returned a non-object payload")
    return payload


def wait_for_runner_targets(
    api_url: str,
    token: str,
    targets: Sequence[RunnerTarget],
    *,
    timeout_seconds: int = 600,
    poll_seconds: int = 20,
    fetch: Callable[[str, str], Mapping[str, object]] = fetch_runner_payload,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, object]:
    """Poll until every target has an online labelled runner or fail closed."""

    if timeout_seconds < 0 or poll_seconds <= 0:
        raise ValueError("timeout_seconds must be non-negative and poll_seconds positive")
    deadline = clock() + timeout_seconds
    attempts = 0
    latest: dict[str, object] = {"available": False, "targets": {}}
    while True:
        attempts += 1
        latest = dict(evaluate_runner_targets(fetch(api_url, token), targets))
        latest["attempts"] = attempts
        if latest.get("available") is True:
            return latest
        remaining = deadline - clock()
        if remaining <= 0:
            latest["timed_out"] = True
            return latest
        sleep(min(float(poll_seconds), remaining))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", required=True)
    parser.add_argument("--token", default=os.environ.get("GITHUB_TOKEN", ""))
    parser.add_argument("--target", action="append", default=[])
    parser.add_argument("--timeout-seconds", type=int, default=600)
    parser.add_argument("--poll-seconds", type=int, default=20)
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if not args.token:
        print("GitHub Actions API token is required", file=sys.stderr)
        return 2
    try:
        targets = tuple(parse_target(item) for item in args.target)
        result = wait_for_runner_targets(
            args.api_url,
            args.token,
            targets,
            timeout_seconds=args.timeout_seconds,
            poll_seconds=args.poll_seconds,
        )
    except (ValueError, OSError) as exc:
        print(f"runner readiness error: {exc}", file=sys.stderr)
        return 2
    serialized = json.dumps(result, ensure_ascii=False, sort_keys=True)
    print(serialized)
    if args.output:
        args.output.write_text(serialized + "\n", encoding="utf-8")
    if result.get("available") is not True:
        print("required labelled GitHub Actions runner is not online", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
