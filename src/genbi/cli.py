"""GenBI CLI entry point.

Launch with ``uv run python -m genbi.cli chat``.
"""

from __future__ import annotations

import asyncio

import typer

from genbi.agent import run_chat

app = typer.Typer(help="Talk-to-Your-Data GenBI CLI.")


@app.command()
def chat() -> None:
    """Start an interactive chat against the local Postgres."""
    asyncio.run(run_chat())


if __name__ == "__main__":
    app()
