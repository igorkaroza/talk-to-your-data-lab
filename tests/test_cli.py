"""Tests for genbi.cli."""

from __future__ import annotations

from importlib.metadata import version

from typer.testing import CliRunner

from genbi.cli import app

runner = CliRunner()


def test_version_exit_code_and_output() -> None:
    result = runner.invoke(app, ["version-cmd"])
    assert result.exit_code == 0
    assert result.output.strip() == version("talk-to-your-data-lab")
