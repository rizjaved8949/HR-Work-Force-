"""High-level Employee Performance tool for HR-agent integration.

The adapter remains deterministic: PerformanceService supplies the facts and the
LLM only selects this tool and explains its structured result.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from functools import lru_cache
from typing import Any, Final

from langchain.messages import ToolMessage
from langchain.tools import ToolRuntime, tool as stateful_tool
from langchain_core.tools import BaseTool, tool
from langgraph.types import Command
from pydantic import BaseModel, ConfigDict, Field

import paths
from performance.repository import PerformanceRepository
from performance.schemas import AnalyzePerformanceInput
from performance.service import PerformanceService


logger = logging.getLogger(__name__)

ANALYZE_EMPLOYEE_PERFORMANCE_TOOL_NAME: Final[str] = "analyze_employee_performance"
ANALYZE_EMPLOYEE_PERFORMANCE_TOOL_DESCRIPTION: Final[str] = (
    "Answer deterministic Employee Performance questions for individuals, "
    "departments, or the organization. Use it for performance scores and bands, "
    "role-specific KPI actual-versus-target results, KPI strengths and gaps, "
    "monthly trends, improving or declining performance, department comparisons "
    "and rankings, best or lowest-performing departments, performance distribution, "
    "employees requiring attention, learning history, skill-development areas, "
    "and evidence-based course or training recommendations. The tool calculates "
    "or retrieves exact values; the LLM must only explain them."
)


class AnalyzeEmployeePerformanceToolInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    question: str = Field(
        min_length=3,
        description=(
            "The user's complete Employee Performance question. Preserve employee "
            "IDs, dates, department or organization scope, ranking/comparison intent, "
            "trend wording, KPI intent, and course/training or learning-history intent."
        ),
    )
    employee_id: str | None = Field(
        default=None,
        description=(
            "Confirmed employee ID when the user supplied one or the conversation "
            "already resolved the employee."
        ),
    )
    employee_name: str | None = Field(
        default=None,
        description=(
            "Employee name when the user asks about a named employee and no confirmed "
            "employee ID is available."
        ),
    )
    department: str | None = Field(
        default=None,
        description=(
            "Department scope when the user's Performance question is explicitly "
            "limited to a department."
        ),
    )


@lru_cache(maxsize=1)
def get_default_performance_service() -> PerformanceService:
    repository = PerformanceRepository(paths.data_dir())
    return PerformanceService(repository)


def run_analyze_employee_performance_tool(
    payload: AnalyzeEmployeePerformanceToolInput | Mapping[str, Any] | str,
    *,
    service: PerformanceService | None = None,
) -> dict[str, Any]:
    if isinstance(payload, AnalyzeEmployeePerformanceToolInput):
        validated = payload
    elif isinstance(payload, str):
        validated = AnalyzeEmployeePerformanceToolInput(question=payload)
    elif isinstance(payload, Mapping):
        validated = AnalyzeEmployeePerformanceToolInput.model_validate(dict(payload))
    else:
        raise TypeError("Performance tool requires a question string or mapping.")

    active_service = service or get_default_performance_service()
    result = active_service.analyze(
        AnalyzePerformanceInput(
            question=validated.question,
            employee_id=validated.employee_id,
            employee_name=validated.employee_name,
            department=validated.department,
        )
    )
    return result.model_dump(mode="json", exclude_none=True)


def create_analyze_employee_performance_tool(
    service: PerformanceService | None = None,
) -> BaseTool:
    active_service = service or get_default_performance_service()

    @tool(
        ANALYZE_EMPLOYEE_PERFORMANCE_TOOL_NAME,
        args_schema=AnalyzeEmployeePerformanceToolInput,
    )
    def performance_tool(
        question: str,
        employee_id: str | None = None,
        employee_name: str | None = None,
        department: str | None = None,
    ) -> dict[str, Any]:
        """
        Analyze deterministic Employee Performance evidence for an employee,
        department, or the organization, including scores, bands, KPIs, trends,
        rankings, attention lists, learning history, skill gaps, and course
        recommendations.
        """
        return run_analyze_employee_performance_tool(
            {
                "question": question,
                "employee_id": employee_id,
                "employee_name": employee_name,
                "department": department,
            },
            service=active_service,
        )

    return performance_tool


def create_stateful_analyze_employee_performance_tool(
    service: PerformanceService | None = None,
) -> BaseTool:
    base_tool = create_analyze_employee_performance_tool(service=service)

    @stateful_tool(
        ANALYZE_EMPLOYEE_PERFORMANCE_TOOL_NAME,
        args_schema=AnalyzeEmployeePerformanceToolInput,
    )
    def performance_tool(
        question: str,
        employee_id: str | None = None,
        employee_name: str | None = None,
        department: str | None = None,
        runtime: ToolRuntime = None,  # pyright: ignore[reportArgumentType]
    ) -> Command:
        """
        Analyze deterministic Employee Performance evidence for individual,
        department, organization, KPI, trend, ranking, learning-history, skill-gap,
        and course-recommendation questions, while preserving other HR-tool context.
        """
        try:
            result = base_tool.invoke({
                "question": question,
                "employee_id": employee_id,
                "employee_name": employee_name,
                "department": department,
            })
        except Exception:
            logger.exception("Performance tool failed for question: %r", question)
            raise

        state_update: dict[str, Any] = {
            "last_user_intent": "performance",
            "last_performance_question": question,
            "last_performance_result": result,
            "last_tool_status": result.get("status"),
        }

        employee = result.get("employee")
        if isinstance(employee, Mapping):
            resolved_id = employee.get("Employee_ID")
            resolved_name = employee.get("Employee_Name")
            resolved_department = employee.get("Department")
            resolved_designation = employee.get("Designation")
            if resolved_id:
                state_update["selected_employee_id"] = str(resolved_id)
            if resolved_name:
                state_update["selected_employee_name"] = str(resolved_name)
            if resolved_department:
                state_update["selected_department"] = str(resolved_department)
            if resolved_designation:
                state_update["selected_designation"] = str(resolved_designation)

        tool_call_id = getattr(runtime, "tool_call_id", None) or "performance-tool-call"
        content = json.dumps(result, ensure_ascii=False, default=str)
        state_update["messages"] = [
            ToolMessage(
                content=content,
                tool_call_id=tool_call_id,
            )
        ]
        return Command(update=state_update)

    return performance_tool
