"""HR Workforce Intelligence Backend — single application entry point.

Run it with either:

    python app.py
    uvicorn app:app --reload

All configuration comes from the single .env file next to this script.

The application exposes:

- the employee-search tool
- the CatBoost attrition-prediction tool
- the combined attrition pipeline
- the local successor / replacement LangGraph
- the multilingual HR reasoning agent (chat)
"""
import json
import os
import re
import sys
from pathlib import Path
from time import perf_counter
from typing import Any, Optional
from uuid import uuid4

from dotenv import load_dotenv

# ============================================================
# PATH AND ENVIRONMENT SETUP
# ============================================================
# The backend package lives one level down. It is added to sys.path so its
# modules can be imported without installing the project as a package.

REPO_ROOT = Path(__file__).resolve().parent
BACKEND_DIR = REPO_ROOT / "backend"

if not BACKEND_DIR.is_dir():
    raise RuntimeError(
        f"Backend folder was not found: {BACKEND_DIR}"
    )

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# The single project .env, loaded before any backend module reads it.
# `settings.py` loads the same file at import time, so this must run first
# for the values here to be the ones that win.
load_dotenv(REPO_ROOT / ".env")


# ============================================================
# BACKEND IMPORTS — MUST COME AFTER sys.path AND .env SETUP
# ============================================================

from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import StreamingResponse  # noqa: E402
from pydantic import BaseModel, Field, SecretStr  # noqa: E402

import paths  # noqa: E402
from attrition_prediction_tool import (  # noqa: E402
    create_attrition_prediction_tool,
)
from employee_record_tool import (  # noqa: E402
    create_employee_record_tool,
)
from headcount.repository import HeadcountRepository  # noqa: E402
from headcount.router import create_headcount_router  # noqa: E402
from headcount.service import HeadcountService  # noqa: E402
from performance.repository import PerformanceRepository  # noqa: E402
from performance.router import create_performance_router  # noqa: E402
from performance.service import PerformanceService  # noqa: E402
from hr_agent import create_hr_reasoning_agent  # noqa: E402
from resilient_model import ResilientChatOpenAI  # noqa: E402
from replacement_tool import (  # noqa: E402
    create_replacement_recommendation_tool,
)
from settings import get_llm_settings  # noqa: E402
from auth import (  # noqa: E402
    auth_router,
    install_authentication,
)
from visualizations.attrition.router import (  # noqa: E402
    create_attrition_dashboard_router,
)

from simulations.lookup_service import SimulationLookupService  # noqa: E402
from simulations.repository import SimulationRepository  # noqa: E402
from simulations.router import create_simulation_router  # noqa: E402
from simulations.service import SimulationDataService, SimulationService  # noqa: E402
from simulations.tool import run_scenario_simulation_tool  # noqa: E402


DATA_PATH = paths.data_dir()
MODEL_PATH = paths.model_path()

# Reading this at startup means a missing OPENROUTER_MODEL or
# OPENROUTER_API_KEY fails immediately with a clear message, rather than on
# the first chat request.
LLM = get_llm_settings()

# How many times /chat will run the agent for one user message before giving
# up. The extra attempt only covers a reply that came back empty.
CHAT_ATTEMPTS = 2


def _verify_startup_paths() -> None:
    """Fail immediately with a clear message when data or model is missing."""

    if not DATA_PATH.is_dir():
        raise RuntimeError(
            f"Data folder was not found: {DATA_PATH}. "
            "Set DATA_DIR in .env."
        )

    if not MODEL_PATH.is_file():
        raise RuntimeError(
            f"CatBoost model was not found: {MODEL_PATH}. "
            "Set MODEL_PATH in .env."
        )


_verify_startup_paths()


# ============================================================
# LOAD EVERY TOOL ONCE
# ============================================================
# The CSV data, the CatBoost model, and the successor graph are each
# loaded a single time and shared by every endpoint.

employee_search_tool = create_employee_record_tool(DATA_PATH)

attrition_prediction_tool = create_attrition_prediction_tool(MODEL_PATH)

replacement_recommendation_tool = create_replacement_recommendation_tool(
    data_dir=DATA_PATH,
)
headcount_service = HeadcountService(
    HeadcountRepository(
        DATA_PATH
    )
)
performance_service = PerformanceService(
    PerformanceRepository(
        DATA_PATH
    )
)
# ============================================================
# SCENARIO SIMULATION — SHARED SERVICES
# ============================================================
# Isolated from the existing attrition, replacement and HR-agent pipelines.
simulation_repository = SimulationRepository(DATA_PATH)
simulation_data_service = SimulationDataService(simulation_repository)
simulation_service = SimulationService(simulation_repository)
simulation_lookup_service = SimulationLookupService(simulation_repository)


hr_agent = create_hr_reasoning_agent(
    employee_search_tool=employee_search_tool,
    attrition_prediction_tool=attrition_prediction_tool,
    data_path=DATA_PATH,
    headcount_service=headcount_service,
    performance_service=performance_service,
    simulation_service=simulation_service,
)

# A plain chat model is used only to turn an already-computed deterministic
# simulation result into a natural chatbot reply. No tools are bound to this
# model, so it cannot rerun or alter any HR/simulation calculation.
simulation_reply_model = ResilientChatOpenAI(
    model=LLM.model,
    api_key=SecretStr(LLM.api_key),
    base_url=LLM.base_url,
    temperature=LLM.temperature,
    max_completion_tokens=LLM.max_tokens,
    max_retries=LLM.max_retries,
    timeout=LLM.timeout_seconds,
    transient_max_attempts=LLM.max_retries + 1,
    extra_body=LLM.extra_body(),
    default_headers={
        "HTTP-Referer": "http://localhost:8000",
        "X-Title": "HR Workforce Intelligence Backend",
    },
)


# ============================================================
# FASTAPI APP
# ============================================================

app = FastAPI(
    title="HR Workforce Intelligence API",
    description=(
        "Employee search, CatBoost attrition prediction, internal "
        "successor recommendations, and the multilingual HR agent."
    ),
    version="3.0.0",
)


install_authentication(app)
app.include_router(auth_router)


# ============================================================
# CROSS-ORIGIN ACCESS
# ============================================================
# A browser refuses to read this API from a page served on another origin
# unless the response carries CORS headers. The frontend runs on its own
# origin (localhost during development, a static site in production), so
# without this every fetch fails before the handler is ever reached.
#
# ALLOWED_ORIGINS is a comma-separated list in .env. "*" allows any origin,
# which is the sensible default only while there are no cookies or
# credentials in play. Set it to the real frontend URLs before launch.

_allowed_origins = [
    origin.strip()
    for origin in os.getenv("ALLOWED_ORIGINS", "*").split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,

    # Supabase authentication uses the Authorization: Bearer header,
    # not browser cookies, so credentials remain disabled.
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


# ============================================================
# ATTRITION DASHBOARD PIPELINE
# ============================================================
# The dashboard reuses the same CSV folder and replacement graph already
# loaded by this application. It does not call the HR-agent LLM.

app.include_router(
    create_attrition_dashboard_router(
        data_dir=DATA_PATH,
        model_path=MODEL_PATH,
        replacement_tool=replacement_recommendation_tool,
    )
)


# ============================================================
# DETERMINISTIC HEADCOUNT ANALYTICS
# ============================================================
# POST /pipeline/headcount, backed by the same HeadcountService the agent's
# analyze_headcount tool uses, so HTTP and chat answers cannot diverge.

app.include_router(
    create_headcount_router(headcount_service)
)


# ============================================================
# EMPLOYEE PERFORMANCE ANALYTICS
# ============================================================
# Employee performance APIs reuse the same shared Data folder and the
# isolated deterministic PerformanceService.

app.include_router(
    create_performance_router(performance_service)
)


# ============================================================
# SCENARIO SIMULATION API
# ============================================================
# Dedicated REST endpoints for the Scenario Simulator UI.
app.include_router(
    create_simulation_router(
        simulation_service=simulation_service,
        data_service=simulation_data_service,
        lookup_service=simulation_lookup_service,
    )
)


# ============================================================
# REQUEST SCHEMAS
# ============================================================

class EmployeeSearchRequest(BaseModel):
    employee_id: Optional[str] = None
    employee_name: Optional[str] = None
    department: Optional[str] = None


class AttritionRecordRequest(BaseModel):
    employee_record: dict[str, Any]


class CombinedAttritionRequest(BaseModel):
    employee_id: Optional[str] = None
    employee_name: Optional[str] = None
    department: Optional[str] = None


class ReplacementRequest(BaseModel):
    employee_id: str = Field(..., min_length=1)


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)

    # Conversation memory is kept per thread_id for as long as the server
    # runs. Send the same value to continue an existing conversation.
    thread_id: Optional[str] = None


# ============================================================
# INTERNAL HELPERS
# ============================================================

def _raw_message_text(message: Any) -> str:
    """Flatten one message's content into text, preserving whitespace.

    Content is a plain string for most providers, but can also be a list of
    typed blocks, or None when the model only emitted tool calls.

    Whitespace is kept exactly as received. Streaming fragments carry the
    spaces between words at their edges, so stripping each fragment would
    run the words together.
    """

    content = getattr(message, "content", None)

    if isinstance(content, str):
        return content

    if isinstance(content, list):
        return "".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )

    return ""


def _message_text(message: Any) -> str:
    """Flatten a complete message into trimmed text."""

    return _raw_message_text(message).strip()


def extract_agent_reply(messages: list[Any]) -> str:
    """Return the agent's final natural-language answer.

    The last message is not always the answer: it may be an assistant
    message carrying only tool calls, or one with null content. So the list
    is scanned backwards for the most recent assistant message that actually
    has text, and tool output is never returned to the user as a reply.
    """

    for message in reversed(messages):
        if getattr(message, "type", None) != "ai":
            continue

        text = _message_text(message)
        if text:
            return text

    return ""


def run_employee_search(
    employee_id: Optional[str] = None,
    employee_name: Optional[str] = None,
    department: Optional[str] = None,
) -> dict:
    """Resolve one employee, or raise a 400 when no identity was supplied."""

    if not employee_id and not employee_name:
        raise HTTPException(
            status_code=400,
            detail="Provide employee_id or employee_name.",
        )

    return employee_search_tool.invoke({
        "employee_id": employee_id,
        "employee_name": employee_name,
        "department": department,
    })



# ============================================================
# SCENARIO SIMULATION CHAT FAST PATH
# ============================================================
#
# This is intentionally isolated from the existing HR-agent routing.
# Normal employee, attrition, replacement, headcount and performance
# questions continue through `hr_agent` exactly as before.
#
# Clear what-if/simulation requests are converted to the same structured
# payload consumed by the Scenario Simulation tool and executed directly
# against the shared SimulationService. This avoids waiting for two LLM
# round trips when the user's intent is already unambiguous.
#

_EMPLOYEE_ID_RE = re.compile(r"\bEMP[-_ ]?0*(\d+)\b", re.IGNORECASE)
_DEPARTMENT_ID_RE = re.compile(r"\bDEPARTMENT[-_ ]?0*(\d+)\b", re.IGNORECASE)
_POSITION_ID_RE = re.compile(r"\bPOS[-_ ]?([A-Z0-9]+)\b", re.IGNORECASE)
_COURSE_ID_RE = re.compile(r"\bCOURSE[-_ ]?([A-Z0-9-]+)\b", re.IGNORECASE)
_PERCENT_RE = re.compile(r"([+-]?\d+(?:\.\d+)?)\s*%")

_SIMULATION_HINTS = (
    "what if",
    "what would happen",
    "simulate",
    "simulation",
    "impact if",
    "effects can occur",
    "effect can occur",
    "future impact",
)


def _canonical_id(match: re.Match[str] | None, prefix: str) -> str | None:
    if match is None:
        return None
    return f"{prefix}{match.group(1).upper()}"


def _extract_employee_id(message: str) -> str | None:
    match = _EMPLOYEE_ID_RE.search(message)
    if match is None:
        return None
    return f"EMP{int(match.group(1)):03d}"


def _extract_department_id(message: str) -> str | None:
    match = _DEPARTMENT_ID_RE.search(message)
    if match is None:
        return None
    return f"DEPARTMENT-{int(match.group(1)):03d}"


def _extract_position_id(message: str) -> str | None:
    return _canonical_id(_POSITION_ID_RE.search(message), "POS-")


def _extract_course_id(message: str) -> str | None:
    return _canonical_id(_COURSE_ID_RE.search(message), "COURSE-")


def _extract_percent(message: str) -> float | None:
    match = _PERCENT_RE.search(message)
    return float(match.group(1)) if match else None


def _extract_count(message: str, patterns: tuple[str, ...]) -> int | None:
    for pattern in patterns:
        match = re.search(pattern, message, flags=re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def _looks_like_simulation_request(message: str) -> bool:
    lower = message.casefold()

    if any(hint in lower for hint in _SIMULATION_HINTS):
        return True

    # Strong action phrases are treated as simulation intent even when the
    # user does not literally say "simulate".
    strong_actions = (
        "promote ",
        "promotion ",
        "transfer ",
        "reduce headcount",
        "headcount reduction",
        "hire ",
        "hiring ",
        "increase workforce",
        "workforce expansion",
        "budget reduction",
        "budget increase",
        "reduce budget",
        "increase budget",
        "reskill",
        "reskilling",
        "workload increase",
        "workload decrease",
        "demand increase",
        "demand decrease",
    )
    return any(action in lower for action in strong_actions)


def _build_simulation_payload(message: str) -> dict[str, Any] | None:
    """Convert an unambiguous what-if question into tool input.

    Returning None means the message should follow the existing HR-agent path.
    Missing scenario-specific fields are deliberately left missing so the
    deterministic simulation tool returns `needs_clarification` rather than
    allowing the LLM to guess.
    """

    if not _looks_like_simulation_request(message):
        return None

    lower = message.casefold()
    employee_id = _extract_employee_id(message)
    department_id = _extract_department_id(message)
    target_position_id = _extract_position_id(message)
    course_id = _extract_course_id(message)
    percent = _extract_percent(message)

    payload: dict[str, Any] = {
        "employee_id": employee_id,
        "department_id": department_id,
        "target_position_id": target_position_id,
        "parameters": {},
    }

    # Promotion
    if "promot" in lower:
        payload["scenario_type"] = "employee_promotion"
        return payload

    # Transfer
    if "transfer" in lower:
        payload["scenario_type"] = "employee_transfer"

        # If two department IDs are present, use the second one as the target.
        departments = list(_DEPARTMENT_ID_RE.finditer(message))
        if len(departments) >= 2:
            payload["department_id"] = None
            payload["target_department_id"] = (
                f"DEPARTMENT-{int(departments[-1].group(1)):03d}"
            )
        elif department_id:
            # A transfer question that mentions one department normally means
            # that department is the destination.
            payload["department_id"] = None
            payload["target_department_id"] = department_id

        return payload

    # Budget change
    if "budget" in lower:
        payload["scenario_type"] = "budget_change"
        if percent is not None:
            change_percentage = abs(percent)
            if any(word in lower for word in ("reduce", "reduction", "decrease", "cut")):
                change_percentage = -change_percentage
            payload["parameters"]["change_percentage"] = change_percentage
        return payload

    # Skill / reskilling
    if any(word in lower for word in ("reskill", "reskilling", "training", "course")):
        payload["scenario_type"] = "skill_reskilling"
        if course_id:
            payload["course_id"] = course_id
            payload["parameters"]["course_id"] = course_id
        return payload

    # Business demand / workload
    if any(word in lower for word in ("workload", "business demand", "demand")):
        payload["scenario_type"] = "business_demand_change"
        if percent is not None:
            demand_change = abs(percent)
            if any(word in lower for word in ("decrease", "reduce", "reduction", "drop")):
                demand_change = -demand_change
            payload["parameters"]["demand_change_percentage"] = demand_change
        return payload

    # Headcount reduction
    if (
        "headcount reduction" in lower
        or "reduce headcount" in lower
        or ("headcount" in lower and any(word in lower for word in ("reduce", "cut", "decrease")))
    ):
        payload["scenario_type"] = "headcount_reduction"

        if percent is not None:
            payload["parameters"]["reduction_percentage"] = abs(percent)
        else:
            reduce_by = _extract_count(
                message,
                (
                    r"(?:reduce|cut|decrease).{0,80}?\bby\s+(\d+)\b",
                    r"\bby\s+(\d+)\s+(?:employees?|fte(?:s)?)\b",
                ),
            )
            if reduce_by is not None:
                payload["parameters"]["reduce_by"] = reduce_by
        return payload

    # Workforce expansion / hiring
    if any(word in lower for word in ("hire", "hiring", "workforce expansion", "increase workforce")):
        payload["scenario_type"] = "workforce_expansion"
        add_headcount = _extract_count(
            message,
            (
                r"(?:hire|hiring|add).{0,40}?(\d+)\s+(?:employees?|people|fte(?:s)?)\b",
                r"(?:increase workforce|increase headcount).{0,50}?\bby\s+(\d+)\b",
            ),
        )
        if add_headcount is not None:
            payload["parameters"]["add_headcount"] = add_headcount
        return payload

    # It looked hypothetical, but it does not map confidently to one of the
    # seven supported simulations. Keep the existing HR-agent behaviour.
    return None


def _humanize_simulation_key(key: str) -> str:
    """Turn internal simulation keys/status values into user-facing text."""

    special = {
        "employee_id": "employee ID",
        "department_id": "department ID",
        "target_department_id": "target department",
        "target_position_id": "target position",
        "parameters.reduce_by_or_reduction_percentage": "reduction amount or percentage",
        "parameters.add_headcount": "number of hires to add",
        "parameters.change_percentage": "budget change percentage",
        "parameters.course_id": "course",
        "parameters.demand_change_percentage": "demand change percentage",
    }
    normalized = str(key or "").strip()
    if normalized in special:
        return special[normalized]
    return normalized.replace("_", " ").replace(".", " ").strip().lower()


def _simulation_number(value: Any, *, decimals: int = 2) -> str:
    if value is None:
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)

    if number.is_integer():
        return f"{int(number):,}"
    return f"{number:,.{decimals}f}".rstrip("0").rstrip(".")


def _simulation_pct(value: Any) -> str:
    rendered = _simulation_number(value)
    return f"{rendered}%" if rendered else ""


def _simulation_money(value: Any) -> str:
    rendered = _simulation_number(value)
    return f"PKR {rendered}" if rendered else ""


def _simulation_text(value: Any) -> str:
    """Humanize a returned enum/band without changing its meaning."""

    return str(value or "").replace("_", " ").strip()


def _simulation_decision_clause(value: Any) -> str:
    """Return a grammatically complete decision phrase for a sentence."""

    normalized = str(value or "").strip().casefold()
    clauses = {
        "recommended": "is recommended",
        "recommended_with_conditions": "is recommended with conditions",
        "not_recommended": "is not recommended",
        "review_required": "requires review",
    }
    if normalized in clauses:
        return clauses[normalized]

    readable = _simulation_text(value)
    return f"is {readable}" if readable else "is completed"


def _join_simulation_items(items: list[Any] | tuple[Any, ...] | None) -> str:
    values = [str(item) for item in (items or []) if item not in (None, "")]
    if not values:
        return ""
    if len(values) == 1:
        return values[0]
    if len(values) == 2:
        return f"{values[0]} and {values[1]}"
    return ", ".join(values[:-1]) + f", and {values[-1]}"


def _simulation_note(result: dict[str, Any]) -> str:
    assumptions = result.get("assumptions") or {}
    if assumptions.get("mutates_source_data") is False:
        return (
            "This is a what-if estimate only; the simulation does not change "
            "the underlying HR records."
        )
    return "This is a what-if estimate for decision support."


def _simulation_warning_line(result: dict[str, Any]) -> str:
    warnings = [str(item).strip() for item in (result.get("warnings") or []) if str(item).strip()]
    if not warnings:
        return ""
    return "One thing to watch: " + " ".join(warnings)


def _format_simulation_candidates(candidates: list[dict[str, Any]]) -> str:
    """Render clarification choices compactly instead of exposing raw dictionaries."""

    choices: list[str] = []
    for item in candidates[:6]:
        if not isinstance(item, dict):
            choices.append(str(item))
            continue

        primary = (
            item.get("employee_name")
            or item.get("position_title")
            or item.get("department_name")
            or item.get("course_name")
            or item.get("skill_name")
            or item.get("employee_id")
            or item.get("position_id")
            or item.get("department_id")
            or item.get("course_id")
        )
        identifiers = [
            item.get("employee_id"),
            item.get("position_id"),
            item.get("department_id"),
            item.get("course_id"),
        ]
        identifier = next((str(value) for value in identifiers if value), "")
        context = item.get("department") or item.get("designation") or item.get("skill_name")

        label = str(primary or "option")
        details = [value for value in (identifier, context) if value and str(value) not in label]
        if details:
            label += f" ({', '.join(map(str, details))})"
        choices.append(label)

    return "; ".join(choices)


def _format_promotion_reply(result: dict[str, Any]) -> str:
    baseline = result.get("baseline") or {}
    simulated = result.get("simulated_state") or {}
    impact = result.get("impact") or {}

    employee = baseline.get("employee_name") or baseline.get("employee_id") or "the employee"
    employee_id = baseline.get("employee_id")
    if employee_id and employee_id not in str(employee):
        employee = f"{employee} ({employee_id})"

    current_role = baseline.get("current_position_title") or "the current role"
    target_role = simulated.get("target_position_title") or simulated.get("target_position_id") or "the target role"
    readiness = _simulation_pct(impact.get("promotion_readiness_score_pct"))
    readiness_band = _simulation_text(impact.get("promotion_readiness_band"))
    feasibility = _simulation_text(impact.get("execution_feasibility"))

    outcome_bits = [bit for bit in (feasibility, f"{readiness} readiness" if readiness else "", readiness_band) if bit]
    lines = [
        f"The promotion simulation for {employee}, from {current_role} to {target_role}, "
        f"comes out as {', '.join(outcome_bits) if outcome_bits else 'completed'}."
    ]

    skill_match = _simulation_pct(simulated.get("target_role_skill_match_pct"))
    mandatory = _simulation_pct(simulated.get("mandatory_skill_coverage_pct"))
    missing = _join_simulation_items(simulated.get("missing_mandatory_skills") or simulated.get("missing_skills"))
    skill_parts = []
    if skill_match:
        skill_parts.append(f"target-role skill match is {skill_match}")
    if mandatory:
        skill_parts.append(f"mandatory-skill coverage is {mandatory}")
    if missing:
        skill_parts.append(f"the main gaps are {missing}")
    if skill_parts:
        lines.append("On capability, " + "; ".join(skill_parts) + ".")

    annual_change = simulated.get("annual_position_cost_change_pkr")
    admin_cost = simulated.get("promotion_admin_cost_pkr")
    cost_parts = []
    if annual_change is not None:
        direction = "increase" if float(annual_change) >= 0 else "decrease"
        cost_parts.append(f"annual position cost would {direction} by {_simulation_money(abs(float(annual_change)))}")
    if admin_cost is not None:
        cost_parts.append(f"the simulated admin cost is {_simulation_money(admin_cost)}")
    if cost_parts:
        lines.append("Financially, " + ", and ".join(cost_parts) + ".")

    warning = _simulation_warning_line(result)
    if warning:
        lines.append(warning)
    lines.append(_simulation_note(result))
    return "\n\n".join(lines)


def _format_transfer_reply(result: dict[str, Any]) -> str:
    baseline = result.get("baseline") or {}
    simulated = result.get("simulated_state") or {}
    impact = result.get("impact") or {}
    resolved = result.get("resolved_inputs") or {}

    employee = baseline.get("employee_name") or baseline.get("employee_id") or "the employee"
    employee_id = baseline.get("employee_id")
    if employee_id and employee_id not in str(employee):
        employee = f"{employee} ({employee_id})"

    source = baseline.get("source_department") or baseline.get("source_department_id") or "the current department"
    target_department = resolved.get("target_department") or baseline.get("target_department_id") or resolved.get("target_department_id") or "the target department"
    target_role = simulated.get("target_position_title") or simulated.get("target_position_id") or "the target role"
    decision = _simulation_decision_clause(impact.get("decision_status"))
    readiness = _simulation_pct(impact.get("transfer_readiness_score_pct"))
    band = _simulation_text(impact.get("transfer_readiness_band"))

    lines = [
        f"The transfer simulation for {employee} from {source} to {target_role} in {target_department} "
        f"{decision}."
    ]
    if readiness and band:
        lines.append(f"Readiness is {readiness} ({band}).")
    elif readiness:
        lines.append(f"Readiness is {readiness}.")
    elif band:
        lines.append(f"Readiness is {band}.")

    source_before = baseline.get("source_headcount")
    source_after = simulated.get("source_headcount")
    target_before = baseline.get("target_headcount")
    target_after = simulated.get("target_headcount")
    if None not in (source_before, source_after, target_before, target_after):
        lines.append(
            f"Headcount would move from {_simulation_number(source_before)} to {_simulation_number(source_after)} in the source department "
            f"and from {_simulation_number(target_before)} to {_simulation_number(target_after)} in the target department, with no net organization headcount change."
        )

    missing = _join_simulation_items(simulated.get("missing_mandatory_skills") or simulated.get("missing_skills"))
    if missing:
        lines.append(f"The main capability concern is the skill gap in {missing}.")

    annual_change = simulated.get("annual_position_cost_change_pkr")
    admin_cost = simulated.get("transfer_admin_cost_pkr")
    if annual_change is not None or admin_cost is not None:
        parts = []
        if annual_change is not None:
            direction = "increase" if float(annual_change) >= 0 else "decrease"
            parts.append(f"annual position cost would {direction} by {_simulation_money(abs(float(annual_change)))}")
        if admin_cost is not None:
            parts.append(f"transfer admin cost is {_simulation_money(admin_cost)}")
        lines.append("Financially, " + ", and ".join(parts) + ".")

    warning = _simulation_warning_line(result)
    if warning:
        lines.append(warning)
    lines.append(_simulation_note(result))
    return "\n\n".join(lines)


def _format_headcount_reduction_reply(result: dict[str, Any]) -> str:
    baseline = result.get("baseline") or {}
    simulated = result.get("simulated_state") or {}
    impact = result.get("impact") or {}

    department = baseline.get("department") or baseline.get("department_id") or "the department"
    current = baseline.get("current_headcount")
    after = simulated.get("simulated_headcount")
    reduce_by = simulated.get("reduce_by")
    decision = _simulation_decision_clause(impact.get("decision_status"))
    risk = _simulation_text(impact.get("operational_risk_band"))
    risk_score = _simulation_pct(impact.get("operational_risk_score_pct"))

    lines = [
        f"For {department}, reducing headcount by {_simulation_number(reduce_by)} would move the team from "
        f"{_simulation_number(current)} to {_simulation_number(after)} people. The simulation {decision}"
        + (f", with {risk} operational risk ({risk_score})" if risk or risk_score else "")
        + "."
    ]

    saving = simulated.get("estimated_monthly_salary_saving_pkr")
    workload_before = baseline.get("workload_index_pct")
    workload_after = simulated.get("workload_index_pct")
    gap = simulated.get("capacity_gap_headcount")
    parts = []
    if saving is not None:
        parts.append(f"estimated monthly salary saving is {_simulation_money(saving)}")
    if workload_before is not None and workload_after is not None:
        parts.append(f"workload rises from {_simulation_pct(workload_before)} to {_simulation_pct(workload_after)}")
    if gap is not None:
        parts.append(f"the resulting capacity gap is {_simulation_number(gap)} people")
    if parts:
        lines.append("The trade-off is that " + "; ".join(parts) + ".")

    warning = _simulation_warning_line(result)
    if warning:
        lines.append(warning)
    lines.append(_simulation_note(result))
    return "\n\n".join(lines)


def _format_workforce_expansion_reply(result: dict[str, Any]) -> str:
    baseline = result.get("baseline") or {}
    simulated = result.get("simulated_state") or {}
    impact = result.get("impact") or {}

    department = baseline.get("department") or baseline.get("department_id") or "the department"
    decision = _simulation_decision_clause(impact.get("decision_status"))
    budget_risk = _simulation_text(impact.get("budget_risk"))

    lines = [
        f"For {department}, adding {_simulation_number(simulated.get('add_headcount'))} people would increase headcount from "
        f"{_simulation_number(baseline.get('current_headcount'))} to {_simulation_number(simulated.get('simulated_headcount'))}. "
        f"The simulation {decision}"
        + (f", with {budget_risk} budget risk" if budget_risk else "")
        + "."
    ]

    gap_before = baseline.get("demand_gap_headcount")
    gap_after = simulated.get("demand_gap_headcount")
    if gap_before is not None and gap_after is not None:
        lines.append(
            f"Capacity improves: the demand gap falls from {_simulation_number(gap_before)} to {_simulation_number(gap_after)} people."
        )

    salary_increase = simulated.get("estimated_monthly_salary_increase_pkr")
    onboarding = simulated.get("estimated_onboarding_cost_pkr")
    utilization = simulated.get("projected_budget_utilization_pct")
    cost_parts = []
    if salary_increase is not None:
        cost_parts.append(f"monthly salary cost increases by {_simulation_money(salary_increase)}")
    if onboarding is not None:
        cost_parts.append(f"estimated onboarding cost is {_simulation_money(onboarding)}")
    if utilization is not None:
        cost_parts.append(f"projected budget utilization is {_simulation_pct(utilization)}")
    if cost_parts:
        lines.append("Financially, " + "; ".join(cost_parts) + ".")

    warning = _simulation_warning_line(result)
    if warning:
        lines.append(warning)
    lines.append(_simulation_note(result))
    return "\n\n".join(lines)


def _format_budget_change_reply(result: dict[str, Any]) -> str:
    baseline = result.get("baseline") or {}
    simulated = result.get("simulated_state") or {}
    impact = result.get("impact") or {}

    department = baseline.get("department") or baseline.get("department_id") or "the department"
    change = simulated.get("change_percentage")
    direction = "increase" if change is not None and float(change) >= 0 else "reduction"
    decision = _simulation_decision_clause(impact.get("decision_status"))
    risk = _simulation_text(impact.get("budget_risk"))

    lines = [
        f"A {_simulation_pct(abs(float(change)) if change is not None else change)} budget {direction} for {department} would move the people budget from "
        f"{_simulation_money(baseline.get('current_people_budget_pkr'))} to {_simulation_money(simulated.get('simulated_people_budget_pkr'))}. "
        f"The simulation {decision}"
        + (f", with {risk} budget risk" if risk else "")
        + "."
    ]

    remaining = simulated.get("simulated_remaining_budget_pkr")
    utilization = simulated.get("simulated_budget_utilization_pct")
    affordable = simulated.get("estimated_affordable_additional_headcount")
    details = []
    if remaining is not None:
        details.append(f"remaining budget would be {_simulation_money(remaining)}")
    if utilization is not None:
        details.append(f"budget utilization would reach {_simulation_pct(utilization)}")
    if affordable is not None:
        details.append(f"estimated affordable additional headcount would be {_simulation_number(affordable)}")
    if details:
        lines.append("After the change, " + "; ".join(details) + ".")

    warning = _simulation_warning_line(result)
    if warning:
        lines.append(warning)
    lines.append(_simulation_note(result))
    return "\n\n".join(lines)


def _format_reskilling_reply(result: dict[str, Any]) -> str:
    baseline = result.get("baseline") or {}
    simulated = result.get("simulated_state") or {}
    impact = result.get("impact") or {}

    employee = baseline.get("employee_name") or baseline.get("employee_id") or "the employee"
    employee_id = baseline.get("employee_id")
    if employee_id and employee_id not in str(employee):
        employee = f"{employee} ({employee_id})"
    course = simulated.get("course_name") or simulated.get("course_id") or "the selected course"
    skill = baseline.get("skill_name") or "the target skill"
    decision = _simulation_decision_clause(impact.get("decision_status"))
    outcome = _simulation_pct(impact.get("reskilling_outcome_score_pct"))
    band = _simulation_text(impact.get("readiness_band"))

    lines = [
        f"The reskilling simulation for {employee} using {course} {decision}. "
        f"The modeled outcome score is {outcome or 'not available'}"
        + (f" ({band})" if band else "")
        + "."
    ]

    before = baseline.get("current_skill_score")
    after = simulated.get("estimated_post_training_skill_score")
    lift = simulated.get("expected_productivity_lift_pct")
    days = simulated.get("expected_time_to_competency_days")
    if before is not None and after is not None:
        lines.append(
            f"For {skill}, the estimated skill score moves from {_simulation_number(before)} to {_simulation_number(after)}."
        )
    details = []
    if lift is not None:
        details.append(f"expected productivity lift is {_simulation_pct(lift)}")
    if days is not None:
        details.append(f"estimated time to competency is {_simulation_number(days)} days")
    if simulated.get("estimated_training_cost_pkr") is not None:
        details.append(f"estimated training cost is {_simulation_money(simulated.get('estimated_training_cost_pkr'))}")
    if details:
        lines.append("The scenario also estimates that " + "; ".join(details) + ".")

    note = (result.get("assumptions") or {}).get("note")
    if note:
        lines.append(str(note))
    else:
        lines.append(_simulation_note(result))
    return "\n\n".join(lines)


def _format_business_demand_reply(result: dict[str, Any]) -> str:
    baseline = result.get("baseline") or {}
    simulated = result.get("simulated_state") or {}
    impact = result.get("impact") or {}

    department = baseline.get("department") or baseline.get("department_id") or "the department"
    change = simulated.get("demand_change_percentage")
    direction = "increase" if change is not None and float(change) >= 0 else "decrease"
    decision = _simulation_decision_clause(impact.get("decision_status"))
    risk = _simulation_text(impact.get("workload_risk"))
    risk_score = _simulation_pct(impact.get("workload_risk_score_pct"))

    lines = [
        f"For {department}, a {_simulation_pct(abs(float(change)) if change is not None else change)} demand {direction} would move demand from "
        f"{_simulation_number(baseline.get('current_demand'))} to {_simulation_number(simulated.get('simulated_demand'))}. "
        f"The simulation {decision}"
        + (f", with {risk} workload risk ({risk_score})" if risk or risk_score else "")
        + "."
    ]

    need_before = baseline.get("current_expected_staffing_need")
    need_after = simulated.get("simulated_expected_staffing_need")
    current_hc = baseline.get("current_headcount")
    gap = simulated.get("headcount_gap")
    if None not in (need_before, need_after, current_hc):
        lines.append(
            f"Expected staffing need rises from {_simulation_number(need_before)} to {_simulation_number(need_after)} against a current headcount of {_simulation_number(current_hc)}"
            + (f", leaving a gap of {_simulation_number(gap)} people" if gap is not None else "")
            + "."
        )

    workload = simulated.get("workload_index_pct")
    gap_cost = simulated.get("estimated_monthly_salary_cost_for_gap_pkr")
    impact_parts = []
    if workload is not None:
        impact_parts.append(f"workload index reaches {_simulation_pct(workload)}")
    if gap_cost is not None:
        impact_parts.append(f"estimated monthly salary cost to cover the gap is {_simulation_money(gap_cost)}")
    if impact_parts:
        lines.append("Operationally, " + "; ".join(impact_parts) + ".")

    warning = _simulation_warning_line(result)
    if warning:
        lines.append(warning)
    lines.append(_simulation_note(result))
    return "\n\n".join(lines)


def _format_simulation_reply(result: dict[str, Any]) -> str:
    """Turn deterministic scenario output into a concise chatbot-style answer."""

    status = str(result.get("status") or "").strip().casefold()

    if status == "needs_clarification":
        missing = result.get("missing_fields") or []
        candidates = result.get("candidates") or []

        if missing:
            needed = _join_simulation_items([
                _humanize_simulation_key(str(item)) for item in missing
            ])
            question = f"I can run that simulation, but I still need the {needed}. What should I use?"
        else:
            question = str(
                result.get("message")
                or "I need one more detail before I can run that simulation."
            )

        if candidates:
            options = _format_simulation_candidates(candidates)
            if options:
                question += f" The matching options are: {options}."
        return question

    if status == "invalid_request":
        message = str(result.get("message") or "The simulation request is invalid.").strip()
        return f"I couldn't run that simulation as requested. {message}"

    scenario = str(result.get("scenario_type") or "").strip().casefold()
    formatters = {
        "employee_promotion": _format_promotion_reply,
        "employee_transfer": _format_transfer_reply,
        "headcount_reduction": _format_headcount_reduction_reply,
        "workforce_expansion": _format_workforce_expansion_reply,
        "budget_change": _format_budget_change_reply,
        "skill_reskilling": _format_reskilling_reply,
        "business_demand_change": _format_business_demand_reply,
    }
    formatter = formatters.get(scenario)
    if formatter is not None:
        return formatter(result).strip()

    # Defensive fallback for any future scenario type. Keep it readable and
    # compact rather than leaking a raw JSON-shaped response to chat users.
    return (
        "The scenario simulation completed successfully. "
        "The deterministic result is available, but this scenario does not yet "
        "have a dedicated conversational summary."
    )


def _run_simulation_fast_path(message: str) -> dict[str, Any] | None:
    payload = _build_simulation_payload(message)
    if payload is None:
        return None

    return run_scenario_simulation_tool(
        payload,
        service=simulation_service,
    )


_SIMULATION_REPLY_SYSTEM_PROMPT = """
You are the final conversational response writer for an HR Workforce Scenario Simulator.

The simulation result supplied to you is authoritative and has already been computed by
the deterministic simulation engine. Your only job is to explain that result naturally.

Rules:
- Use ONLY facts present in the supplied simulation result.
- Never recalculate, change, guess, or invent values, employees, departments, positions,
  costs, risks, scores, recommendations, or assumptions.
- Do not call tools and do not claim that you changed any HR record.
- Reply in the same language as the user's request.
- Sound like a helpful professional chatbot, not a JSON formatter or API response.
- Do not expose internal field names or enum/status identifiers such as
  employee_promotion, employee_transfer, simulated_state, decision_status,
  needs_clarification, or invalid_request unless the user explicitly asks for them.
- If the simulation cannot run, explain the reason in plain language and tell the user
  exactly what needs to be corrected or provided next.
- If it completed, lead with the main outcome, then explain the most useful impact such
  as before/after values, readiness, skills, cost, workload, risk, or recommendation only
  when those facts are present in the result.
- Keep the answer concise and easy to read: usually 2-5 short paragraphs.
- End completed simulations by making clear that this is a what-if estimate and does not
  modify the underlying HR records.
""".strip()


def _simulation_llm_messages(
    user_message: str,
    result: dict[str, Any],
) -> list[tuple[str, str]]:
    """Build a tool-free prompt that asks the LLM only to explain the result."""

    result_json = json.dumps(
        result,
        ensure_ascii=False,
        default=str,
        separators=(",", ":"),
    )
    return [
        ("system", _SIMULATION_REPLY_SYSTEM_PROMPT),
        (
            "user",
            "Original user request:\n"
            f"{user_message}\n\n"
            "Authoritative deterministic simulation result:\n"
            f"{result_json}\n\n"
            "Write the final chatbot reply now.",
        ),
    ]


def _generate_simulation_llm_reply(
    user_message: str,
    result: dict[str, Any],
) -> str:
    """Let the configured LLM explain a simulation; fall back safely if needed."""

    try:
        response = simulation_reply_model.invoke(
            _simulation_llm_messages(user_message, result)
        )
        reply = _message_text(response)
        if reply:
            return reply
    except Exception:
        # The deterministic simulation itself already succeeded (or produced a
        # valid clarification/validation result). If the provider is temporarily
        # unavailable, keep the feature usable without changing any calculation.
        pass

    return _format_simulation_reply(result)


def _stream_text_chunks(text: str, chunk_size: int = 36):
    """Stream simulation replies in small word-safe chunks like normal chat."""

    if not text:
        return

    chunk = ""
    for part in re.findall(r"\S+\s*", text):
        if chunk and len(chunk) + len(part) > chunk_size:
            yield chunk
            chunk = part
        else:
            chunk += part

    if chunk:
        yield chunk


# ============================================================
# HEALTH CHECK
# ============================================================

@app.get("/health")
def health():

    return {
        "status": "healthy",
        "employee_search_tool": "loaded",
        "attrition_prediction_tool": "loaded",
        "catboost_model": str(MODEL_PATH),
        "successor_graph": "loaded",
        "hr_agent": "loaded",
        "shared_data_path": str(DATA_PATH),

        # Straight from .env, so it is obvious which model is actually
        # serving requests.
        "llm": {
            "model": LLM.model,
            "base_url": LLM.base_url,
            "temperature": LLM.temperature,
            "max_tokens": LLM.max_tokens,
            "max_retries": LLM.max_retries,
            "reasoning": LLM.reasoning,
        },
        "successor_llm_enabled": os.getenv(
            "SUCCESSOR_LLM_ENABLED", "false"
        ),
    }


# ============================================================
# ENDPOINT 1 — EMPLOYEE SEARCH TOOL
# ============================================================

@app.post("/tools/employee-search")
def search_employee(request: EmployeeSearchRequest):

    return run_employee_search(
        employee_id=request.employee_id,
        employee_name=request.employee_name,
        department=request.department,
    )


# ============================================================
# ENDPOINT 2 — ATTRITION PREDICTION TOOL
# ============================================================

@app.post("/tools/attrition-predict")
def predict_from_employee_record(request: AttritionRecordRequest):

    employee_record = request.employee_record

    if employee_record.get("status") != "found":
        raise HTTPException(
            status_code=400,
            detail=(
                "A valid employee-search result with "
                "status='found' is required."
            ),
        )

    return attrition_prediction_tool.invoke({
        "employee_record": employee_record,
    })


# ============================================================
# ENDPOINT 3 — COMBINED ATTRITION PIPELINE
# ============================================================

@app.post("/pipeline/attrition")
def complete_attrition_pipeline(request: CombinedAttritionRequest):

    # Step 1: resolve the employee.
    employee_record = run_employee_search(
        employee_id=request.employee_id,
        employee_name=request.employee_name,
        department=request.department,
    )

    search_status = employee_record.get("status")

    # Several employees matched the supplied name.
    if search_status == "needs_clarification":
        return {
            "status": "needs_clarification",
            "candidates": employee_record.get("candidates", []),
        }

    if search_status == "not_found":
        raise HTTPException(
            status_code=404,
            detail="Employee was not found.",
        )

    if search_status != "found":
        raise HTTPException(
            status_code=400,
            detail=employee_record,
        )

    # Step 2: run the CatBoost model on the resolved record.
    return attrition_prediction_tool.invoke({
        "employee_record": employee_record,
    })


# ============================================================
# ENDPOINT 4 — LOCAL REPLACEMENT PIPELINE
# ============================================================

@app.post("/pipeline/replacement")
def complete_replacement_pipeline(request: ReplacementRequest):
    """Run the successor LangGraph against the shared CSV folder."""

    result = replacement_recommendation_tool.invoke({
        "employee_id": request.employee_id,
    })

    status = result.get("status")

    if status in {"completed", "no_candidates"}:
        return result

    if status == "needs_clarification":
        # "No such employee" is a 404, not a 400 asking the user to pick
        # from an empty candidate list. Only a genuine ambiguity, where
        # candidates are actually present, is a client-side choice.
        resolution = result.get("resolution_status")

        # A well-formed ID with no matching record is a missing resource.
        if resolution == "not_found":
            raise HTTPException(status_code=404, detail=result)

        # A malformed ID, an ambiguity, or an ID/name mismatch are all
        # things the caller can correct, so they stay 400.
        raise HTTPException(status_code=400, detail=result)

    if status == "invalid_request":
        raise HTTPException(status_code=400, detail=result)

    raise HTTPException(status_code=500, detail=result)


# ============================================================
# ENDPOINT 5 — MULTILINGUAL HR REASONING AGENT
# ============================================================

@app.post("/chat")
def chat_with_hr_agent(request: ChatRequest):
    """Send one message to the HR agent and return its reply.

    The agent decides on its own whether to check attrition risk or to
    recommend successors, and remembers the selected employee for the
    rest of the thread.
    """

    started = perf_counter()

    thread_id = request.thread_id or str(uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    # Clear Scenario Simulation questions bypass the LLM routing round trip and
    # call the same deterministic simulation core used by the REST API.
    # Every non-simulation message continues through the existing hr_agent.
    simulation_result = _run_simulation_fast_path(request.message)
    if simulation_result is not None:
        resolved = simulation_result.get("resolved_inputs") or {}
        return {
            "thread_id": thread_id,
            "reply": _generate_simulation_llm_reply(
                request.message, simulation_result
            ),
            "selected_employee_id": resolved.get("employee_id"),
            "selected_employee_name": resolved.get("employee_name"),
            "last_tool_status": simulation_result.get("status"),
            "elapsed_ms": round((perf_counter() - started) * 1000),
        }

    last_error: Optional[Exception] = None
    result: dict[str, Any] = {}
    reply = ""

    # Free models occasionally return a reply with no content at all. One
    # retry recovers those without the user having to resend the message.
    # The tools are not re-run: the agent replays from the same thread and
    # the tool results are already in its state.
    for attempt in range(CHAT_ATTEMPTS):
        payload = (
            {"messages": [{"role": "user", "content": request.message}]}
            if attempt == 0
            else {"messages": []}
        )

        try:
            result = hr_agent.invoke(payload, config=config)
        except Exception as error:
            last_error = error
            continue

        reply = extract_agent_reply(result.get("messages", []))

        if reply:
            break

    if not reply:
        detail = (
            "The HR reasoning agent could not complete the request: "
            f"{last_error}"
            if last_error is not None
            else (
                "The HR reasoning agent returned an empty response. "
                "Please send the message again."
            )
        )
        raise HTTPException(status_code=502, detail=detail)

    return {
        "thread_id": thread_id,
        "reply": reply,
        "selected_employee_id": result.get("selected_employee_id"),
        "selected_employee_name": result.get("selected_employee_name"),
        "last_tool_status": result.get("last_tool_status"),

        # Server-side round trip for this turn, so slow replies can be
        # attributed without guessing.
        "elapsed_ms": round((perf_counter() - started) * 1000),
    }


# ============================================================
# ENDPOINT 6 — STREAMING CHAT
# ============================================================

@app.post("/chat/stream")
def stream_chat_with_hr_agent(request: ChatRequest):
    """Same conversation as /chat, streamed token by token.

    A tool-using turn costs two sequential model round trips, so the
    complete answer takes several seconds. Streaming does not make that
    total shorter, but the user starts reading after the first token
    instead of staring at a blank screen until the end.

    Server-sent events. Each line is `data: {...}` with a "type" of:
      meta   - thread_id, sent immediately
      status - a tool started; show it so the wait is not a blank screen
      token  - a fragment of the answer, append it as it arrives
      done   - final state and elapsed_ms
      error  - the turn failed; message is safe to display
    """

    started = perf_counter()
    thread_id = request.thread_id or str(uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    def event(payload: dict[str, Any]) -> str:
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    # What to show while each tool runs. The first model round trip decides
    # the tool and emits no text, so without this the user waits several
    # seconds with nothing on screen.
    tool_status_text = {
        "check_employee_attrition": "Checking attrition risk...",
        "recommend_replacement": "Finding successor candidates...",
        "analyze_headcount": "Analyzing headcount data...",
        "analyze_employee_performance": "Analyzing employee performance...",
        "scenario_simulation": "Running scenario simulation...",
    }

    def generate():
        yield event({"type": "meta", "thread_id": thread_id})

        # Simulation fast path: execute the shared deterministic simulation
        # service immediately, then give that authoritative result to a plain
        # tool-free LLM for the final human-friendly wording. All non-simulation
        # messages continue through the existing hr_agent unchanged.
        simulation_result = _run_simulation_fast_path(request.message)
        if simulation_result is not None:
            yield event({
                "type": "status",
                "text": "Running scenario simulation...",
            })

            reply = _generate_simulation_llm_reply(
                request.message, simulation_result
            )
            for text_chunk in _stream_text_chunks(reply):
                yield event({"type": "token", "text": text_chunk})

            resolved = simulation_result.get("resolved_inputs") or {}
            yield event({
                "type": "done",
                "thread_id": thread_id,
                "selected_employee_id": resolved.get("employee_id"),
                "selected_employee_name": resolved.get("employee_name"),
                "last_tool_status": simulation_result.get("status"),
                "elapsed_ms": round((perf_counter() - started) * 1000),
            })
            return

        streamed_any = False
        announced: set[str] = set()

        try:
            # "messages" mode yields (chunk, metadata) as the model emits
            # tokens. The first round trip only produces tool calls with no
            # text, so nothing is shown until the answer itself starts.
            for chunk, _metadata in hr_agent.stream(
                {"messages": [{"role": "user", "content": request.message}]},
                config=config,
                stream_mode="messages",
            ):
                if getattr(chunk, "type", None) != "AIMessageChunk":
                    continue

                # Announce a tool as soon as the model commits to calling
                # it, before the tool actually runs.
                for call in getattr(chunk, "tool_calls", None) or []:
                    name = call.get("name")
                    if name and name not in announced:
                        announced.add(name)
                        yield event({
                            "type": "status",
                            "text": tool_status_text.get(
                                name, "Working..."
                            ),
                        })

                # Raw, not trimmed: the spaces between words live at the
                # edges of these fragments.
                text = _raw_message_text(chunk)

                if not text:
                    continue

                # The tool-calling round trip emits a stray whitespace-only
                # fragment before it commits to the call. Dropping leading
                # whitespace keeps the answer from starting with a blank
                # line and keeps the "first token" moment honest.
                if not streamed_any:
                    text = text.lstrip()
                    if not text:
                        continue

                streamed_any = True
                yield event({"type": "token", "text": text})

        except Exception as error:
            yield event({
                "type": "error",
                "message": (
                    "The HR reasoning agent could not complete the "
                    f"request: {error}"
                ),
            })
            return

        # The agent's state after the turn, for the employee context.
        state = hr_agent.get_state(config).values

        if not streamed_any:
            yield event({
                "type": "error",
                "message": (
                    "The HR reasoning agent returned an empty response. "
                    "Please send the message again."
                ),
            })
            return

        yield event({
            "type": "done",
            "thread_id": thread_id,
            "selected_employee_id": state.get("selected_employee_id"),
            "selected_employee_name": state.get("selected_employee_name"),
            "last_tool_status": state.get("last_tool_status"),
            "elapsed_ms": round((perf_counter() - started) * 1000),
        })

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            # Stops nginx and similar proxies buffering the stream, which
            # would defeat the point.
            "X-Accel-Buffering": "no",
        },
    )


# ============================================================
# LOCAL DEVELOPMENT SERVER
# ============================================================

if __name__ == "__main__":
    import uvicorn

    host = os.getenv("APP_HOST", "127.0.0.1")
    port = int(os.getenv("APP_PORT", "8000"))

    print(f"Data folder   : {DATA_PATH}")
    print(f"CatBoost model: {MODEL_PATH}")
    print(f"LLM model     : {LLM.model}  (from .env)")
    print(f"Swagger UI    : http://{host}:{port}/docs")

    uvicorn.run(app, host=host, port=port)
