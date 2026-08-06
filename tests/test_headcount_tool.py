"""Tests for the high-level analyze_headcount tool adapter."""

import json
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError


PROJECT_ROOT = Path(
    __file__
).resolve().parents[1]

BACKEND_DIR = PROJECT_ROOT / "backend"

sys.path.insert(
    0,
    str(BACKEND_DIR),
)


import paths
from headcount.repository import HeadcountRepository
from headcount.service import HeadcountService
from headcount.tool import (
    ANALYZE_HEADCOUNT_TOOL_NAME,
    AnalyzeHeadcountToolInput,
    create_analyze_headcount_callable,
    run_analyze_headcount_tool,
)


@pytest.fixture
def service() -> HeadcountService:
    return HeadcountService(
        HeadcountRepository(
            paths.data_dir()
        )
    )


def metric_values(
    result: dict[str, object],
) -> dict[str, object]:
    metrics = result.get(
        "metrics",
        [],
    )

    assert isinstance(metrics, list)

    return {
        str(metric["metric_name"]):
            metric["value"]
        for metric in metrics
        if isinstance(metric, dict)
    }


def test_tool_returns_current_headcount(
    service: HeadcountService,
) -> None:
    result = run_analyze_headcount_tool(
        "What is our current employee headcount?",
        service=service,
    )

    assert result["status"] == "success"

    values = metric_values(result)

    assert values["actual_employee_count"] == 720


def test_tool_supports_mapping_input(
    service: HeadcountService,
) -> None:
    result = run_analyze_headcount_tool(
        {
            "question": (
                "How is the vacancy rate calculated?"
            ),
        },
        service=service,
    )

    assert result["status"] == "success"

    records = result.get(
        "records",
        [],
    )

    assert isinstance(records, list)
    assert len(records) == 1


def test_tool_result_is_json_serializable(
    service: HeadcountService,
) -> None:
    result = run_analyze_headcount_tool(
        "Show current workforce availability.",
        service=service,
    )

    serialized = json.dumps(
        result
    )

    assert isinstance(serialized, str)
    assert '"status": "success"' in serialized


def test_callable_uses_stable_tool_name(
    service: HeadcountService,
) -> None:
    tool_callable = (
        create_analyze_headcount_callable(
            service
        )
    )

    assert (
        tool_callable.__name__
        == ANALYZE_HEADCOUNT_TOOL_NAME
    )

    result = tool_callable(
        "Show current organization headcount."
    )

    assert result["status"] == "success"


def test_tool_rejects_blank_question() -> None:
    with pytest.raises(ValidationError):
        AnalyzeHeadcountToolInput(
            question="  "
        )
