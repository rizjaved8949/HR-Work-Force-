"""Smoke tests for the application itself.

The service suites all passed while `app.py` could not even be imported, and
while the agent's headcount tool failed on every call. These tests cover the
seams those suites do not reach: module import, route registration, and the
tool wiring the agent actually uses at runtime.

Nothing here calls the LLM.
"""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = REPO_ROOT / "backend"

for path in (REPO_ROOT, BACKEND_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import app as app_module  # noqa: E402


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app_module.app)


def test_health(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


@pytest.mark.parametrize(
    "path",
    [
        "/chat",
        "/chat/stream",
        "/pipeline/attrition",
        "/pipeline/headcount",
        "/pipeline/replacement",
        "/tools/attrition-predict",
        "/tools/employee-search",
    ],
)
def test_route_is_registered(path: str) -> None:
    """Importing a router is not the same as mounting it.

    `/pipeline/headcount` was imported and built but never included, so the
    whole headcount layer 404'd over HTTP.
    """

    registered = set(app_module.app.openapi()["paths"].keys())

    assert path in registered


def test_headcount_endpoint_answers(client: TestClient) -> None:
    response = client.post(
        "/pipeline/headcount",
        json={"question": "What is the current headcount by department?"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "success"


def test_employee_search_and_attrition(client: TestClient) -> None:
    search = client.post(
        "/tools/employee-search",
        json={"employee_id": "EMP004"},
    )

    assert search.status_code == 200
    assert search.json()["status"] == "found"

    pipeline = client.post(
        "/pipeline/attrition",
        json={"employee_id": "EMP004"},
    )

    assert pipeline.status_code == 200
    assert pipeline.json()["attrition"] in {"Yes", "No"}


def test_employee_search_requires_an_identity(client: TestClient) -> None:
    response = client.post("/tools/employee-search", json={})

    assert response.status_code == 400


def test_agent_headcount_tool_receives_its_runtime() -> None:
    """The agent's headcount tool must return a usable ToolMessage id.

    When LangChain fails to inject `ToolRuntime` the tool still returns a
    Command, but with a placeholder `tool_call_id`. LangGraph then rejects
    the update, the model sees only "please fix the error", and it answers
    from imagination instead of from the CSVs. That failure is invisible
    from the outside, so it is asserted directly.
    """

    from headcount.tool import create_stateful_analyze_headcount_tool

    tool = create_stateful_analyze_headcount_tool(
        service=app_module.headcount_service,
    )

    command = tool.invoke(
        {
            "name": "analyze_headcount",
            "args": {"question": "How many vacant positions are there?"},
            "id": "call-smoke-1",
            "type": "tool_call",
        }
    )

    assert command.update["last_tool_status"] == "success"

    # Bare `ToolRuntime` annotation, no `from __future__ import annotations`,
    # and no extra="forbid" on the args schema -- all three are required for
    # the runtime to arrive.
    signature_runtime = (
        tool.func.__annotations__.get("runtime")
        if hasattr(tool, "func")
        else None
    )
    assert signature_runtime is not None
    assert not isinstance(signature_runtime, str), (
        "runtime annotation was stringized; LangChain cannot inject it"
    )


@pytest.mark.parametrize(
    "question",
    [
        "purple monkey dishwasher",
        "asdkjhaskjdh",
        "what is the weather today",
        "tell me a joke",
    ],
)
def test_unrecognized_question_is_not_answered(
    client: TestClient,
    question: str,
) -> None:
    """An unmatched question must not fall through to an org overview.

    The planner defaults to OVERVIEW when it recognizes nothing, so a typo
    used to come back as a confident, fully-populated answer.
    """

    response = client.post("/pipeline/headcount", json={"question": question})

    assert response.status_code == 200
    assert response.json()["status"] == "unsupported"


@pytest.mark.parametrize(
    "question",
    [
        "give me an overview",
        "What is the current headcount by department?",
        "How many vacant positions are there?",
        "Show the people budget for Finance",
        "headcount trend over the last 6 months",
        "What is the definition of headcount variance?",
        "daily availability last week",
        "workforce movement history",
        "list headcount exceptions",
        "top 5 departments by vacancies",
    ],
)
def test_real_questions_still_answer(
    client: TestClient,
    question: str,
) -> None:
    """The guard above must not reject legitimate questions."""

    response = client.post("/pipeline/headcount", json={"question": question})

    assert response.status_code == 200
    assert response.json()["status"] != "unsupported"


def test_replacement_distinguishes_missing_from_ambiguous(
    client: TestClient,
) -> None:
    """A well-formed but unknown ID is a 404, not an empty candidate list."""

    missing = client.post(
        "/pipeline/replacement",
        json={"employee_id": "EMP999"},
    )

    assert missing.status_code == 404
    assert missing.json()["detail"]["resolution_status"] == "not_found"

    malformed = client.post(
        "/pipeline/replacement",
        json={"employee_id": "NOPE999"},
    )

    assert malformed.status_code == 400
    assert (
        malformed.json()["detail"]["resolution_status"] == "invalid_reference"
    )


def test_api_messages_are_english(client: TestClient) -> None:
    """Structured API messages are a contract, not agent chat output."""

    detail = client.post(
        "/pipeline/replacement",
        json={"employee_id": "EMP999"},
    ).json()["detail"]

    assert "nahi" not in detail["message"].lower()


def test_headcount_args_schema_allows_injected_runtime() -> None:
    """extra='forbid' here fails every agent call before the tool body runs."""

    from headcount.tool import AnalyzeHeadcountToolInput

    assert AnalyzeHeadcountToolInput.model_config.get("extra") != "forbid"
