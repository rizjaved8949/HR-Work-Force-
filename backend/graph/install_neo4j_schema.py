"""Verify Neo4j connectivity and install Step-4 graph constraints/indexes.

This script creates only graph schema metadata. It does NOT ingest HR records.
"""

from __future__ import annotations

from dotenv import load_dotenv

from .neo4j_repository import Neo4jGraphRepository


def main() -> None:
    load_dotenv()
    repository = Neo4jGraphRepository.from_env()
    try:
        repository.verify_connectivity()
        repository.install_schema()
        print("Neo4j connectivity: OK")
        print("Step-4 graph constraints/indexes: installed")
        print(f"Current node count: {repository.count_nodes()}")
        print(f"Current relationship count: {repository.count_relationships()}")
    finally:
        repository.close()


if __name__ == "__main__":
    main()
