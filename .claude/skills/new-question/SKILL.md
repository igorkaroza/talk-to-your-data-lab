---
name: new-question
description: Append a new case to evals/questions.yaml (auto-assigning the next qNN id) and immediately verify it passes by running `run_evals.py -k qNN`. Use when a gap surfaces from a real demo or a PR discussion.
allowed-tools: Read, Edit, Bash(uv run:*)
---

# /new-question

Grow the eval suite in place. One invocation adds the case **and** proves it passes — or surfaces why it doesn't so the author can fix either the question or the agent.

## Runbook

1. **Read the current suite.** `Read` [evals/questions.yaml](evals/questions.yaml). Note the highest `id` (format `qNN`, zero-padded). The next id is `q{NN+1:02d}`.
2. **Gather the fields** from the user. If the user's invocation already supplies them, skip the prompts; otherwise ask in order:
   - `question`: the natural-language prompt (required, a full sentence).
   - `must_include_tables`: list of table names the generated SQL must reference, e.g. `[sales_orders]` or `[tickets]`. Required. Use the table names from [src/genbi/seed.py](src/genbi/seed.py) — only `sales_orders` and `tickets` exist.
   - `expected_kind`: `scalar` | `table` | `chart` (required).
   - `expected_chart_type`: `bar` | `line` | `pie` | `scatter` — **only if** `expected_kind == chart`.
   - `min_rows`: optional integer; use for chart and table cases where a too-short result would be meaningless (common: `3` for charts, `5` for "top N" tables).
3. **Validate.** If `expected_kind == chart` but no `expected_chart_type`, stop and ask. If `must_include_tables` contains anything outside `{sales_orders, tickets}`, stop and ask (the schema doesn't have it).
4. **Append.** Use `Edit` on [evals/questions.yaml](evals/questions.yaml) to add the new case at the end of the file. Mirror the existing indentation and field order exactly (id, question, must_include_tables, expected_kind, [expected_chart_type,] [min_rows,]). Preserve the trailing newline.
5. **Dry-run.** `uv run python -m evals.run_evals -k qNN`. Surface the result:
   - If the case passes, print a one-line confirmation (`q13 passed on first run`).
   - If it fails, print the Rich table row verbatim and tell the author: the issue is either (a) the question is ambiguous for the current agent / prompt, (b) the `must_include_tables` is too strict, or (c) the agent really is wrong and the case is a genuine regression-in-waiting. Do **not** auto-revert the append — the author decides whether to keep, tweak, or remove it.

## Scope guardrails

- Do not renumber existing ids, ever — downstream tooling (baselines, CI history) references them.
- Do not add cases that duplicate an existing question's intent. If the new prompt is near-paraphrase of a case already in the suite, flag it and ask.
- Do not invent tables or columns that aren't in `seed.py`.
- Do not run the full suite here — single-case only. Use `/run-eval` for the full matrix.
- If the `Edit` fails because the anchor is ambiguous (yaml trailing whitespace, etc.), read the file again and widen the anchor; never `Write` the whole file from scratch just to append.
