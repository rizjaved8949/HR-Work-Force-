"""Tenant-namespaced mapping-plan persistence for Step 12."""
from __future__ import annotations

import json
from pathlib import Path

from ingestion.models import MappingPlan

from .registry import validate_safe_id, validate_tenant_id


PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_PLAN_DIR = PACKAGE_DIR / "workspace" / "plans"


class TenantMappingPlanStore:
    def __init__(self, root: str | Path = DEFAULT_PLAN_DIR) -> None:
        self.root = Path(root)

    def _path(self, tenant_id: str, plan_id: str) -> Path:
        tenant = validate_tenant_id(tenant_id)
        plan = validate_safe_id(plan_id, name="plan_id")
        return self.root / tenant / f"{plan}.json"

    def save(self, tenant_id: str, plan: MappingPlan) -> Path:
        if plan.tenant_id != tenant_id:
            raise ValueError("Mapping plan tenant_id does not match organization tenant_id")
        path = self._path(tenant_id, plan.plan_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(plan.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        tmp.replace(path)
        return path

    def load(self, tenant_id: str, plan_id: str) -> MappingPlan:
        path = self._path(tenant_id, plan_id)
        if not path.is_file():
            raise KeyError(plan_id)
        plan = MappingPlan.model_validate_json(path.read_text(encoding="utf-8"))
        if plan.tenant_id != tenant_id:
            raise ValueError("Stored mapping plan tenant mismatch")
        return plan

    def list_plan_ids(self, tenant_id: str) -> list[str]:
        tenant = validate_tenant_id(tenant_id)
        directory = self.root / tenant
        if not directory.is_dir():
            return []
        return sorted(path.stem for path in directory.glob("*.json"))


DEFAULT_TENANT_PLAN_STORE = TenantMappingPlanStore()
