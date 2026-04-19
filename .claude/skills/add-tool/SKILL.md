---
name: add-tool
description: Scaffold a new `@tool` for the GenBI agent — adds the `_impl` + `@tool` wrapper in src/genbi/tools.py, registers it on the SDK MCP server and the standalone MCP, and writes a happy-path + failure-mode test. Use when a user question genuinely needs a new capability beyond schema_introspect / sql_execute / chart_render.
allowed-tools: Read, Edit, Bash(uv run:*)
---

# /add-tool

Grow the agent's tool surface with a single invocation. Every new tool has to land in **four** places (impl, in-process MCP registration, standalone MCP mirror, tests) — this skill orchestrates the edits so nothing drifts.

## Runbook

1. **Read the anchors.** `Read` all four before touching anything:
   - [src/genbi/tools.py](src/genbi/tools.py) — existing `_*_impl` + `@tool(...)` pattern.
   - [src/genbi/agent.py](src/genbi/agent.py) — `create_sdk_mcp_server(tools=[...])` call and `allowed_tools=[...]` allow-list.
   - [mcp_servers/postgres_readonly.py](mcp_servers/postgres_readonly.py) — `TOOLS: list[mcp_types.Tool]` + `IMPLS` dict + the import line from `genbi.tools`.
   - [tests/test_tools.py](tests/test_tools.py) — happy-path / safety-failure test style.
2. **Gather the fields** from the user. If the invocation already supplies them, skip the prompts; otherwise ask in order:
   - `name`: lowercase_with_underscores (required). Must not collide with an existing tool.
   - `description`: one-sentence summary (required) — the LLM reads this to decide when to call the tool.
   - `input_schema`: dict of `{arg_name: python_type}` using the SDK's shorthand (e.g. `{"sql": str, "limit": int}`). Empty dict `{}` if no args.
   - `returns_payload`: short description of the JSON payload shape (used for the test + optionally the UI branch).
   - `runs_sql`: yes/no. If yes, the impl **must** go through `genbi.safety.validate_and_prepare` (see step 4).
   - `renders_in_ui`: yes/no. If yes, the payload needs a branch in `src/genbi/ui/render.py` — see step 7.
3. **Validate.**
   - Stop and ask if `name` matches an existing tool in [src/genbi/tools.py](src/genbi/tools.py) or the `allowed_tools` list in [src/genbi/agent.py](src/genbi/agent.py).
   - Stop and ask if `name` isn't lowercase_with_underscores — MCP naming conventions downstream (`mcp__genbi__<name>`) assume that shape.
   - Stop and ask if `runs_sql=yes` but the impl draft doesn't reference `validate_and_prepare` or `_run_select` — never build raw SQL with f-strings or `%`-format.
4. **Add the impl + wrapper** to [src/genbi/tools.py](src/genbi/tools.py):
   - Define `async def _<name>_impl(args: dict[str, Any]) -> dict[str, Any]:` returning the raw payload dict.
   - If SQL: call `_run_select(args["sql"])` — it already handles validator + statement_timeout + LIMIT.
   - If not SQL: use `get_engine().connect()` for read-only work; never import from `genbi.seed`.
   - Add the `@tool("<name>", "<description>", <schema>)` decorator over `async def <name>(args) -> dict[str, Any]: return _as_content(await _<name>_impl(args))`.
   - Mirror the two-stage split the existing three tools use — the impl is framework-agnostic so the standalone MCP can reuse it.
5. **Register on the in-process SDK MCP** in [src/genbi/agent.py](src/genbi/agent.py):
   - Extend `tools=[...]` in the `create_sdk_mcp_server(...)` call with the new `<name>` function.
   - Extend `allowed_tools=[...]` in `OPTIONS` with `"mcp__genbi__<name>"`.
   - Update [SYSTEM_PROMPT](src/genbi/agent.py) if the new tool changes the workflow (e.g. a new "if the user asks for X, call `<name>` instead of `sql_execute`" bullet). Do **not** rewrite the whole prompt — add one bullet in the relevant numbered step.
6. **Mirror on the standalone MCP** in [mcp_servers/postgres_readonly.py](mcp_servers/postgres_readonly.py):
   - Add `_<name>_impl` to the import line from `genbi.tools`.
   - Append a `mcp_types.Tool(name=..., description=..., inputSchema=...)` entry to `TOOLS` with the JSON-schema version of the input schema (`{"type": "object", "properties": {...}, "required": [...], "additionalProperties": False}`).
   - Add `"<name>": _<name>_impl` to the `IMPLS` dict.
7. **(Conditional) Extend the UI renderer** at [src/genbi/ui/render.py](src/genbi/ui/render.py):
   - Only if `renders_in_ui=yes`. Add a new branch in `render_result_in_chat(payload, ...)` that checks for the payload's signature key (e.g. `"plotly_json"`, `"row_count"`) and renders the widget. Also add a summary row to `render_tool_result(event)` so the sidebar trace stays informative.
   - Both live-drain and replay paths go through this function — there's one right place for the branch.
8. **Write tests** in [tests/test_tools.py](tests/test_tools.py):
   - Happy path: call `<name>.handler({...})`, unwrap via the existing `_payload(result)` helper, assert the expected payload keys + at least one value-shape check.
   - Failure mode: either a `SafetyError` on bad SQL (for SQL tools) or a `ValueError` on bad input (for validated enums / ranges). Mirror the style of `TestSqlExecuteSafety` or `TestChartRender.test_unknown_chart_type_rejected`.
   - Keep the test inside a new `Test<CamelName>` class adjacent to the others — alphabetical order isn't required, read-order is.
9. **Format + test.** Run in this order:
   - `uv run ruff format . && uv run ruff check --fix .`
   - `uv run pytest -q tests/test_tools.py`
   - If pytest fails with `OperationalError`, the fixture skipped — remind the user to `docker compose up -d postgres && uv run python -m genbi.seed` and rerun.
10. **Regression check.** `uv run python -m evals.run_evals` (or `/run-eval`) to confirm the new tool didn't perturb existing cases. If pass-rate dips, the likely cause is the agent preferring the new tool over `sql_execute` for old questions — tighten the tool's description in step 4 and rerun.

## Scope guardrails

- **Never bypass `validate_and_prepare` for SQL.** If the new tool needs SQL, route through `_run_select` or call `validate_and_prepare` directly. The read-only role is belt; the validator is suspenders.
- **Never rename or delete existing tools.** Eval cases in [evals/questions.yaml](evals/questions.yaml), the standalone MCP's `TOOLS` list, and the baseline in `.eval-baseline.json` all reference the current three by name. Add, don't mutate.
- **Keep the impl framework-agnostic.** `_<name>_impl` returns a plain dict. Only the `@tool` wrapper shapes it into the MCP content envelope via `_as_content(...)`. The standalone MCP does its own envelope in [mcp_servers/postgres_readonly.py](mcp_servers/postgres_readonly.py) — keep both paths thin.
- **Don't add a write tool.** The `genbi_reader` role has no write grants; any impl that tries `INSERT|UPDATE|DELETE|DDL` will be rejected at the DB layer anyway. If a genuine write tool is ever needed, it goes in a separate PR with a called-out safety-rail relaxation (see [CLAUDE.md](CLAUDE.md)).
- **One tool per invocation.** If the request implies multiple tools, stop and ask the author to split — a shared impl + two thin wrappers is fine, but the skill's four-file edit discipline falls over with batching.
- **If any `Edit` anchor is ambiguous** (e.g. the `tools=[...]` list already spans multiple lines in a way your pattern can't match), `Read` the file again and widen the anchor. Never `Write` the whole file from scratch just to extend a list.
