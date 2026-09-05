# Live Engine Spike: PydanticAI vs direct OpenAI SDK vs stdlib urllib

Date: 2026-09-05 · Scope: research spike only, no generator/template changes
Context: `unroll --live` replays a traced agent loop against a real model endpoint.
Runtime deps today: **none** (`pyproject` `dependencies = []`). Python ≥ 3.12.

## Options compared

### A. PydanticAI (`pydantic_ai.Agent` + `agent.iter`)

```python
from pydantic_ai import Agent

agent = Agent(model="openai:gpt-4o", tools=[search, fetch])
async with agent.iter(user_message, message_history=history) as run:
    async for node in run:
        if agent.is_model_request_node(node):
            async with node.stream(run.ctx) as stream:
                ...  # incremental text / thinking
        elif agent.is_tool_call_node(node):
            result = await node.run_tool_calls(...)  # validation + retries built in
```

Pros: typed tool validation, retries, streaming/observability, provider abstraction.
Cons: **new hard dep** (`pydantic-ai` + `pydantic`), version churn, hides the raw
`messages[]`/`tools[]` wire format we are trying to make reproducible, harder to
emit a byte-faithful replay program.

### B. Direct `openai` SDK (RECOMMENDED default)

```python
from openai import OpenAI

client = OpenAI(base_url=base_url, api_key=api_key)  # OpenAI-compat endpoint
resp = client.chat.completions.create(
    model=model, messages=messages, tools=TOOL_SCHEMAS,
    tool_choice="auto", temperature=0.0,
)
msg = resp.choices[0].message
for call in msg.tool_calls or []:
    result = dispatch(call.function.name, json.loads(call.function.arguments))
    messages += [asst_msg(msg), tool_result_msg(call.id, result)]
```

Pros: one obvious call maps 1:1 onto the trace (`messages`, `tools=TOOL_SCHEMAS`);
works against any OpenAI-compatible base_url (Hermes gateway, vLLM, Ollama);
easy to template into generated programs; small dep (`openai` only at live-run time).
Cons: extra dep vs stdlib (but optional/lazy-imported); manual tool-dispatch loop.

### C. Stdlib `urllib` fallback (zero-dep)

```python
import json, os, urllib.request
from pathlib import Path

def load_api_key() -> str:
    for var in ("OPENAI_API_KEY", "HERMES_API_KEY"):
        if os.environ.get(var):
            return os.environ[var]
    env_file = Path.home() / ".hermes" / ".env"  # KEY=VALUE lines
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            k, _, v = line.partition("=")
            if k.strip() in ("OPENAI_API_KEY", "HERMES_API_KEY") and v.strip():
                return v.strip().strip("'\"")
    raise SystemExit("no API key: set OPENAI_API_KEY/HERMES_API_KEY or ~/.hermes/.env")

req = urllib.request.Request(
    f"{base_url}/chat/completions",
    data=json.dumps({"model": m, "messages": msgs, "tools": TOOL_SCHEMAS}).encode(),
    headers={"Authorization": f"Bearer {load_api_key()}", "Content-Type": "application/json"},
)
body = json.load(urllib.request.urlopen(req, timeout=60))
```

Pros: **zero dependencies**, always available, no install friction for replay.
Cons: verbose, manual error/streaming handling, no connection pooling/retries —
acceptable for a fallback path only.

## Decision

- **Default engine: direct `openai` SDK, lazily imported** (`OpenAI(base_url, api_key)` +
  `chat.completions.create(messages, tools=TOOL_SCHEMAS)`). Keeps generated `--live`
  programs short, readable, and portable across OpenAI-compatible endpoints.
- **PydanticAI optional** behind `--engine pydantic` (opt-in extra, never default).
  Justified only when the user wants typed validation / managed tool loop.
- **`urllib` fallback** when `openai` is not installed: same request shape, key read
  order `OPENAI_API_KEY` → `HERMES_API_KEY` → `~/.hermes/.env`, clear error otherwise.
- `pyproject` runtime deps stay `[]`; both live paths are lazy imports.

## Engine selection sketch

```python
def run_live(messages, model, base_url, api_key, engine="openai"):
    if engine == "pydantic":
        from pydantic_ai import Agent  # opt-in extra
        return run_pydantic(messages, model)
    try:
        from openai import OpenAI  # default zero-dep-install path
        return run_openai_sdk(messages, model, base_url, api_key)
    except ImportError:
        return run_urllib(messages, model, base_url, api_key)  # fallback
```

## Verification

- [x] `pyproject` runtime `dependencies = []` confirmed (this spike adds no deps).
- [x] Python floor 3.12 (`requires-python = ">=3.12"`).
- [x] No generator/template code touched by this spike.
