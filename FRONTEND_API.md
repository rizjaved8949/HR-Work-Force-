# Frontend Integration Guide — HR Workforce Intelligence API

Everything the frontend needs to talk to this backend. Every request and
response below was captured from the running server, not written from the
schema, so the shapes are what you will actually receive.

---

## Contents

1. [Connection basics](#1-connection-basics)
2. [Timeouts](#2-timeouts)
3. [Health](#3-health)
4. [Employee search](#4-employee-search)
5. [Attrition prediction](#5-attrition-prediction)
6. [Successor / replacement](#6-successor--replacement)
7. [Headcount analytics](#7-headcount-analytics)
8. [Attrition dashboard](#8-attrition-dashboard)
9. [Chat agent](#9-chat-agent)
10. [Streaming chat](#10-streaming-chat)
11. [Error handling](#11-error-handling)
12. [Gotchas worth repeating](#12-gotchas-worth-repeating)
13. [Integration recipes](#13-integration-recipes)

---

## 1. Connection basics

| | |
|---|---|
| Base URL (local) | `http://127.0.0.1:8000` |
| Base URL (production) | `https://<your-service>.onrender.com` |
| Content type | `application/json` on every POST |
| Auth | **None.** No API key, no token, no cookies. |
| Interactive docs | `<base>/docs` (Swagger) and `<base>/redoc` |
| Machine-readable schema | `<base>/openapi.json` |

Put the base URL in an environment variable (`VITE_API_URL`,
`NEXT_PUBLIC_API_URL`, …). Never hardcode it — local and production differ.

### Endpoint map

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Liveness + active configuration |
| `POST` | `/tools/employee-search` | Resolve one employee |
| `POST` | `/tools/attrition-predict` | Score a record you already hold |
| `POST` | `/pipeline/attrition` | Resolve **and** score in one call |
| `POST` | `/pipeline/replacement` | Rank internal successors |
| `POST` | `/pipeline/headcount` | Deterministic workforce analytics |
| `GET` | `/api/v1/dashboard/attrition/summary` | People-at-risk card |
| `GET` | `/api/v1/dashboard/attrition/attrition-rate` | Rate card + donut |
| `GET` | `/api/v1/dashboard/attrition/department-risk` | Risk by department |
| `GET` | `/api/v1/dashboard/attrition/top-risk-drivers` | Top model drivers |
| `GET` | `/api/v1/dashboard/attrition/people-at-risk` | Filterable list |
| `GET` | `/api/v1/dashboard/attrition/people-at-risk/{id}` | One employee drill-down |
| `GET` | `/api/v1/dashboard/attrition/employees/{id}/profile` | Raw profile row |
| `POST` | `/api/v1/dashboard/attrition/refresh` | Force data reload |
| `POST` | `/chat` | HR agent, single reply |
| `POST` | `/chat/stream` | HR agent, streamed (SSE) |

### CORS

The backend sends CORS headers, so browser calls work cross-origin. Allowed
methods are `GET`, `POST`, `OPTIONS`; all request headers are accepted.

By default `ALLOWED_ORIGINS` is `*`, which is fine because the API uses no
cookies or credentials. In production, set it to a comma-separated list of
real frontend origins:

```
ALLOWED_ORIGINS=https://your-frontend.vercel.app,http://localhost:5173
```

Do **not** send `credentials: "include"` from `fetch`. The API authenticates
nothing, and a browser rejects credentials combined with a `*` origin.

---

## 2. Timeouts

The two chat endpoints call an LLM through OpenRouter. Everything else is
local computation.

| Endpoint group | Typical | Client timeout |
|---|---|---|
| `/chat`, `/chat/stream` | 3–10 s, occasionally much longer | **≥ 120 s** |
| `/tools/*`, `/pipeline/*` | well under 1 s | 30 s |
| `/api/v1/dashboard/*` | under 1 s once warm | 30 s |

Chat latency depends entirely on the configured model and how busy the
provider is — a free-tier model can take a minute or more under load. Size
the loading state for the worst case, not the median, and prefer
`/chat/stream` so the user sees words immediately.

The first dashboard call after startup scores the whole workforce through the
CatBoost model and is slower than later calls, which are served from cache.

On Render's free plan the service **sleeps when idle**. The first request after
a sleep adds a cold start on top. Show a "waking up" state rather than an error.

---

## 3. Health

### `GET /health`

Liveness plus the active configuration. Useful for a connection indicator.

```json
{
  "status": "healthy",
  "employee_search_tool": "loaded",
  "attrition_prediction_tool": "loaded",
  "catboost_model": "/app/models/catboost_attrition_model.cbm",
  "successor_graph": "loaded",
  "hr_agent": "loaded",
  "shared_data_path": "/app/Data",
  "llm": {
    "model": "…",
    "base_url": "https://openrouter.ai/api/v1",
    "temperature": 0.0,
    "max_tokens": 1200,
    "max_retries": 3,
    "reasoning": "off"
  },
  "successor_llm_enabled": "false"
}
```

The component values are fixed strings confirming startup wiring, not live
dependency checks. Treat this as liveness, not readiness.

---

## 4. Employee search

### `POST /tools/employee-search`

Resolve one employee and return their full record.

**Request** — send `employee_id` *or* `employee_name`. `department` narrows
an ambiguous name but cannot identify anyone on its own.

```json
{ "employee_id": "EMP004" }
```
```json
{ "employee_name": "Ali", "department": "Finance" }
```

Employee IDs are `EMP` + digits, normalized to three digits (`emp4` →
`EMP004`). Input is case-insensitive and tolerates hyphens and spaces.

**This endpoint has three different success shapes.** All return HTTP 200,
so you must branch on `status` — not on the status code.

#### `status: "found"`

```json
{
  "status": "found",
  "match_method": "employee_id",
  "employee": {
    "employee_id": "EMP004",
    "employee_name": "Ali Masood",
    "name_aliases": [],
    "department": "Finance",
    "designation": "Financial Analyst",
    "office": null,
    "job_level": "Mid",
    "position_ids": ["POS-004"]
  },
  "records": {
    "profile": { "Employee_ID": "EMP004", "Tenure_Months": "39", "…": "…" },
    "attendance": { "…": "…" },
    "performance": { "…": "…" },
    "experience": { "…": "…" },
    "skills": [ { "…": "…" } ],
    "attrition_features": { "…": "…" },
    "position": { "…": "…" },
    "position_requirements": { "…": "…" },
    "position_skill_requirements": { "…": "…" },
    "skill_catalog": { "…": "…" }
  }
}
```

Notes for rendering:

- `employee` is the flat summary — use it for cards and headers.
- `records` is the raw CSV detail. **Every value inside `records` is a
  string**, including numbers (`"39"`, `"3.3"`). Parse before you do
  arithmetic or comparisons. (The dashboard profile endpoint in §8.7 returns
  the same fields properly typed — prefer it when you just need to display
  a profile.)
- `records.skills` is an array; the other sections are single objects.
- Any field can be `null` or an empty object `{}` when the source CSV had no
  row. Guard before reading nested keys.
- `records` is large. If you only need identity, read `employee` and ignore it.

#### `status: "needs_clarification"`

The name matched several people, or matched only approximately. Show a
picker and re-call with the chosen `employee_id`.

```json
{
  "status": "needs_clarification",
  "match_method": "partial_name",
  "message": "Multiple or approximate employee matches were found. Ask the user to select the correct employee, preferably by Employee ID.",
  "candidates": [
    { "employee_id": "EMP003", "employee_name": "Kamran Ali",
      "department": "Finance", "designation": "Financial Analyst",
      "job_level": "Mid", "position_ids": ["POS-003"],
      "name_aliases": [], "office": null },
    { "employee_id": "EMP004", "employee_name": "Ali Masood", "…": "…" }
  ]
}
```

#### `status: "not_found"`

```json
{
  "status": "not_found",
  "message": "No employee was found with Employee ID 'EMP999'.",
  "searched_employee_id": "EMP999"
}
```

**Errors:** omitting both `employee_id` and `employee_name` returns
HTTP 400 `{"detail": "Provide employee_id or employee_name."}`. Sending only
`department` is the same error.

---

## 5. Attrition prediction

### `POST /pipeline/attrition` ← use this one for risk

Search **and** predict in a single call. This is the endpoint you want for
an attrition screen; it saves a round trip.

**Request** — same fields as employee search:

```json
{ "employee_id": "EMP004" }
```

**Response (employee found):**

```json
{
  "attrition": "Yes",
  "top_reasons": [
    "Job_Satisfaction_Score",
    "Salary_vs_Market_pct",
    "Overtime_Hours_Last_30D"
  ]
}
```

A low-risk employee:

```json
{ "attrition": "No", "top_reasons": [] }
```

Rendering notes:

- `attrition` is the string `"Yes"` or `"No"` — **not a boolean**, and there
  is no probability score in the response. If you need a numeric risk score,
  use the dashboard detail endpoint (§8.6), which returns
  `risk_score_percent`.
- `top_reasons` holds up to 3 raw model feature names. They are
  `Snake_Case` column names, not display text. Map them to human labels in
  the frontend, e.g. `Job_Satisfaction_Score` → "Job satisfaction". The
  dashboard endpoints return pre-labelled versions.
- `top_reasons` is `[]` whenever `attrition` is `"No"`. Do not assume it is
  populated.

**Other outcomes:**

- Ambiguous name → HTTP 200 with `{"status": "needs_clarification",
  "candidates": [...]}` — the same candidate shape as §4. This response has
  **no** `attrition` key, so check for `status` first.
- Unknown employee → HTTP 404 `{"detail": "Employee was not found."}`
- Neither identifier supplied → HTTP 400.

### `POST /tools/attrition-predict` (advanced)

Predicts from a record you already hold, skipping the lookup. Only useful if
you already called `/tools/employee-search`; otherwise prefer
`/pipeline/attrition`.

**Request** — the *entire, unmodified* search response goes inside
`employee_record`:

```json
{ "employee_record": { "status": "found", "employee": { "…": "…" }, "records": { "…": "…" } } }
```

The object must have `status: "found"` or you get HTTP 400. Response is
identical to `/pipeline/attrition`.

---

## 6. Successor / replacement

### `POST /pipeline/replacement`

Rank internal successor candidates for an employee. Deterministic scoring —
no LLM by default, so this is fast.

**Request** — `employee_id` only; a name is not accepted here.

```json
{ "employee_id": "EMP004" }
```

`employee_id` is required and must be at least 1 character, otherwise
HTTP 422.

**Response:**

```json
{
  "status": "completed",
  "target_employee_id": "EMP004",
  "recommended_successors": [
    {
      "rank": 1,
      "employee_id": "EMP161",
      "employee_name": "Iqra Yousaf",
      "current_position": "Financial Analyst",
      "final_score": 97.97,
      "qualification_status": "Qualified",
      "readiness": "Ready Now",
      "reasons": [
        "The candidate has a strong match with the required position skills.",
        "The candidate meets the relevant and total experience requirements.",
        "The candidate has demonstrated strong recent job performance.",
        "The candidate meets all mandatory position requirements."
      ]
    }
  ],
  "disclaimer": "These recommendations are decision support. The final succession decision remains with authorized HR or management."
}
```

Rendering notes:

- At most **3** candidates, already sorted by `rank` (1 = best).
- `final_score` is a number 0–100 — safe for a progress bar.
- `qualification_status` observed values: `"Qualified"`,
  `"Development Candidate"`. `readiness` observed values: `"Ready Now"`,
  `"Ready in 3-6 Months"`, `"Ready in 6-12 Months"`. Treat both as
  open-ended strings and style with a fallback rather than a hard switch.
- `reasons` is a list of complete, display-ready sentences — render as-is.
- **Show the `disclaimer`.** It is returned deliberately.

**No suitable candidates** → HTTP 200 with `status: "no_candidates"` and
`recommended_successors: []`. Handle as an empty state, not an error.

**Error outcomes.** The `detail` is an object, and `resolution_status` tells
you which case you are in:

| HTTP | `resolution_status` | Meaning | UI action |
|---|---|---|---|
| 400 | `invalid_reference` | Malformed ID (does not start with `EMP`) | Fix the input |
| 404 | `not_found` | Well-formed ID, no such employee | "No such employee" |
| 400 | `ambiguous` | Several people matched | Show `candidates` picker |
| 400 | `identifier_mismatch` | ID and name disagree | Ask user to confirm |
| 500 | — | Graph or data failure | Retry / report |

```json
{
  "detail": {
    "status": "needs_clarification",
    "employee_id": "EMP999",
    "resolution_status": "not_found",
    "message": "Employee ID EMP999 was not found in the dataset.",
    "candidates": []
  }
}
```

> **Branch on `resolution_status`, not the outer `status`.** The outer value is
> `needs_clarification` for all four cases, and only `ambiguous` actually has a
> non-empty `candidates` array to show. Rendering a picker for the others gives
> the user an empty list.

---

## 7. Headcount analytics

### `POST /pipeline/headcount`

Deterministic workforce analytics over the headcount datasets. **No LLM is
involved** — the same question always produces the same numbers. Covers current
headcount, positions, vacancies, budget, daily availability, historical trends,
workforce movement, employee and position lookups, governance rules, exceptions,
and metric definitions.

**Request** — a natural-language question is enough. The optional fields let you
bypass inference and pin the plan exactly.

```json
{ "question": "What is the current headcount by department?" }
```

| Field | Type | Notes |
|---|---|---|
| `question` | string, min 3 chars | Required |
| `analysis_type` | enum \| null | See list below |
| `metrics` | string[] | Explicit metric names |
| `group_by` | string[] | e.g. `["department"]` |
| `filters` | object[] | Field / operator / value |
| `date_range` | object \| null | Historical scoping |
| `scope` | object | `department`, `business_unit`, `employee_id`, … |
| `sort_by` / `sort_direction` | string \| null | Ranking control |
| `top_n` | int \| null | Limit ranked rows |
| `include_details` | bool | Include the `records` array |

`analysis_type` values: `overview`, `metric`, `breakdown`, `ranking`,
`comparison`, `trend`, `detail_list`, `employee_lookup`, `position_lookup`,
`vacancy`, `budget`, `movement`, `availability`, `exception`, `definition`,
`rule`, `combined`.

**Response — `status: "success"`:**

```json
{
  "status": "success",
  "question": "What is the current headcount by department?",
  "analysis_type": "breakdown",
  "message": "Headcount calculation completed successfully.",
  "resolved_scope": { "organization": "All", "group_by": "department" },
  "metrics": [
    {
      "metric_name": "actual_employee_count",
      "display_name": "Actual Employee Count",
      "value": 720,
      "unit": "employees",
      "numerator": null,
      "denominator": null
    }
  ],
  "records": [
    {
      "department_id": "DEPARTMENT-001",
      "department": "HR",
      "business_unit": "Corporate Services",
      "actual_employee_count": 45
    }
  ],
  "evidence_sources": ["Position_Vacancy_History.csv", "Position_Master.csv"],
  "data_as_of_date": "2026-08-01",
  "calculation_notes": ["…"],
  "limitations": []
}
```

Rendering notes:

- Render `metrics` as headline figures and `records` as the table.
- **Always surface `data_as_of_date`.** The dataset has a fixed reporting date
  and users will otherwise assume the numbers are live.
- Show `calculation_notes` and `limitations` when non-empty — they qualify how
  a figure was derived (for example, whether frozen positions are counted).
- `numerator` / `denominator` are populated only for ratio metrics; both are
  `null` for plain counts.

**Response status values:** `success`, `partial`, `not_found`, `unsupported`,
`invalid_request`, `error`. All arrive with HTTP 200 — only schema violations
return 422.

**`status: "unsupported"`** — the question matched no metric, dimension, or
scope:

```json
{
  "status": "unsupported",
  "question": "purple monkey dishwasher",
  "analysis_type": "overview",
  "message": "This question could not be matched to any Headcount metric, dimension, or scope. Please rephrase it in terms of headcount, positions, vacancies, budget, or workforce movement.",
  "limitations": ["No recognizable Headcount terms were found in the question."]
}
```

Show this as a prompt to rephrase. **Do not render empty metric tiles** — the
`metrics` array is empty here.

**HTTP 422** — `question` shorter than 3 characters.

---

## 8. Attrition dashboard

Read-only aggregate endpoints under `/api/v1/dashboard/attrition`. Results are
computed once and cached; every successful response carries `status: "success"`.

### 8.1 `GET /summary`

```json
{
  "status": "success",
  "visual": "people_at_risk",
  "prediction_window": "next_6_months",
  "risk_threshold": 0.5,
  "total_employees": 720,
  "people_at_risk": 207,
  "people_not_at_risk": 513,
  "attrition_risk_rate_percent": 28.75,
  "people_at_risk_endpoint": "/api/v1/dashboard/attrition/people-at-risk",
  "department_risk_endpoint": "/api/v1/dashboard/attrition/department-risk",
  "top_risk_drivers_endpoint": "/api/v1/dashboard/attrition/top-risk-drivers"
}
```

### 8.2 `GET /attrition-rate`

Card values plus ready-to-plot donut segments.

```json
{
  "status": "success",
  "visual": "attrition_rate_overview",
  "title": "Predicted Attrition Rate",
  "description": "Current workforce distribution based on the attrition prediction model.",
  "prediction_window": "next_6_months",
  "risk_threshold": 0.5,
  "total_employees": 720,
  "attrition_rate_percent": 28.75,
  "people_at_risk": 207,
  "people_not_at_risk": 513,
  "card": {
    "label": "Predicted Attrition Rate",
    "value_percent": 28.75,
    "supporting_text": "207 of 720 employees are currently flagged at risk"
  },
  "chart": {
    "type": "donut",
    "name_key": "risk_status",
    "value_key": "employee_count",
    "segments": [{ "risk_status": "At Risk", "employee_count": 207 }]
  }
}
```

`chart.name_key` and `chart.value_key` name the fields to bind, so `segments`
can go straight into a charting library without reshaping.

### 8.3 `GET /department-risk`

```json
{
  "status": "success",
  "visual": "attrition_risk_by_department",
  "metric": "people_at_risk",
  "total_departments": 16,
  "total_people_at_risk": 207,
  "highest_risk_department": { "rank": 1, "department": "Customer Support", "…": "…" },
  "departments": [
    {
      "rank": 1,
      "department": "Customer Support",
      "people_at_risk": 30,
      "total_employees": 45,
      "risk_rate_percent": 66.67,
      "people_at_risk_endpoint": "/api/v1/dashboard/attrition/people-at-risk?department=Customer Support"
    }
  ]
}
```

Each row carries a ready-made drill-down URL. **URL-encode it before use** —
department names contain spaces and `&`.

### 8.4 `GET /top-risk-drivers?limit=3`

`limit` is 1–10, default 3.

```json
{
  "status": "success",
  "visual": "top_attrition_risk_drivers",
  "title": "Top Attrition Risk Drivers",
  "basis": "model_top_features_for_at_risk_employees",
  "interpretation_note": "Percentages are shares of model risk-driver mentions, not confirmed exit reasons.",
  "people_at_risk": 207,
  "reasons_per_employee_maximum": 3,
  "total_reason_mentions": 621,
  "top_driver": { "rank": 1, "feature_key": "Job_Satisfaction_Score", "…": "…" },
  "drivers": [
    {
      "rank": 1,
      "feature_key": "Job_Satisfaction_Score",
      "label": "Job satisfaction",
      "mention_count": 168,
      "share_percent": 27.05,
      "employee_share_percent": 81.16
    }
  ]
}
```

**Display `interpretation_note` next to this chart.** `share_percent` is a share
of driver *mentions*, not of employees, and the two read very differently.
`employee_share_percent` — the percentage of at-risk employees showing that
driver — is usually the more intuitive number for a caption.

### 8.5 `GET /people-at-risk`

| Query param | Type | Default | Notes |
|---|---|---|---|
| `offset` | int ≥ 0 | 0 | |
| `limit` | int 1–200 | 50 | 422 outside range |
| `department` | string | — | Exact department name |
| `position_criticality` | string | — | e.g. `High` |
| `search` | string | — | Name or ID substring |

```json
{
  "status": "success",
  "visual": "people_at_risk",
  "total_matching": 207,
  "offset": 0,
  "limit": 50,
  "employees": [
    {
      "employee_id": "EMP004",
      "employee_name": "Ali Masood",
      "department": "Finance",
      "position_id": "POS-004",
      "position_title": "Financial Analyst",
      "designation": "Financial Analyst",
      "job_level": "Mid",
      "position_criticality": "Medium",
      "attrition_status": "At Risk",
      "risk_score_percent": 92.22,
      "attrition_factors": ["Job satisfaction", "Salary competitiveness against the market"],
      "detail_endpoint": "/api/v1/dashboard/attrition/people-at-risk/EMP004",
      "profile_endpoint": "/api/v1/dashboard/attrition/employees/EMP004/profile"
    }
  ]
}
```

Paginate on `total_matching`, not on `employees.length`. Note `attrition_factors`
here are **already human-readable**, unlike `top_reasons` from
`/pipeline/attrition`.

### 8.6 `GET /people-at-risk/{employee_id}`

Full risk breakdown plus successor recommendations for one employee — the
drill-down behind a row.

```json
{
  "status": "success",
  "employee": {
    "employee_id": "EMP004",
    "employee_name": "Ali Masood",
    "department": "Finance",
    "position_id": "POS-004",
    "position_title": "Financial Analyst",
    "designation": "Financial Analyst",
    "job_level": "Mid",
    "position_criticality": "Medium",
    "attrition_status": "At Risk",
    "risk_score_percent": 92.22,
    "attrition_factors": ["Job satisfaction", "…"],
    "profile_endpoint": "/api/v1/dashboard/attrition/employees/EMP004/profile"
  },
  "attrition": {
    "prediction_window": "next_6_months",
    "status": "At Risk",
    "risk_score_percent": 92.22,
    "factors": [
      { "rank": 1, "feature_key": "Job_Satisfaction_Score", "label": "Job satisfaction", "value": "…" }
    ]
  },
  "replacement_status": "completed",
  "recommended_replacements": [ { "rank": 1, "…": "…" } ],
  "decision_support_disclaimer": "…"
}
```

This is the richest single call for an employee view: labelled factors, a
numeric `risk_score_percent`, and successors in one response. Prefer it over
combining `/pipeline/attrition` and `/pipeline/replacement` yourself.

- **404** — employee not found.
- **409** — employee exists but is **not currently flagged at risk**. Expected,
  not an error: fall back to `/pipeline/attrition` for a plain Yes/No.

### 8.7 `GET /employees/{employee_id}/profile`

Returns the `Employee_Profile.csv` row plus position criticality, using the
original column names (`Employee_ID`, `Tenure_Months`, …).

Unlike `records` in §4, **numeric fields here are properly typed** —
`"Tenure_Months": 39`, not `"39"`. Prefer this endpoint for profile display.

**404** if unknown.

### 8.8 `POST /refresh`

Forces a reload and re-scoring after the CSVs change. Returns the same body as
`/summary`. Call it after data edits — the dashboard caches aggressively
otherwise.

---

## 9. Chat agent

### `POST /chat`

One message in, one reply out. The agent decides on its own whether to check
attrition risk, recommend successors, or run headcount analytics, and remembers
the employee under discussion for the rest of the thread. It answers in the
user's language.

**Request:**

```json
{ "message": "What is the attrition risk for EMP004?", "thread_id": null }
```

- `message` — required, non-empty (422 otherwise).
- `thread_id` — omit or `null` on the first message. The server generates
  one and returns it. **Send that same value on every later message** to
  continue the conversation; a new `thread_id` means the agent has forgotten
  everything.

**Response:**

```json
{
  "thread_id": "0576ddbc-0809-4955-88b2-3bbe35e762df",
  "reply": "The attrition model indicates risk for Ali Masood (EMP004), Finance - Financial Analyst. The contributing factors are job satisfaction, salary competitiveness against the market, and recent overtime workload. …",
  "selected_employee_id": "EMP004",
  "selected_employee_name": "Ali Masood",
  "last_tool_status": "completed",
  "elapsed_ms": 3552
}
```

- `reply` may contain Markdown — the agent uses `**bold**` and numbered lists
  for multi-candidate answers. Render it through a Markdown component, or the
  asterisks show up literally.
- `selected_employee_id` / `selected_employee_name` are the agent's current
  context. Useful for an "actively discussing …" chip. Both can be `null`
  before an employee is chosen.
- `last_tool_status` reflects the tool the agent ran: `completed` (attrition),
  `success` (headcount), `needs_clarification`, `not_found`,
  `identity_conflict`, `invalid_request`, or `error`. It is `null` when the
  agent answered conversationally without calling a tool.
- `elapsed_ms` is the server-side round trip — handy for a debug overlay.

**Errors:** HTTP 502 with `{"detail": "…"}` when the agent fails or returns
empty. The detail text is safe to display. Offer a retry button rather than
treating it as fatal — the server already retries an empty reply once.

> **Memory is in-process.** Threads live in server memory and are lost on
> restart. Do not run multiple uvicorn workers for chat — the same `thread_id`
> would land on a different worker and lose its history.

---

## 10. Streaming chat

### `POST /chat/stream`

Identical request body and conversation semantics as `/chat`. Returns
**Server-Sent Events** (`text/event-stream`). Strongly preferred for chat UI:
the total time is the same, but the user starts reading immediately.

Each line is `data: {json}` followed by a blank line. Five event types:

| `type` | Payload | What to do |
|---|---|---|
| `meta` | `thread_id` | Arrives immediately. Store the id at once. |
| `status` | `text` | A tool started. Show as a transient status line. |
| `token` | `text` | A fragment of the answer. **Append verbatim.** |
| `done` | `thread_id`, `selected_employee_id`, `selected_employee_name`, `last_tool_status`, `elapsed_ms` | Turn finished. Same fields as `/chat`. |
| `error` | `message` | Turn failed. Display `message`, stop the stream. |

Status texts: `"Checking attrition risk..."`,
`"Finding successor candidates..."`, `"Analyzing headcount data..."`.

Real captured stream:

```
data: {"type": "meta", "thread_id": "9d597f5e-53bc-41cc-ac32-c5395c537229"}

data: {"type": "status", "text": "Finding successor candidates..."}

data: {"type": "token", "text": "Top"}

data: {"type": "token", "text": " replacement"}

data: {"type": "token", "text": " candidates"}

data: {"type": "token", "text": " for"}

data: {"type": "token", "text": " E"}

data: {"type": "token", "text": "MP"}
```

Critical details:

- **Concatenate `token.text` with no separator.** The spaces live at the
  edges of the fragments (`" replacement"`). Joining with a space, or
  trimming each fragment, mangles the text.
- Tokens split mid-word (`"E"`, `"MP"`, `"0"`, `"0"`, `"4"` → `EMP004`).
  Never parse a partial buffer — only the accumulated string is meaningful.
- Because the answer may be Markdown, re-render the **whole accumulated
  string** through your Markdown component on each token, rather than
  appending rendered HTML.
- Expect several seconds of silence between `status` and the first `token`
  while the tool runs. That is the model working, not a stall.

**You cannot use `EventSource`** — it only issues GET requests and this is a
POST. Use `fetch` with a stream reader:

```js
const response = await fetch(`${API_URL}/chat/stream`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ message, thread_id: threadId }),
});

const reader = response.body.getReader();
const decoder = new TextDecoder();
let buffer = "";
let answer = "";

while (true) {
  const { done, value } = await reader.read();
  if (done) break;

  buffer += decoder.decode(value, { stream: true });

  // Events are separated by a blank line. Keep the trailing partial
  // event in the buffer until the rest of it arrives.
  const events = buffer.split("\n\n");
  buffer = events.pop();

  for (const raw of events) {
    if (!raw.startsWith("data: ")) continue;
    const event = JSON.parse(raw.slice(6));

    if (event.type === "meta")   setThreadId(event.thread_id);
    if (event.type === "status") setStatus(event.text);
    if (event.type === "token")  setAnswer(answer += event.text);
    if (event.type === "done")   setSelected(event.selected_employee_id);
    if (event.type === "error")  setError(event.message);
  }
}
```

The buffering matters: a network chunk can split an event in half, so never
`JSON.parse` before you have seen the blank-line terminator.

---

## 11. Error handling

| Code | Meaning | Frontend behaviour |
|---|---|---|
| 200 | Delivered — **but check the `status` field** | Branch on domain status |
| 400 | Bad input, malformed ID, or ambiguity | Fix the request; show a form error |
| 404 | Employee or resource does not exist | Empty state |
| 409 | Employee exists but is not at risk (§8.6) | Explain; not an error |
| 422 | Schema violation (FastAPI validation) | Fix the request |
| 500 | Internal failure | Generic error + retry |
| 502 | Agent failed or returned empty | Show `detail`, offer retry |

Most error bodies use FastAPI's standard shape:

```json
{ "detail": "Provide employee_id or employee_name." }
```

`detail` is usually a string, but on `/pipeline/replacement` it is an
**object** (§6), and on 422 it is an **array**:

```json
{
  "detail": [
    {
      "type": "string_too_short",
      "loc": ["body", "question"],
      "msg": "String should have at least 3 characters",
      "input": "a"
    }
  ]
}
```

A robust extractor covering all three:

```js
function errorMessage(body) {
  const detail = body?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((e) => e.msg).join(", ");
  if (detail?.message) return detail.message;   // replacement errors
  return "Something went wrong.";
}
```

---

## 12. Gotchas worth repeating

1. **HTTP 200 does not mean success.** `not_found`, `needs_clarification`, and
   `unsupported` all arrive as 200. Always read `status`.
2. **Numbers inside `records` are strings.** `"39"`, not `39`. The dashboard
   profile endpoint (§8.7) returns them properly typed.
3. **`attrition` is `"Yes"`/`"No"`, not a boolean**, and carries no
   probability. Use §8.6 for `risk_score_percent`.
4. **`top_reasons` are raw feature names** needing a display-name map, and are
   empty whenever `attrition` is `"No"`. The dashboard returns labelled
   versions.
5. **On `/pipeline/replacement`, branch on `resolution_status`**, not the outer
   `status` — otherwise every failure looks like an ambiguity with no
   candidates.
6. **Chat can take a long time.** Do not set a short timeout.
7. **Never trim or space-join stream tokens.**
8. **Agent replies may be Markdown.** Render them as such.
9. **Reuse `thread_id`** or the agent loses all memory, and run a single
   uvicorn worker for chat.
10. **Always show `data_as_of_date`** on headcount results — the data has a
    fixed reporting date and is not live.
11. **Send headcount questions verbatim.** Do not paraphrase away dates,
    filters, or grouping words; the planner reads them.
12. **No auth** — do not build a login against this API; it has none.

---

## 13. Integration recipes

### Employee risk page

1. `POST /pipeline/attrition` with the ID or name.
2. If `status === "needs_clarification"`, render `candidates` and repeat with
   the chosen `employee_id`.
3. On a prediction, call `GET /api/v1/dashboard/attrition/people-at-risk/{id}`
   for labelled factors, a numeric score, **and** successors in one call.
4. A `409` from step 3 means the employee is not flagged at risk — expected.
   Fall back to the `top_reasons` from step 1.

### Dashboard landing page

Fire these four in parallel; none depends on another:

```
GET /api/v1/dashboard/attrition/summary
GET /api/v1/dashboard/attrition/attrition-rate
GET /api/v1/dashboard/attrition/department-risk
GET /api/v1/dashboard/attrition/top-risk-drivers?limit=5
```

Then lazy-load `/people-at-risk` for the table. The first call after startup is
slower while the model scores the workforce; subsequent calls are cached.

### Chat widget

1. First message: `POST /chat/stream` with no `thread_id`.
2. Store `thread_id` from the `meta` event.
3. Send it with every later message.
4. Use `selected_employee_id` from `done` to keep a context chip in sync.
5. On `error`, offer a resend.

### Headcount query box

Send the user's question **verbatim** to `POST /pipeline/headcount`. Handle
`status: "unsupported"` by prompting for a rephrase rather than rendering an
empty result. Show `data_as_of_date` in the footer of every result.

---

## 14. Quick local start

```bash
uvicorn app:app --reload
```

or

```bash
python app.py
```

Serves on `http://127.0.0.1:8000`; open `/docs` to try any endpoint by hand
before wiring it up. Verify the connection with:

```bash
curl http://127.0.0.1:8000/health
```
