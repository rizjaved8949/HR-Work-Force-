"""Install/verify the active graph backend schema.

For Supabase, DDL must be executed through the Supabase SQL Editor (or psql),
because the normal PostgREST data API intentionally cannot create arbitrary
schema objects. This command verifies that the two graph tables exist and tells
the operator which SQL migration to run when they do not.
"""
from __future__ import annotations

from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env", override=True)

from .factory import create_graph_repository_from_env, graph_backend_name


def main() -> None:
    backend = graph_backend_name()
    repository = create_graph_repository_from_env(verify_connectivity=False)
    try:
        if backend == "neo4j":
            repository.verify_connectivity()
            repository.install_schema()
            print("Neo4j graph schema installed and connectivity verified.")
            return

        sql_path = ROOT / "backend" / "graph" / "sql" / "supabase_graph_schema.sql"
        try:
            repository.verify_connectivity()
        except Exception as exc:
            raise RuntimeError(
                "Supabase graph tables are not ready. Run this SQL file in the Supabase SQL Editor: "
                f"{sql_path}. Original verification error: {type(exc).__name__}: {exc}"
            ) from exc
        print("Supabase graph schema: OK")
        print(f"DDL source: {sql_path}")
    finally:
        close = getattr(repository, "close", None)
        if callable(close):
            close()


if __name__ == "__main__":
    main()
