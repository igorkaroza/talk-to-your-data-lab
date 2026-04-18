---
name: triage
description: Read the latest failing CI run on the current branch, classify the failure, and draft a minimal fix plan. Can optionally hand the plan to the `developer` subagent — never pushes a fix autonomously.
allowed-tools: Bash(gh:*), Bash(git:*), Read, Agent
---

# /triage

Turn a red CI run into a next action in under a minute. The goal is a one-paragraph diagnosis + a concrete diff proposal the author can accept, tweak, or discard.

## Runbook

1. **Find the run.** `git rev-parse --abbrev-ref HEAD` for the branch, then `gh run list --branch <branch> --limit 5 --json databaseId,name,conclusion,headBranch,workflowName,event,createdAt`. Pick the most recent `conclusion: "failure"`. If every recent run is green, say so and stop — there's nothing to triage.
2. **Pull the logs.** `gh run view <databaseId> --log-failed`. Also run `gh run view <databaseId> --json jobs,displayTitle` to see which job/step failed. Quote the failing step name verbatim in the report.
3. **Classify.** Assign exactly one bucket:
   - **test** — `pytest` step failed; assertion error or exception in a test.
   - **lint** — `ruff check` / `ruff format` step failed.
   - **eval** — `evals/run_evals.py` exited non-zero or the `--gate` check dropped pass-rate >5pp.
   - **infra** — Postgres service didn't come up, `uv sync` failed, action couldn't check out, network timeout.
   - **auth** — `ANTHROPIC_API_KEY` missing/invalid, `GITHUB_TOKEN` scope too narrow, `gh` 401/403.
   - If the logs straddle two buckets, pick the one that *caused* the other (e.g. infra caused test). Say so explicitly.
4. **Diagnose.** For `test` / `eval` failures, pull the failing assertion + the nearest traceback frame in our code. Read the offending file (`Read` the source around the reported line). State the root cause in one sentence — what the code does vs. what the test expects. For `lint`, quote the ruff message + filename:line. For `infra` / `auth`, point at the workflow step + the missing secret/service.
5. **Propose a minimal diff.** Describe the smallest change that would make the run green. File path + line range + what to change. Do **not** apply the change — the author decides.
6. **Optional delegation.** If the user says "go ahead" or "fix it", invoke the `developer` subagent via the `Agent` tool with a prompt shaped like: *"CI run <id> on branch <branch> failed with <bucket>. Root cause: <one sentence>. Proposed fix: <diff outline>. Implement, run `uv run pytest -q`, and stop before committing."* Never push. Never commit from this skill.

## Report format

```
## triage report

**Run:** <workflow name> #<id> — <failed step>
**Branch:** <branch>
**Bucket:** test | lint | eval | infra | auth

### Root cause
<one or two sentences — what the code does vs. what CI expects>

### Proposed fix
- file: `<path>:<line>` — <change>
- (optional) file: `<path>` — <change>

### Verification
- Local: <one command that reproduces the failure, or confirms the fix>
- CI: re-run the failing job once the fix lands.
```

## Scope guardrails

- Read + report only. No `Write`, no `Edit`, no `git commit`, no `git push`, no `gh pr …` mutations. Classification + plan; the author or the `developer` subagent applies the fix.
- Don't re-run the failing workflow from this skill (`gh run rerun`) — that's a deliberate action the author takes after landing a fix.
- If the run is from a different branch than `HEAD`, call it out and stop — triaging someone else's branch is almost always a mistake.
- Cap log excerpts at ~20 lines per finding. If a stack trace is longer, quote the top frame in our code and the bottom frame, not the middle.
- Never mark a failure as "flaky" on one run — that's a pattern call the author makes after seeing the same test fail multiple times on different PRs.
