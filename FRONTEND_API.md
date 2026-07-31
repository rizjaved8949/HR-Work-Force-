# Frontend Integration Guide — HR Workforce Intelligence API

Everything the frontend needs to talk to this backend. Every request and
response below was captured from the running server, not written from the
schema, so the shapes are what you will actually receive.

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

## 2. Timeouts — read this before writing any fetch

The two chat endpoints call a free-tier LLM through OpenRouter. A measured
real response on this backend took **59.6 seconds**. That is normal, not a
bug: a tool-using turn needs two sequential model round trips, and the
`:free` model shares a queue with every other user.

Practical rules:

- **Never** set a client timeout below **120 s** on `/chat` or `/chat/stream`.
  The browser default (no timeout) is safer than a short `AbortController`.
- **Prefer `/chat/stream`.** Same work, same total, but the user sees the
  first words in a few seconds instead of a blank screen for a minute.
- The non-LLM endpoints are fast — `/tools/*` and `/pipeline/*` return in
  well under a second. 30 s is a generous timeout there.
- On Render's free plan the service **sleeps when idle**. The first request
  after a sleep adds a cold start on top. Show a "waking up" state rather
  than an error if the first call is slow.

---

## 3. Endpoint reference

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
    "model": "nvidia/nemotron-3-ultra-550b-a55b:free",
    "base_url": "https://openrouter.ai/api/v1",
    "temperature": 0.0,
    "max_tokens": 1200,
    "max_retries": 3,
    "reasoning": "on"
  },
  "successor_llm_enabled": "false"
}
```

---

### `POST /tools/employee-search`

Resolve one employee and return their full record.

**Request** — send `employee_id` *or* `employee_name`. `department` narrows
an ambiguous name.

```json
{ "employee_id": "EMP001" }
```
```json
{ "employee_name": "Sonia", "department": "HR" }
```

**This endpoint has three different success shapes.** All return HTTP 200,
so you must branch on `status` — not on the status code.

#### `status: "found"`

```json
{
  "status": "found",
  "match_method": "employee_id",
  "employee": {
    "employee_id": "EMP001",
    "employee_name": "Sonia Hassan",
    "name_aliases": [],
    "department": "HR",
    "designation": "HR Manager",
    "office": null,
    "job_level": "Lead/Manager",
    "position_ids": ["POS-001"]
  },
  "records": {
    "profile": { "Employee_ID": "EMP001", "Tenure_Months": "140", "…": "…" },
    "attendance": { "Attendance_Percentage": "100.0", "…": "…" },
    "performance": { "KPI_Achievement_pct": "100.1", "…": "…" },
    "experience": { "…": "…" },
    "skills": [ { "…": "…" } ],
    "attrition_features": { "…": "…" }
  }
}
```

Notes for rendering:

- `employee` is the flat summary — use it for cards and headers.
- `records` is the raw CSV detail. **Every value inside `records` is a
  string**, including numbers (`"140"`, `"100.1"`). Parse before you do
  arithmetic or comparisons.
- `records.skills` is an array; the other sections are single objects.
- Any field can be `null` or an empty object `{}` when the source CSV had no
  row. Guard before reading nested keys.

#### `status: "needs_clarification"`

The name matched several people, or matched only approximately. Show a
picker and re-call with the chosen `employee_id`.

```json
{
  "status": "needs_clarification",
  "match_method": "fuzzy_name",
  "message": "Multiple or approximate employee matches were found. …",
  "candidates": [
    { "employee_id": "EMP001", "employee_name": "Sonia Hassan",
      "department": "HR", "designation": "HR Manager",
      "job_level": "Lead/Manager", "position_ids": ["POS-001"],
      "name_aliases": [], "office": null },
    { "employee_id": "EMP007", "employee_name": "Sonia Ahmad",
      "department": "Customer Support", "…": "…" }
  ],
  "next_action": "Ask which employee is intended, then call this tool again with employee_id."
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
HTTP 400 `{"detail": "Provide employee_id or employee_name."}`.

---

### `POST /pipeline/attrition` ← use this one for risk

Search **and** predict in a single call. This is the endpoint you want for
an attrition screen; it saves a round trip.

**Request** — same fields as employee search:

```json
{ "employee_id": "EMP021" }
```

**Response (employee found):**

```json
{
  "attrition": "Yes",
  "top_reasons": [
    "Monthly_Salary_PKR",
    "Salary_vs_Market_pct",
    "Last_Increment_pct"
  ]
}
```

A low-risk employee:

```json
{ "attrition": "No", "top_reasons": [] }
```

Rendering notes:

- `attrition` is the string `"Yes"` or `"No"` — **not a boolean**, and there
  is no probability score in the response.
- `top_reasons` holds up to 3 raw model feature names. They are
  `Snake_Case` column names, not display text. Map them to human labels in
  the frontend, e.g. `Monthly_Salary_PKR` → "Monthly salary".
- `top_reasons` is frequently `[]`, especially when `attrition` is `"No"`.
  Do not assume it is populated.

**Other outcomes:**

- Ambiguous name → HTTP 200 with `{"status": "needs_clarification",
  "candidates": [...]}` — the same candidate shape as above. Note this
  response has **no** `attrition` key, so check for `status` first.
- Unknown employee → HTTP 404 `{"detail": "Employee was not found."}`
- Neither identifier supplied → HTTP 400.

---

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

### `POST /pipeline/replacement`

Rank internal successor candidates for an employee. Deterministic scoring —
no LLM by default, so this is fast.

**Request** — `employee_id` only; a name is not accepted here.

```json
{ "employee_id": "EMP001" }
```

**Response:**

```json
{
  "status": "completed",
  "target_employee_id": "EMP001",
  "recommended_successors": [
    {
      "rank": 1,
      "employee_id": "EMP087",
      "employee_name": "Kashif Hameed",
      "current_position": "HR Manager",
      "final_score": 98.14,
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
  `"Ready in 6-12 Months"`. Treat both as open-ended strings and style with
  a fallback rather than a hard switch.
- `reasons` is a list of complete, display-ready sentences — render as-is.
- **Show the `disclaimer`.** It is returned deliberately.

**Other outcomes:**

- No suitable candidates → HTTP 200, `{"status": "no_candidates",
  "employee_id": "...", "recommended_successors": [], "message": "..."}`.
  Handle this as an empty state, not an error.
- Bad or ambiguous ID → HTTP 400, with the detail object in `detail`.
- Internal failure → HTTP 500.

---

### `POST /chat` — the HR agent

One message in, one reply out. The agent decides on its own whether to check
attrition risk or recommend successors, and remembers the employee under
discussion for the rest of the thread. It answers in the user's language.

**Request:**

```json
{ "message": "What is the attrition risk for EMP021?", "thread_id": null }
```

- `message` — required, non-empty.
- `thread_id` — omit or `null` on the first message. The server generates
  one and returns it. **Send that same value on every later message** to
  continue the conversation; a new `thread_id` means the agent has forgotten
  everything.

**Response:**

```json
{
  "thread_id": "931124c0-549e-4dd2-bfc2-f90875655362",
  "reply": "The attrition model indicates risk for Usman Khan (EMP021), Customer Support Representative in Customer Support. The contributing factors identified are current salary level, salary competitiveness against the market, and the most recent salary increment. …",
  "selected_employee_id": "EMP021",
  "selected_employee_name": "Usman Khan",
  "last_tool_status": "completed",
  "elapsed_ms": 59623
}
```

- `reply` is Markdown — the agent uses `**bold**` and numbered lists. Render
  it through a Markdown component, or the asterisks show up literally.
- `selected_employee_id` / `selected_employee_name` are the agent's current
  context. Useful for an "actively discussing …" chip. Both can be `null`
  before an employee is chosen.
- `elapsed_ms` is the server-side round trip — handy for a debug overlay.
- That `59623` above is real. Size your loading state for a full minute.

**Errors:** HTTP 502 with `{"detail": "..."}` when the agent fails or returns
empty. The detail text is safe to display. This happens occasionally on the
free model — offer a retry button rather than treating it as fatal.

---

### `POST /chat/stream` — the same agent, streamed

Identical request body and conversation semantics as `/chat`. Returns
**Server-Sent Events** (`text/event-stream`). Strongly preferred for chat UI.

Each line is `data: {json}` followed by a blank line. Five event types:

| `type` | Payload | What to do |
|---|---|---|
| `meta` | `thread_id` | Arrives immediately. Store the id at once. |
| `status` | `text` | A tool started, e.g. `"Finding successor candidates..."`. Show as a transient status line. |
| `token` | `text` | A fragment of the answer. **Append verbatim.** |
| `done` | `thread_id`, `selected_employee_id`, `selected_employee_name`, `last_tool_status`, `elapsed_ms` | Turn finished. Same fields as `/chat`. |
| `error` | `message` | Turn failed. Display `message`, stop the stream. |

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
- Tokens split mid-word (`"E"`, `"MP"`, `"0"`, `"0"`, `"1"` → `EMP001`).
  Never parse a partial buffer — only the accumulated string is meaningful.
- Because the answer is Markdown, re-render the **whole accumulated string**
  through your Markdown component on each token, rather than appending
  rendered HTML.
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

## 4. Error handling summary

| Code | Meaning | Frontend behaviour |
|---|---|---|
| 200 | Success — **but check the `status` field** on search and replacement | Branch on `status` |
| 400 | Missing/invalid input | Fix the request; show a form error |
| 404 | Employee not found (attrition pipeline) | Empty state |
| 500 | Internal failure in the successor graph | Generic error + retry |
| 502 | Agent failed or returned empty | Show `detail`, offer retry |

Every error body is FastAPI's standard shape:

```json
{ "detail": "Provide employee_id or employee_name." }
```

`detail` is usually a string, but on `/pipeline/replacement` it can be an
**object**. Check the type before rendering it:

```js
const message = typeof body.detail === "string"
  ? body.detail
  : body.detail?.message ?? "Something went wrong.";
```

---

## 5. Gotchas worth repeating

1. **HTTP 200 does not mean success.** `not_found` and
   `needs_clarification` both arrive as 200. Always read `status`.
2. **Numbers inside `records` are strings.** `"140"`, not `140`.
3. **`attrition` is `"Yes"`/`"No"`, not a boolean**, and carries no
   probability.
4. **`top_reasons` are raw feature names** needing a display-name map, and
   are often empty.
5. **Chat can take a minute.** Do not set a short timeout.
6. **Never trim or space-join stream tokens.**
7. **Agent replies are Markdown.** Render them as such.
8. **Reuse `thread_id`** or the agent loses all memory.
9. **No auth** — do not build a login against this API; it has none.

---

## 6. Quick local start

```bat
python app.py
```

Serves on `http://127.0.0.1:8000`; open `/docs` to try any endpoint by hand
before wiring it up. Verify the connection with:

```bash
curl http://127.0.0.1:8000/health
```
