"""Idempotently seed the versioned fixed-wing Demo scheme library."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from rflp_lite.adapters.sqlite_repository import SQLiteRepository
from rflp_lite.application.domain_packs import load_domain_pack
from rflp_lite.application.resources import resource_path
from rflp_lite.application.scheme_import_mapper import map_scheme_rows
from rflp_lite.application.workspaces import create_managed_workspace


def seed_demo_schemes(workspace: Path, pack_path: Path | None = None, data_path: Path | None = None) -> dict[str, object]:
    workspace = workspace.resolve()
    if not (workspace / "profile.json").is_file():
        create_managed_workspace(workspace.parent, workspace.name)
    pack_path = pack_path or resource_path("domain-packs/fixed-wing-v1.json")
    data_path = data_path or resource_path("examples/concept-design/demo-schemes.json")
    pack = load_domain_pack(pack_path)
    rows = json.loads(data_path.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise ValueError("Demo scheme data must contain an array")
    database = workspace / ".rflp" / "model.db"
    repository = SQLiteRepository(database)
    try:
        existing = {str(item.get("id")) for item in repository.scheme_records()}
        imported = map_scheme_rows(pack, rows, str(data_path), existing_ids=existing)
        with repository.transaction():
            repository.save_domain_pack(pack)
            repository.save_scheme_records(imported.records)
            repository.record_audit(
                "concept.demo_schemes_seeded",
                {
                    "source": str(data_path),
                    "accepted": len(imported.records),
                    "skipped": len(imported.skipped),
                    "rejected": len(imported.rejected),
                    "dataset_version": "fixed-wing-demo-v1",
                },
            )
        return {
            "status": "ok",
            "accepted": len(imported.records),
            "skipped": list(imported.skipped),
            "rejected": list(imported.rejected),
        }
    finally:
        repository.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--pack", type=Path)
    parser.add_argument("--data", type=Path)
    args = parser.parse_args()
    print(json.dumps(seed_demo_schemes(args.workspace, args.pack, args.data), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
