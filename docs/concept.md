# Talk-to-Your-Data — Concept brief

A 3–5 minute readout for the Jira Task 1 deliverable. The pitch isn't "another chatbot" — it's **"here's a real PoC, and here's how Claude Code built most of it."**

## Problem

Reporting teams and managers wait days for ad-hoc SQL answers. Analysts are the bottleneck: every "what's revenue by region this month?" lands as a ticket, gets queued, gets written, gets reviewed. By the time the answer ships, the question has moved on.

## Target user

- **Reporting analyst** — offloads the repetitive "one-chart" asks.
- **Manager / PM** — gets self-serve answers in seconds, not days.

Neither group writes SQL. Both read charts.

## Value

Type the question in English → get the chart, the table, a one-line summary, and the SQL that produced it. Safe by construction (read-only, validated, timeout-capped), explainable by default (full tool-call trace in the sidebar).

## Capabilities

- Natural language → PostgreSQL `SELECT` (`sql_execute` tool).
- Natural language → Plotly chart (bar / line / pie / scatter via `chart_render`).
- Schema self-discovery on first turn (`schema_introspect`).
- One-click "Explain this" re-asks the agent to summarize the last result.
- CSV export from any chart or table.

## Data model (deliberately small)

Two tables, Faker-seeded:

| table | rows | purpose |
|-------|------|---------|
| `sales_orders` | ~2,000 | revenue, region, product, date |
| `tickets` | ~1,200 | priority, status, open/close timestamps |

Small schema = demo-friendly accuracy. The eval suite would tell us if that ever stops being true.

## Hero questions

The two we'll demo, rehearsed end-to-end:

1. **"How many high-priority tickets closed this year grouped by month? Use a chart."** → line chart + one-sentence trend summary.
2. **"Show revenue by region as a bar chart."** → bar chart + ranked summary.

## Tooling — Claude Agent SDK

The app is ~800 lines of Python; the SDK does the heavy lifting.

- **`ClaudeSDKClient`** — persistent agent session. One client survives the Streamlit rerun loop via a background-thread runtime (`src/genbi/ui/runtime.py`).
- **`@tool` + `create_sdk_mcp_server`** — three in-process tools (`schema_introspect`, `sql_execute`, `chart_render`) registered on an SDK MCP server. Clean Python functions, no MCP boilerplate.
- **`stream_turn()`** async generator — the one tool-call stream shared by the CLI and the Streamlit UI. Both renderers consume the same typed events (`TextEvent` / `ToolUseEvent` / `ToolResultEvent` / `DoneEvent`).
- **Standalone stdio MCP** — the same three tools also exposed via `mcp_servers/postgres_readonly.py`, registered in `.mcp.json` so *any* Claude Code session in this repo inherits them.

## Tooling — Claude Code (the "how we shipped it" half)

Every primitive is wired to a concrete job in this repo — not meta-tooling for its own sake.

- **`CLAUDE.md`** — project conventions, safety rails, model defaults. Every Claude Code session picks it up.
- **7 skills** (`.claude/skills/`) — `/seed-data`, `/pr-prep`, `/run-eval`, `/new-question`, `/add-tool`, `/weekly-update`, `/daily-standup`.
- **5 subagents** (`.claude/agents/`) — `developer`, `code-reviewer`, `test-writer`, `docs-writer`, `sql-reviewer`. Opus on the hard-reasoning ones, Sonnet on the rest.
- **4 hooks** (`.claude/settings.json`) — ruff on Write/Edit, advisory docs-drift check, advisory PR review on `git commit`, `pytest -q` on Stop.
- **4 CI workflows** — `claude-review.yml` (PR review), `eval-regression.yml` (live eval gate, posts pass/fail matrix as a PR comment), `nightly-doc-sync.yml` (auto-PR when docs drift), `issue-to-pr.yml` (label `claude-implement` → `developer` subagent runs headless → draft PR).

## Safety model

Four rails, non-negotiable, all called out in [CLAUDE.md](../CLAUDE.md):

1. **Dual DB roles** — `genbi_admin` (write) is used only by the seed script; everything else runs as `genbi_reader` with no write grants.
2. **sqlglot validator** — every generated statement is parsed; anything that isn't a single `SELECT` / `WITH ... SELECT` is rejected. Multi-statement, DML, and DDL all blocked.
3. **Query limits** — `statement_timeout = 5s` + `LIMIT 1000` appended if missing.
4. **No secrets in code** — `.env` is git-ignored; `.env.example` is the template.

## Why this shape

We picked a narrow scope on purpose:

- **Two tables, not twenty** — schema complexity kills SQL accuracy. Small = demo-friendly.
- **SQL-only, no RAG** — stays on-theme for the reporting-teams audience and on-schedule for a 5-week build.
- **Structural evals, not numeric** — Faker data is noise, so asserting "revenue = $X" would flap every reseed. We assert on tool-firing, table references (parsed with sqlglot), and chart shape instead.

## Out of scope

- Unstructured data (docs, PDFs) — add RAG in a follow-up if needed.
- Writes of any kind — not even "save this chart"; that's a separate product with a separate safety story.
- User-level access control — this PoC assumes one trusted reader; multi-tenant row-level security is a real-product concern.

## The training payload

Alongside the working app, this repo is a **worked example of the Claude Code surface**. Every skill, subagent, hook, and workflow is authored *by* Claude Code, committed, and documented. The 5-week arc is the deliverable; the demo is the proof.
