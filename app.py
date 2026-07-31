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

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from time import perf_counter
from typing import Any, Optional
from uuid import uuid4

from dotenv import load_dotenv


# ============================================================
# PATH AND ENVIRONMENT SETUP
# ============================================================

REPO_ROOT = Path(__file__).resolve().parent

# The backend package lives one level down. It is added to sys.path so its
# modules can be imported without installing the project as a package.
BACKEND_DIR = REPO_ROOT / "backend"

if not BACKEND_DIR.is_dir():
    raise RuntimeError(
        f"Backend folder was not found: {BACKEND_DIR}"
    )

if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# The single project .env, loaded before any backend module reads it.
load_dotenv(REPO_ROOT / ".env")


from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import StreamingResponse  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

import paths  # noqa: E402
from attrition_prediction_tool import (  # noqa: E402
    create_attrition_prediction_tool,
)
from employee_record_tool import (  # noqa: E402
    create_employee_record_tool,
)
from hr_agent import create_hr_reasoning_agent  # noqa: E402
from replacement_tool import (  # noqa: E402
    create_replacement_recommendation_tool,
)
from settings import get_llm_settings  # noqa: E402


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

hr_agent = create_hr_reasoning_agent(
    employee_search_tool=employee_search_tool,
    attrition_prediction_tool=attrition_prediction_tool,
    data_path=DATA_PATH,
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

    # Credentials cannot be combined with the "*" wildcard: the browser
    # rejects that pairing outright. This API authenticates nothing, so
    # credentials stay off and the wildcard keeps working.
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
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

    if status in {"invalid_request", "needs_clarification"}:
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
    }

    def generate():
        yield event({"type": "meta", "thread_id": thread_id})

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
