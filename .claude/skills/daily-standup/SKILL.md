---
name: daily-standup
description: Print a yesterday/today/blockers standup summary from git log + open PRs + open issues. Prints to chat only — no files, no commits. Useful for solo work and trivially adaptable for team standups.
allowed-tools: Bash(git:*), Bash(gh:*)
---

# /daily-standup

A 10-second answer to "what did I do yesterday, what am I doing today, anything blocking me." Reads the git log + GitHub state; writes nothing. The point is ritual + context, not a commit artefact.

## Runbook

1. **Pick the window.** "Yesterday" means "since the last standup" for a human who works daily — operationally, the last 24 hours is wrong on Mondays (skips the weekend) and wrong after time off. Use `git log --author=@me --since="1 day ago"` as the default, but if that returns zero commits, widen to `--since="3 days ago"` and say so in the header ("no commits in the last 24h — showing since Friday"). On Monday mornings, default to `--since="last Friday"`.
2. **Gather signal** (run in parallel):
   - `git log --author=@me --since=<window> --pretty=format:"%h %s"` — what the author shipped.
   - `git rev-parse --abbrev-ref HEAD` + `git status --porcelain` — what's in progress on the working tree.
   - `gh pr list --author @me --state open --json number,title,isDraft,reviewDecision,url` — author's open PRs + review state.
   - `gh pr list --search "review-requested:@me is:open" --json number,title,url` — PRs waiting on the author's review (blocker candidate).
   - `gh issue list --assignee @me --state open --json number,title,labels,url` — assigned issues; the ones tagged `claude-implement` are candidates for the issue-to-PR workflow.
3. **Classify.**
   - **Yesterday:** every commit in the window, collapsed to one bullet per scope (e.g. three `feat(evals): …` commits become one `finished evals harness` bullet).
   - **Today:** derived from (a) branch name + working-tree state, (b) any PR with `reviewDecision: CHANGES_REQUESTED`, (c) assigned issues. If none of these apply, print "TBD — no work queued" rather than inventing a task.
   - **Blockers:** PRs waiting on others (state `REVIEW_REQUIRED` >24h old), review requests owed to the author (they're blocking someone else, which counts), CI red on the current branch (`gh run list --branch <branch> --limit 1 --json conclusion`). If none, write "none" explicitly.
4. **Print the summary.** Exact format below — terse, no prose, no headings beyond the three. This is the whole output; don't wrap it in extra commentary.

## Output format

```
## standup YYYY-MM-DD

**Yesterday** (since <start>)
- <one line per shipped chunk>

**Today**
- <branch or PR in progress> — <next action>
- (optional) pending review on PR #<n> — <title>

**Blockers**
- <one line, or "none">
```

## Scope guardrails

- **Read-only.** No `Write`, no `Edit`, no `git commit`, no `gh pr … create`. This skill prints to chat; the artefact is the conversation.
- **Don't include other authors' work.** `--author=@me` everywhere. If the repo has co-authors, the author can tweak the skill locally — default stays solo.
- **Don't re-derive the weekly update.** If the window you pick spans five days (e.g. Monday morning rolling back to Friday), that's fine for standup context, but a full week should go through `/weekly-update` — mention it in the header and stop short of drafting a file.
- **Don't invent "Today" items.** If the working tree is clean, branch is `main`, no PRs are in flight, and no issues are assigned, print "TBD — no work queued" and leave the call to the author. Inventing a plausible-sounding next task is worse than no task.
- **Blockers section is not optional.** Write "none" explicitly — a missing section reads as "I didn't check."
- **Don't call `gh` without the `@me` scope.** Broader searches risk leaking private org data into the standup; keep it to the author's own work.
