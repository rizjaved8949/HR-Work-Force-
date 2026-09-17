"""Verify the active graph backend and tenant counts."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env", override=True)

from .factory import create_graph_repository_from_env, graph_backend_name


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify active HR graph backend")
    parser.add_argument("--tenant-id", default="ORGANIZATION-001")
    args = parser.parse_args()

    repository = create_graph_repository_from_env(verify_connectivity=True)
    try:
        payload = {
            "graph_backend": graph_backend_name(),
            "repository": type(repository).__name__,
            "tenant_id": args.tenant_id,
            "node_count": repository.count_nodes(args.tenant_id),
            "relationship_count": repository.count_relationships(args.tenant_id),
        }
        print(json.dumps(payload, indent=2))
    finally:
        close = getattr(repository, "close", None)
        if callable(close):
            close()


if __name__ == "__main__":
    main()
