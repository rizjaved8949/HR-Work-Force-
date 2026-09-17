"""Filesystem registry for reviewed Step-6 mapping plans."""
from __future__ import annotations

import json
from pathlib import Path

from .models import MappingPlan


PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_PLAN_DIR = PACKAGE_DIR / "plans"


class MappingPlanRegistry:
    def __init__(self, plan_dir: str | Path = DEFAULT_PLAN_DIR) -> None:
        self.plan_dir = Path(plan_dir)

    def save(self, plan: MappingPlan) -> Path:
        self.plan_dir.mkdir(parents=True, exist_ok=True)
        path = self.plan_dir / f"{plan.plan_id}.json"
        path.write_text(
            json.dumps(plan.model_dump(mode="json"), indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return path

    def load(self, plan_id: str) -> MappingPlan:
        path = self.plan_dir / f"{plan_id}.json"
        if not path.is_file():
            raise KeyError(f"Unknown mapping plan: {plan_id!r}")
        return MappingPlan.model_validate_json(path.read_text(encoding="utf-8"))

    def list_plan_ids(self) -> list[str]:
        if not self.plan_dir.is_dir():
            return []
        return sorted(path.stem for path in self.plan_dir.glob("*.json"))


DEFAULT_PLAN_REGISTRY = MappingPlanRegistry()
