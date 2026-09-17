"""Small Step 9 validation CLI that does not start FastAPI."""
from __future__ import annotations

import argparse
import json

from feature_resolution.service import FeatureResolutionService
from semantic.service import SemanticHRService


def main() -> None:
    parser = argparse.ArgumentParser(description="Step 9 graph runtime checks")
    parser.add_argument("command", choices=["health", "employee", "attrition-features"])
    parser.add_argument("--tenant-id", default="ORGANIZATION-001")
    parser.add_argument("--employee-id")
    args = parser.parse_args()

    semantic = SemanticHRService.from_env(verify_connectivity=True)
    features = FeatureResolutionService(semantic)
    try:
        if args.command == "health":
            payload = {
                "step": 9,
                "semantic": semantic.health(args.tenant_id),
                "feature_resolution": features.health(args.tenant_id),
            }
        elif args.command == "employee":
            if not args.employee_id:
                parser.error("--employee-id is required for employee")
            context = semantic.get_employee_context(
                tenant_id=args.tenant_id, employee_id=args.employee_id
            )
            payload = context.model_dump(mode="json") if context else None
        else:
            if not args.employee_id:
                parser.error("--employee-id is required for attrition-features")
            payload = features.resolve_attrition(
                tenant_id=args.tenant_id, employee_id=args.employee_id
            ).model_dump(mode="json")
        print(json.dumps(payload, indent=2, default=str))
    finally:
        features.close()


if __name__ == "__main__":
    main()
