# SDLC optimization with LLMs — the one slide

The narrative for the final demo's closing slide. The pitch: **Claude Code compresses every phase of the loop, not just "writing code."** This doc is the speaking script + the bullet blocks to drop into a slide deck.

## Slide title

> **5 weeks, one PoC, a working SDLC — authored by Claude Code**

## The three loops

Each phase below maps to concrete files in this repo — every bullet is something you can `grep` for, not a promise.

### Inner loop — author → format → test (seconds)

- **`CLAUDE.md`** — project conventions every session picks up automatically.
- **Hooks** (`.claude/settings.json`):
  - `PostToolUse Write|Edit` → `ruff format` + `ruff check --fix`. Code stays clean without thinking.
  - `PostToolUse Write|Edit` on `tools.py`/`agent.py` → `docs-writer` advisory drift check.
  - `Stop` → `uv run pytest -q`. Can't end a session on a red bar.

### PR loop — plan → implement → review → ship (minutes)

- **Subagents** (`.claude/agents/`) — six specialists, each with its own tool allow-list:
  - `developer` — end-to-end feature work.
  - `code-reviewer` (Opus) — correctness, SQL safety, test coverage.
  - `test-writer` — happy path + one negative, pytest house style.
  - `docs-writer` — keeps `CLAUDE.md` / `README.md` in sync with code.
  - `sql-reviewer` (Opus) — JOIN correctness, NULL hazards, cardinality risk.
  - `release-notes` — tag-to-tag `git log` + merged PRs → stakeholder Markdown grouped by commit scope.
- **Skills** (`.claude/skills/`) — seven user-facing commands that encode *this project's* workflow:
  - `/seed-data`, `/run-eval`, `/new-question`, `/pr-prep`, `/add-tool`, `/weekly-update`, `/daily-standup`.
- **Advisory PreToolUse hook** on `git commit` — `code-reviewer` runs on the staged diff, prints findings, never blocks. Human decides.

### CI/CD — automated gates (every PR, every night)

- **`claude-review.yml`** — AI PR review on every pull request.
- **`eval-regression.yml`** — runs the 12-case eval suite, posts the Rich pass/fail matrix as a PR comment, **fails the check if pass-rate drops >5pp vs. the committed baseline**. SQL quality is now a PR gate.
- **`nightly-doc-sync.yml`** — scheduled cron; if docs drifted, opens an auto-PR titled `chore(docs): nightly drift sync <date>`. Keeps docs from rotting across a multi-week build.
- **`issue-to-pr.yml`** — label an issue `claude-implement` (or `@claude` in a comment on a labeled issue) → the `developer` subagent runs headless on Opus, green-tests a branch, opens a **draft** PR with `Closes #N`. Humans mark ready-for-review. The headline "issue becomes a PR" demo.
- **`release-notes.yml`** — on `v*` tag push, the `release-notes` subagent drafts the GitHub Release body from the tag-to-tag git log + merged PRs. One `gh release create --verify-tag` later, the release is live.

## Claude SDK — the app side

The PoC itself is a demo of the Claude Agent SDK surface:

- **`ClaudeSDKClient`** — persistent agent session; one client, one conversation memory, re-entered per user turn.
- **`@tool` + `create_sdk_mcp_server`** — three tools (`schema_introspect`, `sql_execute`, `chart_render`) as clean Python functions, zero MCP boilerplate.
- **`stream_turn()`** — one async generator, two UIs (CLI + Streamlit) consuming the same typed events.
- **`.mcp.json` + standalone stdio MCP** — the same three tools also expose as `mcp_servers/postgres_readonly.py`, so any Claude Code session in the repo picks them up via `/mcp`. Two tool surfaces, one implementation.

## The numbers

Signals worth calling out:
- **Scope** — dual-role Postgres, a SELECT-only agent with three tools, a Streamlit UI with live tool-call trace, a 12-case structural eval suite, a standalone stdio MCP, and five CI workflows — all authored with Claude Code.
- **PR cycle time** — open → merged in under an hour, most PRs. The `code-reviewer` check runs in ~60s; `eval-regression.yml` runs in ~3 min.
- **Human overrides of AI review** — trended down week over week as prompts tightened. The reviewer is useful, not yet infallible.

## The "so what"

Three things to leave the audience with:

1. **The PoC works** — NL → SQL → chart with a visible tool-call trace. Hero questions rehearsed.
2. **The SDLC works** — a PR that strips `LIMIT` from the validator would fail `eval-regression.yml` today. Docs can't silently drift past `nightly-doc-sync.yml`.
3. **The workflow is the deliverable** — every skill, subagent, hook, and workflow in this repo is reusable on the next project. Copy `.claude/` + `.mcp.json` + `.github/workflows/` and you've moved 80% of the way to the next SDLC-integrated AI app.

## Tone cues for the slide talk

- **Concise.** No "we leveraged an agentic workflow to." Say "the eval gate fails the PR." Done.
- **Friendly.** First-person plural ("we shipped", "we gated SQL regressions") beats corporate passive.
- **Demonstrative.** Every claim has a file path behind it. If a bullet doesn't map to a file, cut it.
- **Honest about trade-offs.** The app is narrow on purpose (two tables, SQL-only, no RAG). Say so — that's why the demo doesn't flap.

## Where it's headed next

- **RLS + per-user auth** — the read-only role is enough for a PoC; a real product needs row-level security.
- **RAG over unstructured data** — pull in docs + PDFs alongside SQL once the SQL story is boring.
- **Multi-dataset routing** — one agent, N databases, a router subagent that picks the connection from the question.
