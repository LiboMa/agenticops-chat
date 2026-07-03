# tests/test_cli_cost.py
"""Test aiops cost CLI command."""

from unittest.mock import patch

from typer.testing import CliRunner

from agenticops.cli.main import app

runner = CliRunner()


def test_aiops_cost_runs():
    fake = {
        "totals": {"cost_usd": 5.0, "total_tokens": 3300, "cache_hit_pct": 60.0, "call_count": 2},
        "series": [],
        "breakdown": [
            {"key": "rca", "calls": 1, "tokens": 1500, "cache_hit_pct": 0.0, "cost_usd": 2.0},
            {"key": "sre", "calls": 1, "tokens": 1800, "cache_hit_pct": 80.0, "cost_usd": 3.0},
        ],
    }
    with patch("agenticops.services.cost_service.cost_summary", return_value=fake):
        res = runner.invoke(app, ["cost", "--period", "month", "--by", "agent"])
    assert res.exit_code == 0
    assert "5.0" in res.output or "$5" in res.output
    assert "rca" in res.output


def test_aiops_cost_period_day():
    fake = {
        "totals": {"cost_usd": 1.5, "total_tokens": 1000, "cache_hit_pct": 50.0, "call_count": 3},
        "series": [],
        "breakdown": [],
    }
    with patch("agenticops.services.cost_service.cost_summary", return_value=fake):
        res = runner.invoke(app, ["cost", "--period", "day"])
    assert res.exit_code == 0
    assert "1.5" in res.output or "$1" in res.output
