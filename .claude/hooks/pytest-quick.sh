#!/usr/bin/env bash
# Stop hook — run a quick pytest sweep at end-of-turn. Advisory: never blocks.
# If there are no tests yet, pytest exits 5; we swallow that and all other non-zeros.

set -u

# Silently no-op if uv isn't installed (e.g. running outside the dev env).
command -v uv >/dev/null 2>&1 || exit 0

# Run in foreground so output surfaces in the session, but always exit 0.
{
    echo ""
    echo "--- pytest -q (advisory) ---"
    uv run pytest -q 2>&1 || true
    echo "--- end pytest ---"
    echo ""
} >&2

exit 0
