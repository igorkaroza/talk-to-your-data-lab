---
name: security-sweep
description: SQL-safety + secrets + role-isolation audit across the repo. Grep-driven scan plus a security-lens code-reviewer pass on the current diff. Flags; never fixes.
allowed-tools: Bash(git:*), Read, Glob, Grep, Agent
---

# /security-sweep

Weekly (or pre-release) regression guard for the three safety rails in [CLAUDE.md](CLAUDE.md) §Safety rails: dual-role DB, SELECT-only validator, no secrets in code. Produces a terse `## security-sweep report`; a human fixes anything flagged.

## Runbook

1. **Banned SQL-building patterns.** Under `src/genbi/` and `mcp_servers/`, `Grep` for:
   - `f"...SELECT` / `f'...SELECT` / `f"...FROM` / `f'...FROM` — f-string SQL.
   - `%s` adjacent to `SELECT`/`FROM`/`WHERE` — printf-style SQL.
   - `.format(` applied to a string containing SQL keywords.
   - Any `.execute(` call whose argument isn't a `sqlalchemy.text(...)` or a module-level `_SQL` constant (i.e. bare string concatenation).
   Exclude test fixtures under `tests/` and `evals/` — they're allowed to string-build for assertions. Each real hit is a `block` finding.
2. **Admin-role isolation.** `Grep` for `genbi_admin` repo-wide. The **only** legitimate references are in [src/genbi/seed.py](src/genbi/seed.py), [docker-compose.yml](docker-compose.yml), [.env.example](.env.example), and documentation (`CLAUDE.md`, `README.md`, `PLAN.md`, `docs/**`). Anything else — especially anywhere under `src/genbi/tools.py`, `src/genbi/agent.py`, `app/`, `evals/`, `mcp_servers/` — is a `block` finding.
3. **Validator bypass.** `Grep` for `engine.connect(` / `engine.begin(` under `src/genbi/` and `mcp_servers/`. Every non-`seed.py` call must be reached via `safety.validate_select(...)` first (follow the call graph — `Read` the surrounding function). Any read path that executes arbitrary SQL without the validator is a `block` finding.
4. **Secrets hygiene.** `Glob` for `**/.env` and `**/.env.*`. Confirm every match except `.env.example` is covered by `.gitignore` (`Read` `.gitignore` and verify). `Grep` the repo for likely API-key shapes: `sk-ant-[A-Za-z0-9_-]{20,}`, `ghp_[A-Za-z0-9]{30,}`, `AKIA[0-9A-Z]{16}`. Anything checked in is a `block` finding; note the file + line but **never** paste the value into the report.
5. **Diff-focused review.** If the branch has commits ahead of `main` (`git rev-list --count main..HEAD` > 0), invoke the `code-reviewer` subagent via the `Agent` tool, passing `git diff main...HEAD` as context with the prompt: *"Security lens only: flag SQL injection, validator bypass, missing LIMIT, `genbi_admin` leakage outside seed.py, or hard-coded secrets. Be terse; skip style nits."* Fold the subagent's `BLOCK`/`WARN` findings into the report. If the branch is clean vs. `main`, skip this step and note it.

## Report format

```
## security-sweep report

**Verdict:** CLEAN | NITS | BLOCK

### Findings
- [severity] <file>:<line> — <one-sentence issue>. Suggested direction: <concrete action>.
- …

### Clean
- SQL building: <one line>
- Admin-role isolation: <one line>
- Validator coverage: <one line>
- Secrets / .env: <one line>
- Diff review: <one line, or "skipped — no diff vs main">
```

Severities: `info` (style nit, not a rail violation), `warn` (likely rail violation under some conditions), `block` (definite rail violation — must fix before merge). `BLOCK` if any finding is `block`; `NITS` if all findings are `info`/`warn`; `CLEAN` if no findings. If everything is clean, emit the `CLEAN` verdict and a one-line summary per section — skip `### Findings`.

## Scope guardrails

- Read + report only. No `Write`, no `Edit`. You flag; a human fixes.
- Never paste a suspected secret value into the report — reference file + line only. The whole point of the check is to avoid re-exposing it.
- Don't run the `sql-reviewer` subagent here — this skill is about the rails (role, validator, secrets), not per-query SQL correctness. `/run-eval` is where `sql-reviewer` lives.
- If a finding would only fail under an edge case you can't reproduce from the code alone (e.g. a runtime-assembled SQL string), severity `warn`, not `block` — but name it explicitly so the author can verify.
- Cap findings at 8. If there are more, keep the 8 highest severity, and say "N additional findings omitted — re-run after the top issues are addressed."
