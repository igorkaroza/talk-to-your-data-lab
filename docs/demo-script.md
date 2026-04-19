# Demo script — 5 minutes flat

The live walkthrough for Jira Task 3. Two beats: **"look what the app does"** (~2 min) and **"look how Claude Code built it"** (~3 min). Rehearse twice before each demo — the value is in the rhythm, not the surprise.

## Setup (before the audience joins)

```bash
docker compose up -d postgres
uv run python -m genbi.seed          # fresh data, charts look the same every time
uv run streamlit run app/streamlit_app.py
```

Open a second terminal in the repo root with Claude Code running (`claude`). Keep `http://localhost:8501` and the Claude Code terminal both visible.

Window layout: Streamlit on the left, Claude Code terminal on the right. Sidebar in Streamlit should be expanded (the tool-call trace is the explainability beat).

## Beat 1 — "The app" (~2 min)

### Hero question 1 — chart (0:00–1:00)

Click the first hero button: **"How many high-priority tickets closed this year grouped by month? Use a chart."**

Narration while the status spinner runs:
> *"I typed a question in English. The agent is now picking a tool, writing a SQL statement, running it against a read-only role, and rendering a Plotly chart. No SQL from me."*

When the line chart lands (~5–10s):
- Point at the chart. One-line summary appears below it.
- Click the "data" expander. Underlying rows visible.
- Point at the sidebar — expand the two tool-call entries. **"Here's the SQL. Nothing is hidden."**
- Click **Explain** — the agent re-reads the result and writes a 2–3 sentence readout with a caveat. **"Same rail, same trace, no magic."**

### Hero question 2 — revenue chart (1:00–2:00)

Click the second hero button: **"Show revenue by region as a bar chart."**

Narration:
> *"Different table, different chart type, same discipline — schema introspect first, then a SQL query, then the chart. The agent isn't inventing numbers; every quantity came from a `sql_execute` or `chart_render` call."*

Click the CSV button. **"And yes, reporting teams get a CSV."**

## Beat 2 — "How Claude Code built it" (~3 min)

Switch to the Claude Code terminal.

### The SDK (0:00–0:30)

Narration:
> *"The app is about 800 lines. The agent loop is the Claude Agent SDK — `ClaudeSDKClient` for the session, `@tool` for the three tools, `create_sdk_mcp_server` to mount them. The CLI and the Streamlit UI share one async generator (`stream_turn`) so both surfaces consume the same tool-call events."*

Show `src/genbi/tools.py` briefly — three `@tool`-decorated functions, that's it.

### Standalone MCP (0:30–1:00)

In the Claude Code terminal: `/mcp`

Point at `postgres-readonly` in the list.

Type: **"What tables are in this database?"**

Narration:
> *"Same three tools, now as a standalone stdio MCP. Any Claude Code session in this repo picks them up via `.mcp.json`. I get ad-hoc data questions in my terminal, no app needed."*

### Skills — the authored developer workflow (1:00–1:45)

Show `.claude/skills/` in the file tree. Nine skills.

Call out three:
- **`/seed-data`** — wipes and reseeds Postgres. Used every demo setup.
- **`/run-eval`** — runs the 12-case eval suite, prints the pass/fail matrix, falls back to the `sql-reviewer` subagent on failures.
- **`/pr-prep`** — runs ruff + pytest, calls `code-reviewer` on the diff, drafts the PR body, opens it via `gh`.

Run `/run-eval` live (or have it cached if time is tight). The Rich table is the money shot.

Narration:
> *"These aren't generic commands — they encode how **this** project works. `/run-eval` knows about our baseline; `/pr-prep` knows about our commit style. Every skill was authored by Claude Code, with Claude Code."*

### Subagents + hooks (1:45–2:15)

Show `.claude/agents/` — six subagents. Call out:
- **`code-reviewer`** (Opus) — fires on every PR via `claude-review.yml`, also advisory on local `git commit` via a PreToolUse hook.
- **`docs-writer`** (Sonnet) — fires on every `tools.py` / `agent.py` edit via a PostToolUse hook, flags drift between code and `CLAUDE.md`.
- **`sql-reviewer`** (Opus) — called from `/run-eval` and `/security-sweep` with a SQL-correctness lens.

Narration:
> *"Subagents are specialists with their own tool allow-lists. Hooks wire them into the dev loop — I don't remember to run the reviewer, the hook does."*

### CI — the two hero workflows (2:15–3:00)

Open `.github/workflows/` — three files.

- **`eval-regression.yml`** — every PR runs the 12-case suite, posts the Rich matrix as a PR comment, fails the check if pass-rate drops more than 5pp vs. the committed baseline.
- **`nightly-doc-sync.yml`** — scheduled cron; runs `docs-writer`; if docs drifted, opens an auto-PR titled `chore(docs): nightly drift sync <date>`. A human merges.

If a broken-on-purpose branch is available, open the PR tab and show the red check + the matrix comment.

Narration (the close):
> *"We have a PoC, an eval gate that blocks SQL regressions, and a nightly docs-sync PR that keeps the plan and the code from diverging. Five weeks. Most of it authored by Claude Code, reviewed by Claude Code, gated by Claude Code. That's the SDLC story."*

## Closing (~30s)

Return to the Streamlit tab. Leave the revenue chart on-screen.

> *"Questions?"*

## Fallbacks

- **Chart doesn't render / agent times out** — reseed (`/seed-data`), reload the page, retry. The hero questions are the safest asks; don't freestyle during a demo.
- **Claude Code terminal latency** — skip the live `/mcp` call and show the `.mcp.json` file + a screenshot of a previous `/mcp` output.
- **CI demo unavailable** — have a pre-captured screenshot of a red `eval-regression.yml` run with the Rich matrix as a PR comment. It's a 15-second slide, not a live beat.
- **Only 3 minutes on the clock** — keep Beat 1 (hero question 1 only, skip Explain) + the CI workflows in Beat 2. Skip skills + subagents. The CI gate + the nightly sync are the highest-signal bits.

## What to cut if you overrun

Priority order for cuts (drop from the bottom first):
1. Explain button (save 20s)
2. Hero question 2 (save 60s — but only if the audience has seen chart output elsewhere)
3. Subagents beat (save 30s — collapse into "and there are six subagents, similar shape")
4. Standalone MCP beat (save 30s — mention it exists, don't demo)

Never cut: the sidebar tool-call trace (explainability), the eval gate (SDLC hero), the closing line.
