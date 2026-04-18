#!/usr/bin/env bash
# PostToolUse(Write|Edit) — when tools.py / agent.py / pyproject.toml change,
# invoke the docs-writer subagent to detect drift in CLAUDE.md / README.md / docs/concept.md.
# Advisory only: exit 0 always, never block the edit.

set -u

payload="$(cat)"

path="$(printf '%s' "$payload" | /usr/bin/env python3 -c '
import json, sys
try:
    print(json.load(sys.stdin).get("tool_input", {}).get("file_path", ""))
except Exception:
    pass
' 2>/dev/null || true)"

# Only fire on edits to the source-of-truth files the docs describe.
case "$path" in
    *src/genbi/tools.py|*src/genbi/agent.py|*pyproject.toml) ;;
    *) exit 0 ;;
esac

# Need the Claude CLI — if it isn't on PATH, skip silently.
if ! command -v claude >/dev/null 2>&1; then
    exit 0
fi

# Timeout wrapper: prefer gtimeout (macOS coreutils), fall back to timeout, else no cap.
timeout_cmd=()
if command -v gtimeout >/dev/null 2>&1; then
    timeout_cmd=(gtimeout 45)
elif command -v timeout >/dev/null 2>&1; then
    timeout_cmd=(timeout 45)
fi

prompt=$'Invoke the docs-writer subagent (.claude/agents/docs-writer.md) to check for drift\nbetween the file just edited and the project docs (CLAUDE.md, README.md, docs/concept.md\nif it exists).\n\nThe file that was just edited is: '"$path"$'\n\nReport in the exact Markdown structure the subagent defines (Drift found / Clean /\nSuggested edits). If clean, emit the single-line "No drift detected" form.\n\nDo not rewrite any docs — reports only.'

{
    echo ""
    echo "--- docs-drift (advisory, model: sonnet) ---"
    printf '%s\n' "$prompt" \
        | "${timeout_cmd[@]}" claude -p --model claude-sonnet-4-6 2>&1 \
        || echo "(docs-drift skipped: timeout or CLI error — edit proceeds)"
    echo "--- end docs-drift ---"
    echo ""
} >&2

exit 0
