# Project conventions — Talk-to-Your-Data GenBI PoC

A natural-language → SQL → chart/table/summary chat over Postgres. Built as a Claude Code AI adoption training deliverable.

## Stack

- **Python 3.12** + **uv** for env/deps
- **PostgreSQL 16** with **pgvector** in Docker (`pgvector/pgvector:pg16`, port **5433**)
- **`claude-agent-sdk`** for the agent runtime
- **SQLAlchemy 2.x** + `psycopg[binary]` (sync) + **sqlglot** for SQL safety
- **Streamlit** + **Plotly** for the UI
- **Faker** for synthetic data; **pydantic v2** for schemas
- **Ollama** (local) + **httpx** for KB embeddings (`nomic-embed-text`, 768 dims)
- **ruff** (format + lint), **pytest**

## Commands

```bash
cp .env.example .env               # fill ANTHROPIC_API_KEY before first run
docker compose up -d postgres      # start Postgres (pgvector image)
uv sync --all-extras               # install runtime + ui + dev
uv run python -m genbi.seed        # wipe + reseed synthetic data
ollama pull nomic-embed-text       # one-time, for kb_search
uv run python -m genbi.seed_kb     # populate kb_chunks from kb/*.md
uv run python -m genbi.cli chat    # terminal chat against the DB
uv run streamlit run app/streamlit_app.py  # Streamlit UI
uv run python -m evals.run_evals   # eval suite — prefer /run-eval
uv run pytest -q                   # run tests
uv run ruff format . && uv run ruff check --fix .
```

Skills expose the common workflows as slash commands — prefer `/seed-data`, `/run-eval`, `/pr-prep`, `/add-tool`, `/new-question` over raw CLI invocations.

Any Claude session opened in this repo auto-loads the standalone `postgres-readonly` MCP via `.mcp.json` — `/mcp` lists `schema_introspect`, `sql_execute`, `chart_render`, `ask_user`, `kb_search` side-by-side with the in-process tool surface.

## Knowledge base (RAG)

Business glossary lives as markdown under `kb/` (`glossary.md`, `metrics.md`, `ops_runbook.md`). Each `## H2` is one chunk. `genbi.seed_kb` chunks the corpus, embeds each chunk via Ollama (`nomic-embed-text`, 768 dims), and writes to the `kb_chunks` table — hidden from `schema_introspect` so the agent only reaches it through `kb_search`. The tool degrades gracefully when Ollama is unreachable (returns `{error, snippets: []}`); the agent then proceeds without RAG context.

## Safety rails (non-negotiable)

1. **Three DB roles.** `genbi_admin` (write) is used only by `src/genbi/seed.py` and `src/genbi/seed_kb.py`. The agent, evals, CLI, MCP, and the app's read paths connect through `READONLY_DATABASE_URL` as `genbi_reader` (`USAGE` on `public`, `SELECT` on tables — no write grants). The Streamlit ingest path in `src/genbi/kb_ingest.py` connects through `KB_WRITER_DATABASE_URL` as `genbi_kb_writer`, which has `USAGE` on `public` and `SELECT/INSERT/DELETE` on `kb_chunks` only — plus `USAGE/SELECT` on its sequence. No `ALTER DEFAULT PRIVILEGES` is granted to the writer, so it cannot gain rights on tables added later.
2. **SQL validator.** `src/genbi/safety.py` parses every generated statement with `sqlglot` and rejects anything that isn't a single `SELECT` / `WITH ... SELECT`. Strips trailing semicolons. Blocks `INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|GRANT|TRUNCATE|COPY`.
3. **Query limits.** `SET LOCAL statement_timeout = '5s'` per query; `LIMIT 1000` appended if missing.
4. **No secrets in code.** Connection strings and `ANTHROPIC_API_KEY` live in `.env` (git-ignored); `.env.example` is the canonical template.

Any change that relaxes these rails must be called out in the PR description.

## Code conventions

- Source layout: `src/genbi/` is the Python package; `app/` is Streamlit only; `evals/` is the regression suite; `mcp_servers/` holds standalone MCPs.
- `src/genbi/events.py` is the structured-event boundary — the agent emits typed events consumed by both the UI (`ui/render.py`) and the eval runner. Extend the event schema there rather than inventing ad-hoc dicts per call site.
- Prefer async (`ClaudeSDKClient`) for the agent; keep DB code sync (SQLAlchemy) — don't mix.
- Type-hint all public functions. Use pydantic models for any structured data crossing a tool or API boundary.
- Don't catch `Exception` broadly — let Postgres / validator errors surface to the agent so it can retry.
- Tests go in `tests/`, named `test_<module>.py`. Integration tests that need Postgres assume `docker compose up` has run.
- Streamlit reruns the script on every interaction; the `ClaudeSDKClient` lives on a background thread via `src/genbi/ui/runtime.py` so conversation memory survives reruns. Don't instantiate the client inside a Streamlit callback.

## Model defaults

- **`claude-sonnet-4-6`** for the runtime agent and all subagents.
- CI workflows pin models explicitly in `claude_args`; never rely on implicit defaults there.

## How to add a tool

1. Add a new `@tool` function in `src/genbi/tools.py` with a clear docstring (the LLM reads it).
2. Register it on the SDK MCP server in `src/genbi/agent.py` and allow-list it in `ClaudeAgentOptions.allowed_tools`.
3. Add a unit test in `tests/test_tools.py` covering the happy path and at least one failure mode.
4. If it runs SQL, route through `src/genbi/safety.py` — never build raw strings. The single exception is `kb_search`, whose vector-search SQL is hardcoded in `src/genbi/kb.py` with bound parameters; the read-only role is the only safety layer.
5. If it returns a structured payload the UI should render (tables, `plotly_json` from `chart_render`, etc.), extend `src/genbi/ui/render.py` so both live-drain and replay paths render it consistently.
6. Run `/run-eval` to confirm no regressions.

The `/add-tool` skill automates steps 1–3 — use it.

## Meta-tooling map

- **Skills** (`.claude/skills/`): `seed-data`, `pr-prep`, `run-eval`, `new-question`, `add-tool`.
- **Subagents** (`.claude/agents/`): `developer`, `code-reviewer`, `test-writer`, `docs-writer`, `sql-reviewer`.
- **Hooks** (`.claude/settings.json` → `.claude/hooks/`): `lint-and-format.sh` (ruff) on `Write|Edit`, `docs-drift.sh` (advisory `docs-writer`) on `Write|Edit` of `tools.py` / `agent.py` / `pyproject.toml`, `advisory-review.sh` (advisory `code-reviewer`) on `git commit`, `pytest-quick.sh` (`pytest -q`) on `Stop`.
- **MCP** (`.mcp.json`): standalone `postgres-readonly` stdio server — extracted from the in-process `@tool` surface; any Claude session in this repo picks up the three tools via `/mcp`.
- **CI** (`.github/workflows/`): `claude-review.yml`, `eval-regression.yml` live gate, `nightly-doc-sync.yml`, `issue-to-pr.yml`.

## Naming conventions

### Commits — Conventional Commits
```
<type>(<scope>): <short summary>
```
- **Types:** `feat` · `fix` · `chore` · `ci` · `docs` · `test` · `refactor` · `perf`
- **Scopes:** `agent` · `tools` · `ui` · `evals` · `ci` · `skills` · `agents` · `docs` · `db` · `safety`
- Keep the summary under 72 characters, lowercase, no trailing period.
- Examples: `feat(tools): add chart_render pdf export`, `fix(ui): capitalize chat input placeholder`

### Branches
```
<type>/<short-kebab-description>
```
- Mirror the commit type: `feat/`, `fix/`, `chore/`, `ci/`, `docs/`, `test/`
- Keep it short (3–5 words max). Examples: `fix/chat-input-placeholder`, `feat/csv-export`, `chore/update-deps`

### Issues
- Title: imperative sentence, sentence-case. Example: `Add CSV export to chart results`
- Label `claude-implement` to trigger the `issue-to-pr` workflow.

### PRs
- Title mirrors the primary commit: `<type>(<scope>): <summary>` — same 72-char, lowercase rule.
- Body must include a `## Summary` bullet list and a `## Test plan` checklist.
- Draft PRs for in-progress work; mark ready-for-review only when CI is green.

## What not to do

- Don't hit the DB with `genbi_admin` from anywhere but `seed.py`.
- Don't build SQL with f-strings or `%`-formatting — use SQLAlchemy parameters.
- Don't let subagents write data. They can read, plan, and propose — a human merges.
