# tests/test_cost_api.py
"""Tests for /api/cost/summary endpoint."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from agenticops.web.app import app

client = TestClient(app)


def test_cost_summary_endpoint():
    fake = {"totals": {"cost_usd": 5.0, "call_count": 2}, "series": [], "breakdown": []}
    with patch("agenticops.services.cost_service.cost_summary", return_value=fake):
        r = client.get("/api/cost/summary?period=30d&group_by=agent")
    assert r.status_code == 200
    assert r.json()["totals"]["cost_usd"] == 5.0


def test_cost_summary_period_shortcuts():
    """Verify period=7d, month, year all resolve without error."""
    fake = {"totals": {"cost_usd": 0}, "series": [], "breakdown": []}
    with patch("agenticops.services.cost_service.cost_summary", return_value=fake) as mock:
        for p in ("7d", "30d", "month", "year"):
            r = client.get(f"/api/cost/summary?period={p}")
            assert r.status_code == 200
        assert mock.call_count == 4


def test_cost_summary_custom_start_end():
    """Explicit start/end override period shorthand."""
    fake = {"totals": {"cost_usd": 1.0}, "series": [], "breakdown": []}
    with patch("agenticops.services.cost_service.cost_summary", return_value=fake) as mock:
        r = client.get(
            "/api/cost/summary?start=2026-06-01T00:00:00%2B00:00"
            "&end=2026-06-30T00:00:00%2B00:00&bucket=month"
        )
    assert r.status_code == 200
    call_kwargs = mock.call_args
    assert call_kwargs.kwargs["bucket"] == "month"


def test_cost_summary_filters_forwarded():
    """Filters (actor_type, agent_name, model_id) pass through to service."""
    fake = {"totals": {"cost_usd": 0}, "series": [], "breakdown": []}
    with patch("agenticops.services.cost_service.cost_summary", return_value=fake) as mock:
        r = client.get(
            "/api/cost/summary?actor_type=user&agent_name=rca&model_id=opus"
        )
    assert r.status_code == 200
    filters = mock.call_args.kwargs["filters"]
    assert filters == {"actor_type": "user", "agent_name": "rca", "model_id": "opus"}
