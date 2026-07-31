# HR Workforce Intelligence Backend

Employee search, CatBoost attrition prediction, internal successor
recommendations, and a multilingual HR reasoning agent — behind one FastAPI
application.

## Run it

```bat
pip install -r requirements.txt
python app.py
```

Swagger UI: <http://127.0.0.1:8000/docs>

`uvicorn app:app --reload` works too.

## Structure

```
Attrition_Project/
├── .env                  <- the ONLY configuration file
├── app.py                <- the ONLY entry point
├── requirements.txt
├── README.md
│
├── Data/                 <- shared CSVs (attrition + successor workflows)
├── models/               <- catboost_attrition_model.cbm
├── notebooks/            <- EDA and model-training notebooks
│
├── backend/
│   ├── paths.py                     <- resolves every path from .env
│   ├── settings.py                  <- resolves every LLM setting from .env
│   ├── employee_record_tool.py      <- employee search over the CSVs
│   ├── attrition_prediction_tool.py <- CatBoost model wrapper
│   ├── replacement_tool.py          <- calls the local successor graph
│   ├── agent_prompts.py             <- agent system prompt
│   ├── agent_state.py               <- per-conversation state schema
│   ├── agent_tools.py               <- state-aware tools for the agent
│   ├── hr_agent.py                  <- the HR reasoning agent
│   └── successor_service/           <- successor recommendation LangGraph
│       ├── bootstrap.py             <- builds and caches the graph
│       ├── config.py                <- successor settings
│       ├── graph/                   <- LangGraph nodes and state
│       ├── repositories/            <- CSV loading
│       ├── services/                <- feature building, scoring, ranking
│       ├── tools/                   <- resolver, position, candidates
│       ├── agents/                  <- successor reasoning agent
│       └── resources/               <- scoring_config.json
│
└── tests/                <- runnable end-to-end scripts
```

Every file above is reachable from `app.py`. There is no dead code and no
second copy of anything.

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/health` | Loaded components, resolved paths, active LLM settings |
| POST | `/tools/employee-search` | Resolve one employee record |
| POST | `/tools/attrition-predict` | Run CatBoost on a search result |
| POST | `/pipeline/attrition` | Search + predict in one call |
| POST | `/pipeline/replacement` | Rank internal successors |
| POST | `/chat` | Talk to the multilingual HR agent |
| POST | `/chat/stream` | Same, streamed token by token (SSE) |

`/chat` takes `{"message": "...", "thread_id": "..."}`. Omit `thread_id` on
the first message and reuse the returned one to continue — the agent
remembers the selected employee across turns, so "yes, show replacements"
works without repeating the ID. The response includes `elapsed_ms` so a slow
turn can be attributed without guessing.

`/chat/stream` takes the same body and emits server-sent events. Use it for
any real UI: the complete answer takes the same time either way, but the
user starts reading in ~1–3 s instead of watching a blank screen.

| `type` | Meaning |
| --- | --- |
| `meta` | `thread_id`, sent immediately |
| `status` | A tool started, e.g. "Checking attrition risk..." — show it |
| `token` | A fragment of the answer; append it verbatim |
| `done` | Final employee context and `elapsed_ms` |
| `error` | The turn failed; `message` is safe to display |

```js
const res = await fetch("/chat/stream", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ message: "Is EMP004 at risk?", thread_id }),
});

for await (const chunk of res.body.pipeThrough(new TextDecoderStream())) {
  for (const line of chunk.split("\n")) {
    if (!line.startsWith("data: ")) continue;
    const e = JSON.parse(line.slice(6));
    if (e.type === "status") showSpinner(e.text);
    if (e.type === "token") appendToReply(e.text);   // append, do not trim
    if (e.type === "done") thread_id = e.thread_id;
  }
}
```

## Configuration

Everything lives in `.env` at the repository root. Nothing is hardcoded:
**the model the agent uses comes only from `OPENROUTER_MODEL`**, and a
missing key or model fails at startup with a clear message rather than
silently falling back.

| Key | Meaning |
| --- | --- |
| `OPENROUTER_API_KEY` | **Required.** OpenRouter key |
| `OPENROUTER_MODEL` | **Required.** Model id, e.g. `openai/gpt-oss-20b:free` |
| `OPENROUTER_BASE_URL` | OpenRouter API base URL |
| `OPENROUTER_TEMPERATURE` | `0` keeps answers and tool choice stable |
| `OPENROUTER_MAX_TOKENS` | Must be ≥ ~800 or successor answers get cut off |
| `OPENROUTER_MAX_RETRIES` | Retries for transient free-model errors |
| `OPENROUTER_TIMEOUT_SECONDS` | Per-request timeout |
| `OPENROUTER_REASONING` | `off` disables chain-of-thought — see below |
| `DATA_DIR` | Shared CSV folder (relative to repo root, or absolute) |
| `MODEL_PATH` | Saved CatBoost model |
| `SUCCESSOR_LLM_ENABLED` | `false` uses fast deterministic successor reasons |
| `APP_HOST` / `APP_PORT` | Server bind address |

Check what is actually in effect with `GET /health`.

## Response time

The HR tools are not the bottleneck — employee search, the CatBoost
prediction, and the successor graph each run in **under 0.06 s**. Effectively
all latency is the language model.

Three things keep it down, and all three are already applied:

- **`OPENROUTER_REASONING=off`.** Reasoning models emit a long internal
  monologue before answering, generated one token at a time, twice per turn
  (once to pick the tool, once to write the reply). Measured on this
  workload: **10.5 s → 1.8 s** per model call, 407 → 95 generated tokens.
  This agent routes to a tool and fills a fixed answer shape, so it gains
  nothing from deliberation. Set it to `low` or `on` only if you change the
  agent to do open-ended analysis.
- **A short system prompt.** Every rule costs prompt tokens on every call
  and dilutes the model's attention. `agent_prompts.py` is deliberately
  terse; adding restatements of existing rules makes the agent slower *and*
  less obedient. Verified: at ~4,500 prompt tokens it began skipping tool
  calls and ignoring formatting rules that it followed at ~2,700.
- **Short retry backoff** in `resilient_model.py`, so recovering from a busy
  provider worker costs ~4 s rather than ~10 s.

What remains is queueing on the free OpenRouter endpoint, which no code
change can fix: a `:free` model shares one pool with every other user, so
replies range from ~3 s to ~30 s and some requests fail with
`Worker local total request limit reached`. `/chat` retries those
automatically and returns a clear 502 if they still fail. Switching
`OPENROUTER_MODEL` to a paid model removes the variance.

## Tests

```bat
python tests/test_replacement_tool.py     :: successor graph, no LLM
python tests/test_hr_agent.py             :: agent, attrition + memory
python tests/test_combined_hr_agent.py    :: agent, attrition + replacement
```


## Deploying to Render (GitHub-connected)

The repo ships a `Dockerfile` and a `render.yaml` blueprint, so Render builds
and runs the same image used locally. No `.env` file is deployed — Render
injects the configuration as real environment variables, and `settings.py`
loads `.env` with `override=False`, so the platform values win.

1. Push this repo to GitHub:

   ```bat
   git remote add origin https://github.com/<user>/<repo>.git
   git push -u origin main
   ```

2. In Render: **New > Blueprint**, connect the GitHub repo, and pick the
   branch. Render reads `render.yaml` and creates the web service.

3. Set the one secret it cannot read from the repo — `OPENROUTER_API_KEY` —
   in the service's **Environment** tab. Every other variable is already
   declared in `render.yaml`; change a model or timeout there and redeploy.

4. Render sets `PORT`; the container's `CMD` binds `0.0.0.0:${PORT}`.
   Health checks hit `/health`, and Swagger UI is at `<service-url>/docs`.

`autoDeploy: true` means each push to the connected branch redeploys.

Notes:

- The CSVs in `Data/` and the CatBoost model in `models/` are committed
  (~550 KB total) and baked into the image, so the service needs no disk.
- On Render's free plan the service sleeps when idle; the first request
  after a sleep pays a cold start on top of the usual OpenRouter latency.
