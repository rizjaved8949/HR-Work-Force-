"""Small Linux-friendly CLI for Step 12 onboarding operations."""
from __future__ import annotations

import argparse
import json

from dotenv import load_dotenv

from .access import DEFAULT_ORGANIZATION_ACCESS
from .models import ActorContext, CreateOrganizationRequest
from .service import MultiOrganizationOnboardingService


def _local_actor() -> ActorContext:
    return ActorContext(
        authenticated=False,
        user_id="step12-cli",
        role="local_dev",
        local_development=True,
    )


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Step 12 multi-organization onboarding")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list")
    create = sub.add_parser("create")
    create.add_argument("--tenant-id", required=True)
    create.add_argument("--name", required=True)
    create.add_argument("--country")
    create.add_argument("--currency")

    import_file = sub.add_parser("register-file")
    import_file.add_argument("--tenant-id", required=True)
    import_file.add_argument("--path", required=True)
    import_file.add_argument("--source-system")
    import_file.add_argument("--source-object")
    import_file.add_argument("--sheet-name")

    profile = sub.add_parser("profile")
    profile.add_argument("--tenant-id", required=True)
    profile.add_argument("--dataset-id", required=True)

    readiness = sub.add_parser("readiness")
    readiness.add_argument("--tenant-id", required=True)

    args = parser.parse_args()
    service = MultiOrganizationOnboardingService.from_env()
    actor = _local_actor()
    try:
        if args.command == "list":
            payload = [item.model_dump(mode="json") for item in service.list_organizations(actor=actor)]
        elif args.command == "create":
            payload = service.create_organization(
                CreateOrganizationRequest(
                    tenant_id=args.tenant_id,
                    name=args.name,
                    country=args.country,
                    currency=args.currency,
                ),
                actor=actor,
            ).model_dump(mode="json")
        elif args.command == "register-file":
            payload = service.register_file_dataset(
                args.tenant_id,
                args.path,
                actor=actor,
                source_system=args.source_system,
                source_object=args.source_object,
                sheet_name=args.sheet_name,
            ).model_dump(mode="json")
        elif args.command == "profile":
            payload = service.profile_dataset(args.tenant_id, args.dataset_id, actor=actor)
        else:
            payload = service.readiness(args.tenant_id, actor=actor).model_dump(mode="json")
        print(json.dumps(payload, indent=2, default=str))
    finally:
        service.close()


if __name__ == "__main__":
    main()
