from __future__ import annotations

import argparse
import json
from pathlib import Path

from dotenv import load_dotenv

from .bootstrap import bootstrap_directory
from .config import KGRuntimeConfig
from .materializer import GraphRuntimeMaterializer
from .status import runtime_status
from .store import SupabaseRuntimeGraphStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Knowledge-Graph-only runtime compatibility tools")
    sub = parser.add_subparsers(dest="command", required=True)

    bootstrap = sub.add_parser("bootstrap", help="Mirror repository CSV sources into the reserved KG runtime subgraph")
    bootstrap.add_argument("--tenant-id", default=None)
    bootstrap.add_argument("--source-dir", default=None)

    materialize = sub.add_parser("materialize", help="Rebuild the disposable runtime Data directory from KG")
    materialize.add_argument("--tenant-id", default=None)
    materialize.add_argument("--force", action="store_true")

    status = sub.add_parser("status", help="Show KG runtime source status")
    status.add_argument("--tenant-id", default=None)
    return parser


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    load_dotenv(root / ".env", override=False)
    args = build_parser().parse_args()
    cfg = KGRuntimeConfig.from_env()
    tenant = str(args.tenant_id or cfg.tenant_id)
    store = SupabaseRuntimeGraphStore.from_env(cfg)

    if args.command == "bootstrap":
        source = Path(args.source_dir or cfg.source_dir)
        result = bootstrap_directory(source_dir=source, tenant_id=tenant, store=store)
    elif args.command == "materialize":
        materializer = GraphRuntimeMaterializer(config=cfg, store=store)
        path = materializer.materialize(tenant_id=tenant, force=bool(args.force))
        result = {"status": "materialized", "tenant_id": tenant, "path": str(path)}
    else:
        # runtime_status currently reports configured tenant; include requested tenant mirror summary too.
        materializer = GraphRuntimeMaterializer(config=cfg, store=store)
        result = runtime_status(cfg)
        result["requested_tenant"] = tenant
        result["requested_tenant_mirror"] = materializer.status(tenant_id=tenant)

    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
