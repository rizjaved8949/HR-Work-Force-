"""Non-destructive Step-5 live Neo4j verification command."""

from __future__ import annotations

import json

from .service import SemanticHRService


def main() -> None:
    service = SemanticHRService.from_env(verify_connectivity=True)
    try:
        print("NEO4J SEMANTIC CONNECTION OK")
        print(json.dumps(service.health(), indent=2, default=str))
    finally:
        service.close()


if __name__ == "__main__":
    main()
