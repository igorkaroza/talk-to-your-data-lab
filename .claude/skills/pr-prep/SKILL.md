---
name: pr-prep
description: Format + lint + test the branch, run the code-reviewer subagent on the diff, then draft and open a PR via gh. Use when the branch is ready for review.
allowed-tools: Bash(uv run:*), Bash(gh:*), Bash(git:*), Read, Edit, Agent
---

# /pr-prep

One command to go from a working branch to an open PR. Use it when the feature is implemented, committed locally, and you want reviewer feedback before merging.

## Runbook

1. **Format + lint.** Run `uv run ruff format .` then `uv run ruff check --fix .`. If `ruff check` still reports issues after `--fix`, stop and surface them — the developer decides whether to hand-fix or override.
2. **Tests.** Run `uv run pytest -q`. If anything fails, stop and print the failures. Do not open a PR on a red branch.
3. **Staged changes.** If `git status --porcelain` shows unstaged changes from steps 1–2 (ruff reflow), ask whether to add them as a follow-up commit before proceeding. Never auto-amend.
4. **Code review.** Invoke the `code-reviewer` subagent via the `Agent` tool, passing the output of `git diff main...HEAD` as context and asking for a terse review (correctness, SQL safety, missing tests). Surface the review verbatim to the user — they decide whether to act on it before opening the PR.
5. **Draft PR title + body.** Read `git log main..HEAD --oneline` for the commit list and `git diff main...HEAD --stat` for the surface area. Draft:
   - **Title** — scope-prefixed in the repo style: `M3(ui): …`, `M2(agent): …`, etc. Under 70 chars.
   - **Body** — a ## Summary section (1–3 bullets on *what* changed and *why*) plus a ## Test plan section (checklist of things a reviewer can verify locally). Mirror the conventions in prior PRs on `main`.
6. **Push.** If the branch isn't tracking a remote, `git push -u origin HEAD`. Otherwise `git push`. Never force-push without explicit user confirmation.
7. **Open the PR.** Use `gh pr create --title "<title>" --body "$(cat <<'EOF'`…`EOF`)"` with a heredoc body so Markdown renders correctly. Include the trailing `🤖 Generated with [Claude Code](https://claude.com/claude-code)` footer.
8. **Print the URL.** Echo the PR URL `gh pr create` returned so the user can click through.

## Scope guardrails

- Read `CLAUDE.md` → *Safety rails* before drafting the body. If the diff touches `src/genbi/safety.py` or loosens any safety rail, call it out explicitly in the PR summary — reviewers should never have to discover a rail relaxation from the diff.
- Do not run `/run-eval` here — evals live in their own workflow (`eval-regression.yml`) and take longer than a pre-PR loop. If evals matter for this change, mention it in the Test plan as a reviewer action.
- Never open a PR with `[skip ci]` or `--no-verify` — if a hook fails, surface the failure and stop.
- Never close or merge a PR from this skill. Opening only.

## When to skip the review step

If the branch is a pure docs/config change (no `.py` files in the diff), you can skip step 4 and note in the PR body that the code-reviewer was skipped for a docs-only diff.
