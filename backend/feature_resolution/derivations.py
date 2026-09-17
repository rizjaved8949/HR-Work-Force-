"""Approved derivations for Step 8.

Only ontology-backed, explicitly registered derivations are allowed. The resolver
must never invent a formula for a missing feature just because inputs look related.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from semantic.models import EmployeeContext

from .providers import SemanticValueProvider


PACKAGE_DIR = Path(__file__).resolve().parent
DEFAULT_RULES_FILE = PACKAGE_DIR / "rules" / "feature_resolution_rules_v1.json"


@dataclass(frozen=True)
class DerivationResult:
    resolved: bool
    value: Any = None
    rule_id: str | None = None
    source_reference_ids: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


def _as_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return date.fromisoformat(text)
        except ValueError:
            return None


def _completed_months(start: date, end: date) -> int:
    if end < start:
        raise ValueError("reference/as-of date cannot be earlier than hire date")
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day < start.day:
        months -= 1
    return max(months, 0)


class FeatureDerivationRegistry:
    def __init__(self, rules_file: str | Path = DEFAULT_RULES_FILE) -> None:
        self.rules_file = Path(rules_file).resolve()
        self._payload = json.loads(self.rules_file.read_text(encoding="utf-8"))
        self._rules = {
            item["ontology_path"]: item
            for item in self._payload.get("derivations", [])
            if item.get("status") == "approved"
        }
        self._safe_defaults = {
            item["ontology_path"]: item
            for item in self._payload.get("safe_defaults", [])
            if item.get("status") == "approved"
        }

    @property
    def version(self) -> str:
        return str(self._payload.get("version", "unknown"))

    def has_derivation(self, ontology_path: str) -> bool:
        return ontology_path in self._rules

    def safe_default(self, ontology_path: str) -> tuple[bool, Any, str | None]:
        rule = self._safe_defaults.get(ontology_path)
        if rule is None:
            return False, None, None
        return True, rule.get("value"), str(rule.get("rule_id"))

    def derive(
        self,
        ontology_path: str,
        *,
        provider: SemanticValueProvider,
        employee_context: EmployeeContext | None = None,
        as_of_date: date | None = None,
    ) -> DerivationResult:
        rule = self._rules.get(ontology_path)
        if rule is None:
            return DerivationResult(resolved=False)

        rule_id = str(rule.get("rule_id"))

        if rule_id == "derive_tenure_months_from_hire_date":
            hire = provider.get("Employment.hireDate")
            if not hire.present:
                return DerivationResult(
                    resolved=False,
                    rule_id=rule_id,
                    notes=("Employment.hireDate is unavailable.",),
                )
            hire_date = _as_date(hire.value)
            if hire_date is None:
                return DerivationResult(
                    resolved=False,
                    rule_id=rule_id,
                    source_reference_ids=hire.source_reference_ids,
                    notes=("Employment.hireDate could not be parsed as a date.",),
                )

            data_as_of = provider.get("Employment.dataAsOfDate")
            ref_date = _as_date(data_as_of.value) if data_as_of.present else None
            ref_source_ids = data_as_of.source_reference_ids if data_as_of.present else ()
            if ref_date is None:
                ref_date = as_of_date
            if ref_date is None:
                return DerivationResult(
                    resolved=False,
                    rule_id=rule_id,
                    source_reference_ids=hire.source_reference_ids,
                    notes=(
                        "No Employment.dataAsOfDate or explicit request as_of_date is available; "
                        "tenure was not derived from wall-clock time implicitly.",
                    ),
                )
            try:
                value = _completed_months(hire_date, ref_date)
            except ValueError as error:
                return DerivationResult(
                    resolved=False,
                    rule_id=rule_id,
                    source_reference_ids=tuple(dict.fromkeys((*hire.source_reference_ids, *ref_source_ids))),
                    notes=(str(error),),
                )
            return DerivationResult(
                resolved=True,
                value=value,
                rule_id=rule_id,
                source_reference_ids=tuple(dict.fromkeys((*hire.source_reference_ids, *ref_source_ids))),
                notes=(f"Derived from hire date {hire_date.isoformat()} and reference date {ref_date.isoformat()}.",),
            )

        return DerivationResult(
            resolved=False,
            rule_id=rule_id,
            notes=(f"Derivation rule {rule_id!r} has no implementation.",),
        )


DEFAULT_DERIVATIONS = FeatureDerivationRegistry()
