# Talk-to-Your-Data GenBI PoC — Execution Plan

## Context

You own three Jira tasks for AI adoption training: (1) define a PoC concept over SQL data, (2) build it in weekly increments, (3) demo it in 5 minutes. The overarching goal is to **build a working app while learning Claude Code's full surface area** — skills, subagents, hooks, `CLAUDE.md`, MCP creation, and the Claude Agent SDK.

Your proposed app — a **"Talk-to-Your-Data" GenBI chat** that lets reporting teams and managers ask ad-hoc questions, visualize answers as charts/tables, and read auto-generated summaries — is a strong fit: it maps cleanly to the "chatbot over structured data" scope Jira asks for, it's demo-friendly for a non-technical audience, and it gives us natural surfaces to practice every Claude Code primitive.

## Reflection on the proposal

**Why it works**
- GenBI is a clean, focused narrative: *"ask English, get a chart + a number + a sentence."*
- SQL generation with `Claude Sonnet 4.6` is a proven strong-suit; demo should feel magical.
- Reporting/management audience (not developers) lets you highlight UX polish over technical depth.

**Risks / watch-outs**
- Schema complexity kills SQL accuracy — **keep the schema small (2–3 tables, ≤10 columns each)** and bias the synthetic data toward stories you can demo.
- "Live natural language → SQL" demos are fragile; we need a **curated eval set** to catch regressions each week and a few **hero questions** rehearsed for the final demo.
- Safety matters even in a PoC — a read-only role + SQL validator is cheap insurance and a good talking point.

**Suggested features (beyond your brief)**
1. **Agent trace panel** in the UI — show tool calls, generated SQL, and reasoning in a collapsible sidebar. Huge demo win; showcases the agent mental model.
2. **"Explain this chart"** button — one-click summarization over the current result set.
3. **Follow-up / drill-down** — multi-turn chat memory (`ClaudeSDKClient` handles this natively).
4. **CSV / PNG export** — cheap, but it's what reporting teams actually want.
5. **Hero questions dropdown** — pre-seeded examples so the demo never stalls on "what do I ask?"

## Locked scope (from clarifying questions)

| Decision | Choice |
|----------|--------|
| Dataset | **Retail sales + tickets** (two tables, synthetic via Faker) |
| UI | **Streamlit** (Python-native, fastest to charts+chat) |
| Data scope | **SQL-only** (no RAG; stays on-theme and on-schedule) |
| SDK | **Claude Agent SDK** (`claude-agent-sdk` on PyPI) |
| Models | `claude-sonnet-4-6` default; `claude-opus-4-7` for hard reasoning subagents |

## Architecture

```
┌────────────────────────────┐
│  Streamlit chat UI         │  app/streamlit_app.py
│  - Chat pane               │
│  - Chart/table area        │
│  - Agent trace sidebar     │
└──────────────┬─────────────┘
               │ async per-turn
┌──────────────▼─────────────┐
│  ClaudeSDKClient           │  src/genbi/agent.py
│  (Claude Agent SDK)        │
│                            │
│  System prompt: GenBI      │
│  Tools: @tool decorators   │
│  Subagents: AgentDefinition│
└───┬────────┬─────────┬─────┘
    │        │         │
    ▼        ▼         ▼
 schema_  sql_      chart_
 introspect execute  render
    │        │         │
    └────────┴─────────┘
             │
       ┌─────▼─────┐
       │ Postgres  │  docker-compose.yml
       │ read-only │  role: genbi_reader (SELECT only)
       │ role      │  statement_timeout=5s, LIMIT 1000
       └───────────┘
```

## Tech stack

- **Python 3.12**, **uv** for env/dependency management
- **PostgreSQL 16** via `docker-compose.yml`
- **`claude-agent-sdk`** (Python) — agent loop, `@tool`, `create_sdk_mcp_server`, `AgentDefinition`
- **SQLAlchemy 2.x** + **psycopg** (sync) for DB; **sqlglot** for SQL validation
- **Streamlit 1.40+** + **Plotly** for charts
- **Faker** for synthetic data; **pydantic v2** for schemas
- **pytest** + **ruff** (format + lint)

## Repo layout

```
.claude/
  skills/
    seed-data/SKILL.md          # regenerate synthetic data
    add-tool/SKILL.md           # scaffold a new @tool + register it
    run-eval/SKILL.md           # run eval suite, print pass/fail table
    new-question/SKILL.md       # add an eval case
    weekly-update/SKILL.md      # draft Jira weekly update from git log
  agents/
    sql-reviewer.md             # reviews generated SQL for correctness/safety
    schema-explorer.md          # summarizes Postgres schema in NL
    chart-designer.md           # picks Plotly chart type + encoding
  settings.json                 # hooks (ruff on save, pytest on stop) + permissions
.mcp.json                       # registers the postgres-readonly MCP (added in M4)
CLAUDE.md                       # project conventions — stack, commands, safety rules
docker-compose.yml
pyproject.toml                  # uv-managed
src/genbi/
  __init__.py
  agent.py                      # ClaudeSDKClient, system prompt, tool registration
  tools.py                      # @tool definitions (schema_introspect, sql_execute, chart_render)
  safety.py                     # SQL validator (sqlglot), SELECT-only enforcement
  db.py                         # engine + read-only role handling
  seed.py                       # Faker generators for sales + tickets
  schemas.py                    # pydantic: QueryRequest, ChartSpec, ...
app/
  streamlit_app.py              # chat UI entrypoint; agent trace sidebar
evals/
  questions.yaml                # 12–15 NL questions with expected shape
  run_evals.py                  # runs agent on each question, scores structurally
mcp_servers/
  postgres_readonly.py          # standalone stdio MCP (added in M4)
tests/
  test_safety.py                # SQL validator unit tests
  test_tools.py                 # tool happy-path tests against a test DB
docs/
  concept.md                    # Task 1 deliverable (3–5 min concept brief)
  demo-script.md                # Task 3 deliverable (5-min walkthrough)
  weekly-updates/               # 01.md, 02.md, … Task 2 deliverables
```

## Claude Code meta-tooling (the "learn CC" deliverable)

Each primitive is wired to a concrete job in this repo — **don't build meta-tooling for its own sake**, build it because the repo needs it and note what you learned.

### `CLAUDE.md` (project root)
Keep under ~150 lines. Sections: stack + versions, make/uv commands, **safety rails** (read-only DB, no DML, timeout, row cap), code conventions (ruff config, pytest layout), model defaults (Sonnet 4.6 for tools, Opus 4.7 for subagents), and a **"how to add a tool"** mini-runbook that points at the `add-tool` skill.

### Custom skills (`.claude/skills/<name>/SKILL.md`)
Each with YAML frontmatter (`name`, `description`, `allowed-tools`). All user-invocable via `/<name>`:
- **`seed-data`** — wipes + reseeds Postgres with fresh Faker data.
- **`add-tool`** — scaffolds a new `@tool` function in `src/genbi/tools.py` + registers it on the SDK MCP server.
- **`run-eval`** — runs `evals/run_evals.py`, prints a pass/fail matrix.
- **`new-question`** — appends an eval case to `evals/questions.yaml`.
- **`weekly-update`** — reads `git log` since last update and drafts a Jira-ready bullet summary into `docs/weekly-updates/NN.md`.

### Custom subagents (`.claude/agents/<name>.md`)
Three programmatic subagents exposed via `AgentDefinition` inside the runtime agent, **plus** the same three mirrored as file-based subagents for Claude Code-driven development:
- **`sql-reviewer`** — given SQL + schema, flags join correctness, NULL handling, cardinality risks. Called by `run-eval` and optionally at runtime before execution.
- **`schema-explorer`** — reads `information_schema`, writes a natural-language schema card. Called by `seed-data` after reseed.
- **`chart-designer`** — given a data shape + user intent, proposes chart type + encoding (returns a `ChartSpec`).

### Hooks (`.claude/settings.json`)
- `PostToolUse` matcher `Write|Edit` on `*.py` → `uv run ruff format` + `uv run ruff check --fix`.
- `PreToolUse` matcher `Bash` with `if: "Bash(rm -rf *)"` → deny.
- `Stop` → `uv run pytest -q` (no-op if no tests match changed files).

### Custom MCP server (`mcp_servers/postgres_readonly.py`, added in M4)
Standalone **stdio MCP** that wraps the read-only DB role and exposes `schema_introspect` + `sql_execute`. Registered in `.mcp.json`. Start as in-process `@tool` in M2, **extract to standalone MCP in M4** as the learning exercise — this way you feel the difference between in-process and out-of-process tools.

### Slash commands
Skills are already invokable as `/seed-data`, `/run-eval`, etc. No separate `commands/` folder needed.

## SDLC optimization with LLMs (training add-on)

The PoC app is only half the training deliverable — the other half is **showing how LLMs compress the inner dev loop and CI/CD**. Wire these in *as you build*, not as a separate phase, so they become the narrative of "how we shipped this in 5 weeks."

### Dev-loop subagents (`.claude/agents/`)
- **`developer`** — implements a feature end-to-end: reads `CLAUDE.md`, writes code following repo conventions, wires it in, runs tests. Invoked via the `Agent` tool for any "add a new tool / subagent / skill" task. Model: `sonnet`.
- **`code-reviewer`** — reviews staged diff / PR diff for correctness, **SQL-safety violations** (writes, missing `LIMIT`, injected params), style, and missing tests. Produces a Markdown report. Model: `opus` (quality > speed here).
- **`test-writer`** — given a function signature + behavior notes, writes pytest cases (happy path + edge cases + one negative). Paired with `developer` for TDD-style loops.
- **`docs-writer`** — keeps `CLAUDE.md`, `docs/concept.md`, `README.md` in sync with code. Detects drift between "how to add a tool" runbook and actual `src/genbi/tools.py` shape.
- **`release-notes`** — drafts release notes from `git log` + closed PRs.

### Dev-loop skills (`.claude/skills/`)
- **`/pr-prep`** — runs `ruff` + `pytest` + `/run-eval`, invokes `code-reviewer`, drafts PR title/body, pushes branch, opens PR via `gh`. One command replaces the pre-PR checklist.
- **`/triage`** — reads the latest failing CI run (`gh run view --log-failed`), drafts a fix plan or a fix-it PR directly.
- **`/daily-standup`** — yesterday's commits + today's plan from `git log` + open tasks. Useful for solo work; trivial to adapt for team standups.
- **`/security-sweep`** — runs `code-reviewer` with a SQL-safety + secrets lens across the repo. Use weekly as a regression guard.

### CI/CD with LLMs (`.github/workflows/`)
Primary option: the official **`anthropics/claude-code-action@v1`** GitHub Action, backed by `ANTHROPIC_API_KEY` in repo secrets. Fallback: a thin Python step that calls `claude-agent-sdk` headless — use this in `eval-regression.yml` because it needs DB access. *Verify the action ref in M1 since the GitHub Action API evolves.*

- **`claude-review.yml`** — on `pull_request`, posts an AI review as a PR comment covering correctness, SQL safety, and test coverage. Uses the `code-reviewer` subagent prompt.
- **`eval-regression.yml`** — on PR targeting `main`, spins up a Postgres service container, runs `evals/run_evals.py`, posts the pass/fail matrix as a PR comment, **fails the check if pass-rate drops >5% vs `main`**. This is the single most demo-worthy workflow — it turns the eval suite into a regression gate.
- **`nightly-doc-sync.yml`** — scheduled cron; runs `docs-writer`; opens an auto-PR if `CLAUDE.md` / `concept.md` have drifted. Keeps docs from rotting across a 5-week build.
- **`issue-to-pr.yml`** — on issues labeled `claude-implement` (or `@claude` mentions in comments), runs the `developer` subagent headless, pushes branch, opens a draft PR for human review. Perfect for the M5 "look, an issue became a PR" demo.
- **`release-notes.yml`** — on tag push, runs `release-notes` subagent, posts to GitHub Releases.

### Local hooks (complement CI — append to `.claude/settings.json`)
- `PreToolUse` matcher `Bash` with `if: "Bash(git commit *)"` → runs `code-reviewer` on staged diff; emits an **advisory** (exit 0), never blocks. So the developer sees the review but always has the final call.
- `PostToolUse` on `Write|Edit` for `src/genbi/tools.py` → invokes `docs-writer` to check the "how to add a tool" runbook in `CLAUDE.md`.
- `Stop` (already planned) → `pytest -q`.

### Cost & safety controls
- Default CI model: `claude-sonnet-4-6`. Escalate to `claude-opus-4-7` only for `nightly-doc-sync.yml` and `issue-to-pr.yml` (harder reasoning).
- Hard cap `max_turns`: 15 for review workflows, 40 for implementation workflows.
- `ANTHROPIC_API_KEY` scoped to a training budget; workflows log token usage to `.ci-metrics/run-<id>.json`. Weekly roll-up committed to `docs/sdlc-metrics.csv`.
- `gh` token for workflows: `GITHUB_TOKEN` with `pull-requests: write` + `issues: write`, nothing broader.

### Measurement (prove the win)
`docs/sdlc-metrics.csv` updated each Friday. Track:
- Time from concept → first working demo
- Median PR review cycle time (open → merged)
- Eval pass-rate trend (weekly snapshot)
- CI cost per PR (tokens × price)
- Human-overrides of `code-reviewer` findings (should trend down as prompts improve)

One slide in the final demo charts these — that's the "SDLC optimization with LLMs" payload.

### SDLC rollout by milestone
- **M1** — add `developer` + `code-reviewer` subagents; stand up `claude-review.yml`; add the `git commit` PreToolUse hook.
- **M2** — add `test-writer`; adopt a TDD loop (`test-writer` → `developer` → `code-reviewer`); stand up `eval-regression.yml` once evals exist in stub form.
- **M3** — add `/pr-prep` skill; add `docs-writer` + the `tools.py` PostToolUse hook; start logging `sdlc-metrics.csv`.
- **M4** — add `/triage` and `/security-sweep` skills; stand up `nightly-doc-sync.yml`; add `release-notes` subagent.
- **M5** — land `issue-to-pr.yml` as the headline SDLC demo; build the metrics slide for the final demo.

## Safety rails (non-negotiable)

1. **Dedicated Postgres role** `genbi_reader`: `GRANT USAGE ON SCHEMA public`, `GRANT SELECT` on all tables. No write perms.
2. **SQL validator** in `src/genbi/safety.py` using `sqlglot`: parse, reject anything that isn't a single `SELECT`/`WITH … SELECT`. Strip semicolons. Reject `INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|GRANT|TRUNCATE|COPY`.
3. **Query limits**: `SET LOCAL statement_timeout = '5s'`; enforce `LIMIT 1000` (append if missing).
4. **Connection pool** uses the read-only role; the write role is only used by `seed.py`.

## Implementation milestones (weekly demo cadence, Task 2)

| Milestone | Week | App deliverable | SDLC deliverable | Demo line |
|-----------|------|-----------------|------------------|-----------|
| **M1 — Skeleton** | 1 | Postgres up, schema + seeded data, `CLAUDE.md`, ruff hooks, `/seed-data` skill | `developer` + `code-reviewer` subagents; `claude-review.yml` on PRs; `git commit` advisory hook | "Here's the data, the repo, **and an AI reviewer on every PR.**" |
| **M2 — Agent + CLI** | 2 | `ClaudeSDKClient` with `schema_introspect` + `sql_execute` + SQL validator; terminal chat | `test-writer` subagent + TDD loop; stub `eval-regression.yml` | `"How many high-priority tickets closed last month?"` → number + SQL, TDD-written. |
| **M3 — Streamlit + charts** | 3 | Streamlit chat UI, `chart_render` tool, agent trace sidebar, CSV export | `/pr-prep` skill; `docs-writer` subagent + docs-drift hook; start `sdlc-metrics.csv` | `"Show revenue by region as a bar chart"` → chart + summary; PR opened via `/pr-prep`. |
| **M4 — Evals + subagents + MCP** | 4 | `evals/run_evals.py` with 12–15 cases; `sql-reviewer` + `chart-designer` subagents; standalone Postgres MCP | `/triage` + `/security-sweep` skills; `nightly-doc-sync.yml`; `release-notes` subagent; live `eval-regression.yml` | Eval pass-rate gate on a PR + a nightly doc-sync PR merged. |
| **M5 — Polish + final demo** | 5 | Hero-questions dropdown, "Explain this chart" button, `docs/demo-script.md` | `issue-to-pr.yml`; SDLC metrics slide | Live "issue → PR" demo + metrics slide (Task 3). |

Each Friday: `/weekly-update` → commit `docs/weekly-updates/NN.md` → paste into Jira.

## Task 1 deliverables (concept)

Write `docs/concept.md` covering: problem statement (reporting backlog, ad-hoc requests), target user (reporting analyst, manager), value (self-serve answers in seconds), capabilities (NL → SQL → chart + summary), data model (sales_orders, tickets), tooling (Claude Agent SDK + Postgres + Streamlit), safety model. Include the two hero questions you'll demo in M5. **3–5 min readout** — bullets, no prose walls.

## Evaluation approach

`evals/questions.yaml` — 12–15 cases:
```yaml
- id: q01
  question: "What was our top-selling product last month?"
  must_include_tables: [sales_orders]
  expected_kind: table|scalar
  expected_columns: [product, total_amount]
- id: q02
  question: "Show revenue by region as a bar chart"
  must_include_tables: [sales_orders]
  expected_kind: chart
  expected_chart_type: bar
# ...
```
`run_evals.py` runs each through the agent, inspects the tool-call trace, and asserts structural expectations (tables touched, chart type, non-empty result). Target ≥75% pass by end of M4. This is your regression guard.

## Verification (end-to-end)

After M3, you should be able to:
```bash
docker compose up -d postgres
uv sync
uv run python -m genbi.seed          # or /seed-data
uv run streamlit run app/streamlit_app.py
```
Then in the UI, ask both hero questions and confirm: chart renders, SQL visible in trace panel, summary reads cleanly, CSV export works. After M4, also run:
```bash
uv run python evals/run_evals.py     # or /run-eval
```
and expect ≥75% pass.

## Critical files to create (in order)

**App + domain subagents**
1. `docker-compose.yml`, `pyproject.toml`, `CLAUDE.md`, `.gitignore` additions
2. `.claude/settings.json` (hooks + permissions), `.claude/skills/seed-data/SKILL.md`
3. `src/genbi/db.py`, `src/genbi/seed.py`, `src/genbi/safety.py`
4. `src/genbi/tools.py`, `src/genbi/agent.py`
5. `app/streamlit_app.py`
6. `.claude/agents/{sql-reviewer,schema-explorer,chart-designer}.md`
7. `evals/questions.yaml`, `evals/run_evals.py`
8. `mcp_servers/postgres_readonly.py`, `.mcp.json` (M4)
9. `docs/concept.md` (Task 1), `docs/demo-script.md` (Task 3)

**SDLC optimization layer**
10. `.claude/agents/{developer,code-reviewer,test-writer,docs-writer,release-notes}.md` (staggered M1–M4)
11. `.claude/skills/{pr-prep,triage,daily-standup,security-sweep}/SKILL.md` (staggered M3–M4)
12. `.github/workflows/claude-review.yml` (M1), `.github/workflows/eval-regression.yml` (M2 stub → M4 full)
13. `.github/workflows/{nightly-doc-sync,release-notes}.yml` (M4), `.github/workflows/issue-to-pr.yml` (M5)
14. `docs/sdlc-metrics.csv` (M3), `docs/sdlc-slide.md` (M5 — the metrics slide narrative)

## Execution discipline (process, not code)

- **Work one milestone at a time.** Don't start M3 until M2 has a working terminal demo.
- **Use Claude Code to build Claude Code tooling.** Every skill/subagent/hook should be authored *by* Claude Code, not hand-written — that's the learning.
- **Ship the weekly update every Friday** even if the milestone slips; stakeholders care about cadence.
- **Keep one rehearsed hero question per milestone** so you always have a live demo segment ready.
