"""Step 13 production-readiness CLI.

Examples:
  python -m production.cli version
  python -m production.cli readiness --tenant-id ORGANIZATION-001
  python -m production.cli release-gate --tenant-id ORGANIZATION-001
  python -m production.cli release-gate --tenant-id ORGANIZATION-001 --production --strict
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env", override=True)

from .config import ProductionSettings
from .service import ProductionReadinessService
from .versioning import current_version_info


def _supabase_check() -> bool:
    from auth.supabase_client import get_supabase_admin_client
    client = get_supabase_admin_client()
    client.table("organization_master").select("Organization_ID").limit(1).execute()
    return True


def _service() -> ProductionReadinessService:
    from graph.neo4j_repository import Neo4jGraphRepository
    repository = Neo4jGraphRepository.from_env()
    return ProductionReadinessService(
        project_root=ROOT,
        repository=repository,
        settings=ProductionSettings.from_env(),
        supabase_check=_supabase_check,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Step 13 production readiness")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("version")

    ready = sub.add_parser("readiness")
    ready.add_argument("--tenant-id", default="ORGANIZATION-001")
    ready.add_argument("--strict", action="store_true")

    gate = sub.add_parser("release-gate")
    gate.add_argument("--tenant-id", default="ORGANIZATION-001")
    gate.add_argument("--production", action="store_true")
    gate.add_argument("--strict", action="store_true")

    args = parser.parse_args()
    if args.command == "version":
        print(json.dumps(current_version_info(root=ROOT).model_dump(mode="json"), indent=2))
        return

    service = _service()
    try:
        if args.command == "readiness":
            report = service.readiness(args.tenant_id)
            print(json.dumps(report.model_dump(mode="json"), indent=2))
            if args.strict and not report.ready:
                raise SystemExit(1)
        else:
            report = service.release_gate(args.tenant_id, require_production=args.production)
            print(json.dumps(report.model_dump(mode="json"), indent=2))
            if args.strict and not report.passed:
                raise SystemExit(1)
    finally:
        close = getattr(service.repository, "close", None)
        if callable(close):
            close()


if __name__ == "__main__":
    main()
