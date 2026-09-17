"""Command-line utility for Step-6 profiling, mapping review and dry-runs."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .models import MappingPlan
from .service import DataIngestionService
from .sources import CSVSource, JSONArraySource, XLSXSource


def _source(path: str, *, system: str, object_name: str | None, sheet: str | None = None):
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix == ".csv":
        return CSVSource(p, source_system=system, source_object=object_name)
    if suffix == ".json":
        return JSONArraySource(p, source_system=system, source_object=object_name)
    if suffix in {".xlsx", ".xlsm"}:
        return XLSXSource(p, sheet_name=sheet, source_system=system, source_object=object_name)
    raise ValueError(f"Unsupported source file extension: {suffix}")


def _load_plan(path: str) -> MappingPlan:
    return MappingPlan.model_validate_json(Path(path).read_text(encoding="utf-8"))


def _print(payload) -> None:
    print(json.dumps(payload, indent=2, default=str))


def main() -> None:
    parser = argparse.ArgumentParser(description="HR roadmap Step-6 ingestion utility")
    sub = parser.add_subparsers(dest="command", required=True)

    for name in ("profile", "suggest"):
        p = sub.add_parser(name)
        p.add_argument("file")
        p.add_argument("--source-system", default="file_upload")
        p.add_argument("--source-object")
        p.add_argument("--sheet")

    validate = sub.add_parser("validate-plan")
    validate.add_argument("plan")
    validate.add_argument("--file")
    validate.add_argument("--sheet")

    approve = sub.add_parser("approve-plan")
    approve.add_argument("plan")
    approve.add_argument("--approved-by", required=True)
    approve.add_argument("--output", required=True)

    dry = sub.add_parser("dry-run")
    dry.add_argument("plan")
    dry.add_argument("file")
    dry.add_argument("--sheet")

    args = parser.parse_args()
    service = DataIngestionService()

    if args.command in {"profile", "suggest"}:
        src = _source(
            args.file,
            system=args.source_system,
            object_name=args.source_object,
            sheet=args.sheet,
        )
        if args.command == "profile":
            _print(service.profile(src).model_dump(mode="json"))
        else:
            _print(service.suggest_mappings(src))
        return

    plan = _load_plan(args.plan)
    if args.command == "validate-plan":
        src = None
        if args.file:
            src = _source(
                args.file,
                system=plan.source_system,
                object_name=plan.source_object,
                sheet=args.sheet,
            )
        _print(service.validate_plan(plan, src))
    elif args.command == "approve-plan":
        approved = service.approve_plan(plan, approved_by=args.approved_by)
        Path(args.output).write_text(
            json.dumps(approved.model_dump(mode="json"), indent=2),
            encoding="utf-8",
        )
        _print({"approved": True, "output": args.output, "plan_id": approved.plan_id})
    elif args.command == "dry-run":
        src = _source(
            args.file,
            system=plan.source_system,
            object_name=plan.source_object,
            sheet=args.sheet,
        )
        _print(service.dry_run(src, plan))


if __name__ == "__main__":
    main()
