"""GenBI eval runner.

Runs each case in :file:`evals/questions.yaml` through the runtime agent
(:data:`genbi.agent.OPTIONS` + :func:`genbi.agent.stream_turn`) and scores
structurally — which tool fired, which tables the generated SQL references,
chart type, row count. Never asserts numeric values: Faker seed data is noise.

Used by:

- ``uv run python -m evals.run_evals`` — local full-suite run
- ``uv run python -m evals.run_evals -k q01`` — focus one case
- ``uv run python -m evals.run_evals --gate .eval-baseline.json`` — CI gate
  (fails if pass-rate drops more than 5pp vs. baseline)
- ``uv run python -m evals.run_evals --write-baseline .eval-baseline.json`` —
  regenerate baseline after the suite changes deliberately
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import sqlglot
import typer
import yaml
from claude_agent_sdk import ClaudeSDKClient
from rich.console import Console
from rich.table import Table
from sqlglot import exp
from sqlglot.errors import ParseError

from genbi.agent import OPTIONS, stream_turn
from genbi.events import ToolResultEvent, ToolUseEvent

QUESTIONS_PATH = Path(__file__).parent / "questions.yaml"
GATE_THRESHOLD = 0.05  # pass-rate drop > 5pp fails the gate


@dataclass
class Case:
    id: str
    question: str
    must_include_tables: list[str]
    expected_kind: str  # scalar | table | chart
    expected_chart_type: str | None = None
    min_rows: int | None = None


@dataclass
class Trace:
    tool_uses: list[ToolUseEvent] = field(default_factory=list)
    tool_results: list[ToolResultEvent] = field(default_factory=list)


@dataclass
class Outcome:
    case_id: str
    question: str
    passed: bool
    reason: str
    sql_executed: str | None


def load_cases(path: Path = QUESTIONS_PATH) -> list[Case]:
    with path.open() as fh:
        raw = yaml.safe_load(fh) or []
    return [Case(**item) for item in raw]


def _extract_tables(sql: str) -> set[str]:
    try:
        parsed = sqlglot.parse_one(sql, read="postgres")
    except ParseError:
        return set()
    if parsed is None:
        return set()
    return {t.name for t in parsed.find_all(exp.Table)}


def _sql_from_trace(trace: Trace) -> str | None:
    for use in trace.tool_uses:
        if use.name in {"sql_execute", "chart_render"} and "sql" in use.input:
            return use.input["sql"]
    return None


def _score(case: Case, trace: Trace) -> tuple[bool, str]:  # noqa: PLR0911
    use_names = [u.name for u in trace.tool_uses]

    if case.expected_kind == "chart":
        chart_calls = [u for u in trace.tool_uses if u.name == "chart_render"]
        if not chart_calls:
            return False, "chart_render was not called"
        if case.expected_chart_type:
            got = chart_calls[-1].input.get("chart_type")
            if got != case.expected_chart_type:
                return False, f"expected chart_type={case.expected_chart_type}, got {got!r}"
    elif "sql_execute" not in use_names:
        return False, "sql_execute was not called"

    sql = _sql_from_trace(trace)
    if sql is None:
        return False, "no SQL was produced"
    tables = _extract_tables(sql)
    missing = set(case.must_include_tables) - tables
    if missing:
        return False, f"SQL missed required tables: {sorted(missing)} (saw {sorted(tables)})"

    if case.min_rows is not None:
        last = next(
            (
                r
                for r in reversed(trace.tool_results)
                if r.name in {"sql_execute", "chart_render"} and not r.is_error
            ),
            None,
        )
        if last is None or last.payload is None:
            return False, "no tool result to read row_count from"
        row_count = int(last.payload.get("row_count", 0))
        if row_count < case.min_rows:
            return False, f"row_count {row_count} < min_rows {case.min_rows}"

    return True, "ok"


async def _run_one(client: ClaudeSDKClient, case: Case) -> Outcome:
    trace = Trace()
    async for ev in stream_turn(client, case.question):
        if isinstance(ev, ToolUseEvent):
            trace.tool_uses.append(ev)
        elif isinstance(ev, ToolResultEvent):
            trace.tool_results.append(ev)
    passed, reason = _score(case, trace)
    return Outcome(
        case_id=case.id,
        question=case.question,
        passed=passed,
        reason=reason,
        sql_executed=_sql_from_trace(trace),
    )


async def _run_all(cases: list[Case]) -> list[Outcome]:
    outcomes: list[Outcome] = []
    async with ClaudeSDKClient(options=OPTIONS) as client:
        for case in cases:
            outcomes.append(await _run_one(client, case))
    return outcomes


def _render_table(console: Console, outcomes: list[Outcome]) -> None:
    table = Table(title="GenBI eval results")
    table.add_column("id", style="bold")
    table.add_column("question", max_width=60)
    table.add_column("status", justify="center")
    table.add_column("reason")
    for o in outcomes:
        status = "[green]pass[/green]" if o.passed else "[red]fail[/red]"
        table.add_row(o.case_id, o.question, status, "" if o.passed else o.reason)
    console.print(table)


def _pass_rate(outcomes: list[Outcome]) -> float:
    return sum(1 for o in outcomes if o.passed) / len(outcomes) if outcomes else 0.0


def main(
    k: Annotated[
        str | None,
        typer.Option("-k", help="Run only the case with this id (e.g. q01)."),
    ] = None,
    gate: Annotated[
        Path | None,
        typer.Option("--gate", help="Fail if pass-rate drops >5pp below this baseline JSON."),
    ] = None,
    write_baseline: Annotated[
        Path | None,
        typer.Option(
            "--write-baseline",
            help="Write the current run as a baseline JSON (only on full-suite success).",
        ),
    ] = None,
    json_out: Annotated[
        Path | None,
        typer.Option("--json-out", help="Write full per-case result JSON here."),
    ] = None,
) -> None:
    console = Console()
    cases = load_cases()
    if k is not None:
        cases = [c for c in cases if c.id == k]
        if not cases:
            console.print(f"[red]No case with id {k!r}[/red]")
            raise typer.Exit(2)

    outcomes = asyncio.run(_run_all(cases))
    _render_table(console, outcomes)
    rate = _pass_rate(outcomes)
    console.print(
        f"\n[bold]pass-rate:[/bold] {rate:.0%} "
        f"({sum(1 for o in outcomes if o.passed)}/{len(outcomes)})"
    )

    result = {
        "run_date": datetime.now(UTC).isoformat(),
        "pass_rate": rate,
        "cases": [
            {
                "id": o.case_id,
                "passed": o.passed,
                "reason": o.reason,
                "sql": o.sql_executed,
            }
            for o in outcomes
        ],
    }
    if json_out is not None:
        json_out.write_text(json.dumps(result, indent=2))

    exit_code = 0 if all(o.passed for o in outcomes) else 1

    if gate is not None:
        baseline = json.loads(gate.read_text())
        drop = float(baseline["pass_rate"]) - rate
        if drop > GATE_THRESHOLD:
            console.print(
                f"[red]GATE FAILED:[/red] pass-rate dropped {drop:.2%} vs. baseline "
                f"({baseline['pass_rate']:.0%} → {rate:.0%})"
            )
            exit_code = 1
        else:
            console.print(
                f"[green]GATE PASSED:[/green] pass-rate {rate:.0%} "
                f"(baseline {baseline['pass_rate']:.0%})"
            )

    if write_baseline is not None:
        if exit_code != 0:
            console.print("[yellow]Refusing to write baseline: at least one case failed.[/yellow]")
        else:
            write_baseline.write_text(json.dumps(result, indent=2))
            console.print(f"Wrote baseline to {write_baseline}")

    raise typer.Exit(exit_code)


if __name__ == "__main__":
    typer.run(main)
