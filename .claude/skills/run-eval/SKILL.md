---
name: run-eval
description: Run the GenBI eval suite, print the pass/fail matrix, and invoke sql-reviewer on any failing case. Use before opening a PR that touches SQL prompting, tool definitions, or the safety validator.
allowed-tools: Bash(uv run:*), Bash(docker compose:*), Bash(docker ps:*), Read, Agent
---

# /run-eval

Run `evals/run_evals.py` and turn any failures into actionable review findings. Target: ≥75% pass (M4 bar from [PLAN.md](PLAN.md)); ≥90% is great.

## Runbook

1. **Postgres up?** `docker compose ps postgres` — if it isn't listed as Up, either start it (`docker compose up -d postgres`) or, if the DB is empty, tell the user to run `/seed-data` first. Eval runs hit the real DB.
2. **Run the suite.** `uv run python -m evals.run_evals`. If the user passed `-k qNN` in the skill args, forward it (`uv run python -m evals.run_evals -k qNN`).
3. **Read the table.** The runner prints a Rich table with columns `id | question | status | reason`. Copy the pass-rate line verbatim (e.g. `pass-rate: 83% (10/12)`).
4. **Drill into failures.** For each failing row:
   - If the `reason` mentions "SQL missed required tables" or "no SQL was produced", the SQL is wrong. Pull the executed SQL from the runner output (it's surfaced in the final JSON if `--json-out` was used, otherwise re-run just that case with `-k qNN` and scrape the tool-use trace).
   - Invoke the `sql-reviewer` subagent via the `Agent` tool with a prompt shaped like: *"The eval case qNN asked: '<question>'. The agent produced: `<SQL>`. Please review."* Paste the SQL and the NL question.
   - Capture the subagent's `## sql-review report` verbatim.
5. **Summarize.** Emit a single Markdown block with:
   - The pass-rate line.
   - A bullet list of failing case ids + one-liner reasons.
   - The `sql-review report` for each failed case (indented under that case's bullet).
6. **Hint next step.** If pass-rate is below 75%, say so and suggest tightening the system prompt in [src/genbi/agent.py](src/genbi/agent.py) or adding a schema hint. If the failures are specific to one table, say which.

## Scope guardrails

- Do not write or edit any files. This skill is read + report only.
- Do not regenerate `.eval-baseline.json` — that's a deliberate, reviewed action (run `uv run python -m evals.run_evals --write-baseline .eval-baseline.json` manually on a known-good `main`). See the CI workflow's promote-baseline step.
- If `docker compose ps` shows Postgres unreachable, do not silently start it behind the user's back; ask first.
- Eval runs call the live Anthropic API — if the user's `ANTHROPIC_API_KEY` isn't set, stop and prompt them to export it. The runner's error will say so but the skill should catch it early.
- Keep the final summary under ~40 lines; if sql-reviewer output is long, truncate each report to its Verdict + top 3 Findings and link the full block in a collapsed `<details>`.
