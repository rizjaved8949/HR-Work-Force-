"""Linux/Windows CLI for Step-8 verification against a populated graph."""
from __future__ import annotations

import argparse
import json
from datetime import date
from typing import Any

from .adapters import FeatureResolutionBlockedError
from .registry import DEFAULT_FEATURE_CONTRACTS
from .service import FeatureResolutionService


def _date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def _print(payload: Any) -> None:
    if hasattr(payload, "model_dump"):
        payload = payload.model_dump(mode="json")
    print(json.dumps(payload, indent=2, default=str))


def main() -> None:
    parser = argparse.ArgumentParser(description="Step 8 feature-resolution utilities")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("contracts", help="Show audited feature contracts exposed by Step 8")

    health = sub.add_parser("health", help="Verify Semantic/Graph connectivity through Step 8")
    health.add_argument("--tenant-id")

    attrition = sub.add_parser("attrition", help="Resolve the 14 current attrition features")
    attrition.add_argument("--tenant-id", required=True)
    attrition.add_argument("--employee-id", required=True)
    attrition.add_argument("--as-of-date")
    attrition.add_argument("--strict-missing", action="store_true")

    model = sub.add_parser(
        "attrition-model-input",
        help="Resolve and adapt to the exact current CatBoost 14-feature contract",
    )
    model.add_argument("--tenant-id", required=True)
    model.add_argument("--employee-id", required=True)
    model.add_argument("--as-of-date")
    model.add_argument("--strict-missing", action="store_true")

    args = parser.parse_args()

    if args.command == "contracts":
        _print(
            {
                "step": 8,
                "contracts": [
                    DEFAULT_FEATURE_CONTRACTS.get(name).model_dump(mode="json")
                    for name in DEFAULT_FEATURE_CONTRACTS.list_contracts()
                ],
            }
        )
        return

    service = FeatureResolutionService.from_env()
    try:
        if args.command == "health":
            _print(service.health(args.tenant_id))
            return
        if args.command == "attrition":
            _print(
                service.resolve_attrition(
                    tenant_id=args.tenant_id,
                    employee_id=args.employee_id,
                    as_of_date=_date(args.as_of_date),
                    strict_missing=args.strict_missing,
                )
            )
            return
        if args.command == "attrition-model-input":
            try:
                _print(
                    service.attrition_model_input(
                        tenant_id=args.tenant_id,
                        employee_id=args.employee_id,
                        as_of_date=_date(args.as_of_date),
                        strict_missing=args.strict_missing,
                    )
                )
            except FeatureResolutionBlockedError as error:
                raise SystemExit(str(error)) from error
            return
    finally:
        service.close()


if __name__ == "__main__":
    main()
