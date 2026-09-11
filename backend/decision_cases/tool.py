from __future__ import annotations

import re
from typing import Optional

from langchain_core.tools import BaseTool, tool
from pydantic import BaseModel, Field

from .exceptions import DecisionCaseStorageError
from .service import DecisionCaseService


_EMPLOYEE_RE = re.compile(r"\bEMP[-_ ]?0*(\d+)\b", re.IGNORECASE)


class QueryDecisionCasesInput(BaseModel):
    question: str = Field(..., min_length=1)
    employee_id: Optional[str] = None
    department: Optional[str] = None
    priority: Optional[str] = None
    status: Optional[str] = None
    limit: int = Field(default=5, ge=1, le=5)


def create_query_decision_cases_tool(service: DecisionCaseService) -> BaseTool:
    @tool("query_decision_cases", args_schema=QueryDecisionCasesInput)
    def query_decision_cases(
        question: str,
        employee_id: Optional[str] = None,
        department: Optional[str] = None,
        priority: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 5,
    ) -> dict:
        """Refresh and read deterministic HR Decision Trigger cases.

        The five rules are re-evaluated from the configured data source before
        querying, so the LLM does not depend on hardcoded or stale case rows.
        Evaluation may refresh the dedicated case-state store, but it never changes
        an employee/workforce source record or makes an HR decision.
        """
        lower = question.casefold()
        if "overdue" in lower:
            return {
                "status": "unsupported",
                "message": (
                    "No case SLA or due-date rule is currently defined, so the system "
                    "cannot label a case overdue without inventing a threshold."
                ),
                "cases": [],
                "count": 0,
                "total_matching": 0,
            }

        if not employee_id:
            match = _EMPLOYEE_RE.search(question)
            if match:
                employee_id = f"EMP{int(match.group(1)):03d}"

        if not priority:
            for value in ("Critical", "High", "Medium", "Low"):
                if value.casefold() in lower:
                    priority = value
                    break

        if not status:
            for value in ("Under Review", "In Progress", "Resolved", "Closed", "Open"):
                if value.casefold() in lower:
                    status = value
                    break

        try:
            # Keep HR-agent answers synchronized with the same source data that
            # powers the dashboard. Existing HR workflow status is preserved.
            service.evaluate()
            result = service.list_cases(
                priority=priority,
                status=status,
                employee_id=employee_id,
                department=department,
                active_only=status not in {"Resolved", "Closed"},
                limit=limit,
            )
        except DecisionCaseStorageError as exc:
            return {
                "status": "error",
                "message": str(exc),
                "cases": [],
                "count": 0,
                "total_matching": 0,
            }

        return result.model_dump(mode="json")

    return query_decision_cases
