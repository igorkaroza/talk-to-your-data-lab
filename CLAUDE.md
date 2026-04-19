# Project conventions — Talk-to-Your-Data GenBI PoC

A natural-language → SQL → chart/table/summary chat over Postgres. Built as a Claude Code AI adoption training deliverable. Full plan: [PLAN.md](PLAN.md).

## Stack

- **Python 3.12** + **uv** for env/deps
- **PostgreSQL 16** in Docker (`docker-compose.yml`) on port **5433**
- **`claude-agent-sdk`** for the agent runtime
- **SQLAlchemy 2.x** + `psycopg[binary]` (sync) + **sqlglot** for SQL safety
- **Streamlit** + **Plotly** for the UI (lands in M3)
- **Faker** for synthetic data; **pydantic v2** for schemas
- **ruff** (format + lint), **pytest**

## Commands

```bash
docker compose up -d postgres      # start Postgres
uv sync --all-extras               # install runtime + ui + dev
uv run python -m genbi.seed        # wipe + reseed synthetic data
uv run python -m genbi.cli chat    # terminal chat against the DB (M2+)
uv run streamlit run app/streamlit_app.py  # M3+
uv run python -m evals.run_evals   # eval suite (M4+) — prefer /run-eval
uv run pytest -q                   # run tests
uv run ruff format . && uv run ruff check --fix .
```

Skills also expose these as slash commands — prefer `/seed-data`, `/run-eval`, `/pr-prep` once they exist.

## Safety rails (non-negotiable)

1. **Two DB roles.** `genbi_admin` (write) is used only by `src/genbi/seed.py`. Everything else — agent tools, evals, app — connects through `READONLY_DATABASE_URL` as `genbi_reader`, which has `USAGE` on `public` and `SELECT` on tables. No write grants, ever.
2. **SQL validator.** `src/genbi/safety.py` parses every generated statement with `sqlglot` and rejects anything that isn't a single `SELECT` / `WITH ... SELECT`. Strips trailing semicolons. Blocks `INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|GRANT|TRUNCATE|COPY`.
3. **Query limits.** `SET LOCAL statement_timeout = '5s'` per query; `LIMIT 1000` appended if missing.
4. **No secrets in code.** Connection strings and `ANTHROPIC_API_KEY` live in `.env` (git-ignored); `.env.example` is the canonical template.

Any change that relaxes these rails must be called out in the PR description.

## Code conventions

- Source layout: `src/genbi/` is the Python package; `app/` is Streamlit only; `evals/` is the regression suite; `mcp_servers/` holds standalone MCPs.
- Prefer async (`ClaudeSDKClient`) for the agent; keep DB code sync (SQLAlchemy) — don't mix.
- Type-hint all public functions. Use pydantic models for any structured data crossing a tool or API boundary.
- Don't catch `Exception` broadly — let Postgres / validator errors surface to the agent so it can retry.
- Tests go in `tests/`, named `test_<module>.py`. Integration tests that need Postgres assume `docker compose up` has run.

## Model defaults

- **`claude-sonnet-4-6`** for the runtime agent and most subagents (including `chart-designer` — pattern-match task, not hard reasoning).
- **`claude-opus-4-7`** for hard-reasoning subagents: `code-reviewer`, `sql-reviewer`.
- CI workflows pin models explicitly in `claude_args`; never rely on implicit defaults there.

## How to add a tool

1. Add a new `@tool` function in `src/genbi/tools.py` with a clear docstring (the LLM reads it).
2. Register it on the SDK MCP server in `src/genbi/agent.py` and allow-list it in `ClaudeAgentOptions.allowed_tools`.
3. Add a unit test in `tests/test_tools.py` covering the happy path and at least one failure mode.
4. If it runs SQL, route through `src/genbi/safety.py` — never build raw strings.
5. If it returns a structured payload the UI should render (tables, `plotly_json` from `chart_render`, etc.), extend `src/genbi/ui/render.py` so both live-drain and replay paths render it consistently.
6. Run `/run-eval` to confirm no regressions.

The `/add-tool` skill automates steps 1–3 — use it.

## Meta-tooling map

- **Skills** (`.claude/skills/`): `seed-data` (M1), `pr-prep` (M3), `run-eval` + `new-question` + `triage` + `security-sweep` (M4), `add-tool` + `weekly-update` + `daily-standup` (M5).
- **Subagents** (`.claude/agents/`): `developer` + `code-reviewer` (M1), `test-writer` (M2), `docs-writer` (M3), `sql-reviewer` + `chart-designer` (M4), `release-notes` (M5); `schema-explorer` still planned.
- **Hooks** (`.claude/settings.json`): ruff on `Write|Edit`, advisory `docs-writer` drift check on `Write|Edit` of `tools.py` / `agent.py` / `pyproject.toml`, advisory `code-reviewer` on `git commit`, `pytest -q` on `Stop`.
- **MCP** (`.mcp.json`): standalone `postgres-readonly` stdio server (M4) — extracted from the in-process `@tool` surface; any Claude session in this repo picks up the three tools via `/mcp`.
- **CI** (`.github/workflows/`): `claude-review.yml` (M1), `eval-regression.yml` live gate (M4), `nightly-doc-sync.yml` (M4), `release-notes.yml` + `issue-to-pr.yml` (M5).

## What not to do

- Don't hit the DB with `genbi_admin` from anywhere but `seed.py`.
- Don't build SQL with f-strings or `%`-formatting — use SQLAlchemy parameters.
- Don't let subagents write data. They can read, plan, and propose — a human merges.
- Don't skip the weekly Friday update (`/weekly-update` → `docs/weekly-updates/NN.md`) even if the milestone slipped.
