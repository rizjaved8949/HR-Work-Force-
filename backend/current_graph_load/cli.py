from __future__ import annotations

import argparse
import json

from .manifest import DEFAULT_STEP7_MANIFEST
from .service import CurrentSupabaseGraphLoadService
from .verify import verify_current_graph


WRITE_CONFIRMATION = "LOAD-CURRENT-SUPABASE-INTO-GRAPH"


def _tables(raw: str | None) -> set[str] | None:
    if not raw:
        return None
    return {item.strip() for item in raw.split(",") if item.strip()}


def main() -> None:
    parser = argparse.ArgumentParser(description="Step 7 current Supabase -> HR Knowledge Graph")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("manifest")

    preflight = sub.add_parser("preflight")
    preflight.add_argument("--tenant-id", required=True)
    preflight.add_argument("--tables")

    load = sub.add_parser("load")
    load.add_argument("--tenant-id", required=True)
    load.add_argument("--tables")
    load.add_argument("--confirm-write", required=True)

    verify = sub.add_parser("verify")
    verify.add_argument("--tenant-id", required=True)
    verify.add_argument("--employee-id")

    args = parser.parse_args()
    if args.command == "manifest":
        print(DEFAULT_STEP7_MANIFEST.load().model_dump_json(indent=2))
        return
    if args.command == "verify":
        print(json.dumps(
            verify_current_graph(tenant_id=args.tenant_id, employee_id=args.employee_id),
            indent=2, default=str,
        ))
        return

    service = CurrentSupabaseGraphLoadService.from_env()
    try:
        if args.command == "preflight":
            report = service.preflight(tenant_id=args.tenant_id, tables=_tables(args.tables))
            print(report.model_dump_json(indent=2))
            if not report.valid:
                raise SystemExit(2)
            return
        if args.command == "load":
            if args.confirm_write != WRITE_CONFIRMATION:
                raise SystemExit(
                    f"Graph write blocked. Pass --confirm-write {WRITE_CONFIRMATION} exactly."
                )
            report = service.load(tenant_id=args.tenant_id, tables=_tables(args.tables))
            print(report.model_dump_json(indent=2))
            return
    finally:
        service.close()


if __name__ == "__main__":
    main()
