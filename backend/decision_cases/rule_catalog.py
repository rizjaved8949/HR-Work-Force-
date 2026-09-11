from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd


RULES_FILE = "HR_Decision_Trigger_Rules.csv"


@dataclass(frozen=True)
class DecisionTriggerRule:
    rule_id: str
    rule_name: str
    enabled: bool
    priority: str
    subject_type: str
    display_rank: int
    trigger_condition: str
    source_files: str
    aggregation_mode: str
    suggested_action: str
    source_rule_id: str | None = None


class DecisionTriggerRuleCatalog:
    """Loads the five approved Decision Trigger rules from CSV configuration.

    The case rows themselves are never stored here. This file only controls
    whether a rule is enabled and supplies display metadata. The deterministic
    rule implementations still read live HR data on every evaluation.
    """

    REQUIRED_COLUMNS = {
        "Rule_ID",
        "Rule_Name",
        "Enabled",
        "Priority",
        "Subject_Type",
        "Display_Rank",
        "Trigger_Condition",
        "Source_Files",
        "Aggregation_Mode",
        "Suggested_Action",
    }

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        if not self.path.is_file():
            raise FileNotFoundError(
                f"Decision Trigger rule catalog was not found: {self.path}"
            )
        self._rules = self._load()

    def _load(self) -> dict[str, DecisionTriggerRule]:
        frame = pd.read_csv(self.path).fillna("")
        missing = self.REQUIRED_COLUMNS - set(frame.columns)
        if missing:
            raise ValueError(
                "Decision Trigger rule catalog is missing columns: "
                + ", ".join(sorted(missing))
            )

        rules: dict[str, DecisionTriggerRule] = {}
        for row in frame.to_dict("records"):
            rule_id = str(row["Rule_ID"]).strip().upper()
            if not rule_id:
                continue
            if rule_id in rules:
                raise ValueError(f"Duplicate Decision Trigger rule id: {rule_id}")

            priority = str(row["Priority"]).strip().title()
            if priority not in {"Critical", "High"}:
                raise ValueError(
                    f"{rule_id} priority must be Critical or High for the focused MVP queue."
                )

            enabled = str(row["Enabled"]).strip().casefold() in {
                "1", "true", "yes", "on"
            }
            source_rule_id = str(row.get("Source_Rule_ID", "")).strip() or None

            rules[rule_id] = DecisionTriggerRule(
                rule_id=rule_id,
                rule_name=str(row["Rule_Name"]).strip(),
                enabled=enabled,
                priority=priority,
                subject_type=str(row["Subject_Type"]).strip(),
                display_rank=int(row["Display_Rank"]),
                trigger_condition=str(row["Trigger_Condition"]).strip(),
                source_files=str(row["Source_Files"]).strip(),
                aggregation_mode=str(row["Aggregation_Mode"]).strip(),
                suggested_action=str(row["Suggested_Action"]).strip(),
                source_rule_id=source_rule_id,
            )

        return rules

    def get(self, rule_id: str) -> DecisionTriggerRule:
        normalized = rule_id.strip().upper()
        try:
            return self._rules[normalized]
        except KeyError as exc:
            raise KeyError(
                f"Decision Trigger rule {normalized} is not defined in {self.path.name}."
            ) from exc

    def enabled(self, rule_id: str) -> bool:
        return self.get(rule_id).enabled

    def all(self) -> list[DecisionTriggerRule]:
        return sorted(self._rules.values(), key=lambda item: item.display_rank)
