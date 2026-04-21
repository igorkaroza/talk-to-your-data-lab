#!/usr/bin/env bash
# PreToolUse(Bash) — on `git commit *`, run an AI review over the staged diff.
# Advisory only: exit 0 always, never block the commit.

set -u
set -o pipefail

log_file=".claude/hook-errors.log"

payload="$(cat)"

cmd="$(printf '%s' "$payload" | /usr/bin/env python3 -c '
import json, sys
try:
    print(json.load(sys.stdin).get("tool_input", {}).get("command", ""))
except Exception:
    pass
' 2>/dev/null || true)"

# Only fire on `git commit` invocations.
case "$cmd" in
    *"git commit"*) ;;
    *) exit 0 ;;
esac

# No staged diff → nothing to review.
diff="$(git diff --cached 2>/dev/null || true)"
[[ -z "$diff" ]] && exit 0

# Need the Claude CLI — if it isn't on PATH, skip silently.
if ! command -v claude >/dev/null 2>&1; then
    exit 0
fi

# Timeout wrapper: prefer gtimeout (macOS coreutils), fall back to timeout, else no cap.
timeout_cmd=()
if command -v gtimeout >/dev/null 2>&1; then
    timeout_cmd=(gtimeout 30)
elif command -v timeout >/dev/null 2>&1; then
    timeout_cmd=(timeout 30)
fi

prompt=$'You are an advisory code reviewer for the talk-to-your-data-lab repo (GenBI PoC).\n\nReview the staged diff below. Focus only on:\n1. SQL-safety violations: DML/DDL slipping into the read-only path, raw string-built SQL, missing LIMIT, untrusted input in queries.\n2. Obvious correctness bugs.\n3. Missing or stale tests in tests/.\n\nBe terse: at most 5 bullets, or a single line "LGTM" if clean. Never block — the developer ships either way.\n\n--- staged diff ---'

stderr_capture="$(mktemp -t advisory-review.XXXXXX)"
trap 'rm -f "$stderr_capture"' EXIT

{
    echo ""
    echo "--- code-reviewer (advisory, model: opus) ---"
    if ! printf '%s\n\n%s\n' "$prompt" "$diff" \
        | "${timeout_cmd[@]}" claude -p --model claude-opus-4-7 2>"$stderr_capture"; then
        code=$?
        echo "(review skipped: exit $code — see $log_file)"
        {
            printf '[%s] advisory-review exit=%s\n' "$(date -u +%FT%TZ)" "$code"
            cat "$stderr_capture"
            echo "---"
        } >> "$log_file"
    fi
    echo "--- end review ---"
    echo ""
} >&2

exit 0
