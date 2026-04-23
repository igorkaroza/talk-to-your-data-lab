"""GenBI CLI entry point.

Launch with ``uv run python -m genbi.cli chat``.
"""

from __future__ import annotations

import asyncio
from importlib.metadata import version

import typer

from genbi.agent import run_chat

app = typer.Typer(help="Talk-to-Your-Data GenBI CLI.", no_args_is_help=True)


@app.callback()
def _main() -> None:
    """Force Typer to keep subcommand routing even with a single command."""


@app.command()
def chat() -> None:
    """Start an interactive chat against the local Postgres."""
    asyncio.run(run_chat())


@app.command()
def version_cmd() -> None:
    """Print the installed genbi package version."""
    typer.echo(version("talk-to-your-data-lab"))


if __name__ == "__main__":
    app()
