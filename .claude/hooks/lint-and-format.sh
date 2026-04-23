#!/usr/bin/env bash
# PostToolUse(Write|Edit) — format + auto-fix Python files with ruff.
# Reads {tool_input: {file_path: ...}} on stdin. Never blocks: exit 0 always.
set -u

payload="$(cat)"
path="$(printf '%s' "$payload" | /usr/bin/env python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("tool_input",{}).get("file_path",""))' 2>/dev/null || true)"

[[ -z "$path" ]] && exit 0
[[ "$path" != *.py ]] && exit 0
[[ ! -f "$path" ]] && exit 0

uv run ruff format "$path" >/dev/null 2>&1 || true
uv run ruff check --fix "$path" >/dev/null 2>&1 || true
exit 0
