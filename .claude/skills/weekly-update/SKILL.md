---
name: weekly-update
description: Draft a Jira-ready weekly status from git log + closed PRs since the last update, write it to docs/weekly-updates/NN.md, and print the bullets back so the author can paste into Jira. Run every Friday.
allowed-tools: Bash(git:*), Bash(gh:*), Bash(ls:*), Read, Write
---

# /weekly-update

One command to go from "what did I ship this week" to a committed `docs/weekly-updates/NN.md` and a clean bullet list ready for the Jira task comment. Runs Friday; writes in the voice of the author (first person, terse, no marketing).

## Runbook

1. **Find the previous update.** `ls docs/weekly-updates/` to enumerate existing files. The next id is `{NN+1:02d}` (zero-padded). If the directory is empty, start at `01`. If a file for the current week already exists (same Friday date), ask the author whether to overwrite or bail — never silently clobber.
2. **Pick the window.** Default window is `since the last update's commit date` → `HEAD`. If no prior update exists, fall back to `--since="7 days ago"`. Surface the exact date range you're using in the report header so the author can sanity-check it.
3. **Gather signal** (run these in parallel):
   - `git log --since=<start> --pretty=format:"%h %s"` — commit subjects.
   - `git log --since=<start> --pretty=format:"%h" --shortstat` — surface area (files changed / insertions / deletions) for a one-line "size" number.
   - `gh pr list --state merged --search "merged:>=<start>" --json number,title,mergedAt,url` — merged PRs in the window.
   - `gh pr list --state open --json number,title,isDraft,url` — open PRs as "in flight" context.
4. **Map commits → milestones.** Read the commit subjects — the repo convention is `Mx(scope): …` prefixes (e.g. `M4(ci): …`, `M3(ui): …`). Group the bullets under the milestone tags that appear in the window. Untagged commits ("docs: …", "chore: …") go under a `Housekeeping` bucket at the end.
5. **Draft the update.** Mirror the template below. One bullet per commit group, not per commit — collapse `M4(evals): harness + 12 questions` + `M4(skills): /run-eval + /new-question` into a single `M4 evals` bullet when they clearly belong together. Keep each bullet under ~20 words; this is a Jira paste, not a changelog.
6. **Write the file.** `Write` [docs/weekly-updates/NN.md](docs/weekly-updates/NN.md). Preserve the template below verbatim — the file is itself the Jira paste target plus a permanent log, so the same content serves both audiences.
7. **Print back.** Echo the `## Shipped` bullets to the chat (just that section — the author pastes it into the Jira weekly-status task). Also print the filename so the author can review the full file before committing.
8. **Do not commit.** The author decides whether to roll the weekly-update into the current branch's commit or make a standalone `docs: weekly update NN` commit. Never `git commit` from this skill.

## File template

```markdown
# Weekly update NN — YYYY-MM-DD

**Window:** YYYY-MM-DD → YYYY-MM-DD ({N} commits, {M} files, +{ins}/-{del})

## Shipped

- **Mx** — <1-line bullet per shipped chunk, Jira-voice>
- **Mx** — <...>
- **Housekeeping** — <docs/chore bullet, if any>

## In flight

- PR #<n> — <title> (<draft|ready>)

## Next week

- <1–3 bullets on what's queued — pulled from PLAN.md / M<next> milestone, not invented>

## Risks / blockers

- <one line, or "none" — this is where you flag things the stakeholder should act on>
```

## Scope guardrails

- **Never invent work.** Every bullet in `## Shipped` must trace back to a real commit or merged PR in the window. If `gh pr list` is empty, say so — don't fluff the section.
- **Don't re-summarize full commit messages.** One bullet per coherent chunk, Jira-voice — the full commit log is already in git.
- **Don't include private notes.** If the author uses `/daily-standup` for rough drafts, those are local; the weekly-update is stakeholder-facing. Skip anything that reads like a TODO.
- **Don't renumber existing files.** If `NN.md` collisions surface (rare — the same week ran twice), ask; never overwrite a prior week's file.
- **Mirror the repo's milestone labels exactly** — `M3`, `M4`, `M5` — so the update slots into the plan in [PLAN.md](PLAN.md) without translation. If commits span two milestones, use two bullets.
- **Risks section is not optional.** Write "none" explicitly if nothing's wrong — an empty bullet list reads as "I forgot to check."
