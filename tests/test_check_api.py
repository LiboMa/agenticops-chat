"""Tests for POST /api/health-check endpoint."""
import pytest
from unittest.mock import patch, AsyncMock
from starlette.testclient import TestClient
from agenticops.web.app import app
from agenticops.checker.engine import CheckResult, AccountCheckResult


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def mock_check_result():
    return CheckResult(
        accounts=[
            AccountCheckResult(
                account_id=1, account_name="prod", provider="aws",
                issues_created=2, duration_s=45.0, errors=[],
            ),
            AccountCheckResult(
                account_id=2, account_name="staging", provider="aws",
                issues_created=0, duration_s=30.0, errors=["timeout on CloudWatch"],
            ),
        ],
        total_issues=2,
        duration_s=50.0,
    )


class TestHealthCheckAPI:
    def test_trigger_health_check(self, client, mock_check_result):
        """Test basic health check endpoint returns correct structure."""
        with patch("agenticops.checker.check_accounts_parallel", new_callable=AsyncMock, return_value=mock_check_result):
            resp = client.post("/api/health-check", json={})

        assert resp.status_code == 200
        data = resp.json()
        assert data["total_issues"] == 2
        assert data["duration_s"] == 50.0
        assert len(data["accounts"]) == 2

        # Check first account
        acc1 = data["accounts"][0]
        assert acc1["account_id"] == 1
        assert acc1["account_name"] == "prod"
        assert acc1["provider"] == "aws"
        assert acc1["issues_created"] == 2
        assert acc1["duration_s"] == 45.0
        assert acc1["errors"] == []

        # Check second account with errors
        acc2 = data["accounts"][1]
        assert acc2["account_id"] == 2
        assert acc2["issues_created"] == 0
        assert len(acc2["errors"]) == 1
        assert "timeout" in acc2["errors"][0].lower()

    def test_health_check_with_params(self, client, mock_check_result):
        """Test passing account_ids, scope, and deep parameters."""
        with patch("agenticops.checker.check_accounts_parallel", new_callable=AsyncMock, return_value=mock_check_result) as mock_check:
            resp = client.post("/api/health-check", json={
                "account_ids": [1, 2],
                "scope": "EC2",
                "deep": True,
            })

        assert resp.status_code == 200
        # Verify the mock was called with correct params
        mock_check.assert_called_once_with(
            account_ids=[1, 2],
            scope="EC2",
            deep=True,
        )

    def test_health_check_empty_result(self, client):
        """Test with no accounts."""
        empty_result = CheckResult(accounts=[], total_issues=0, duration_s=0.1)
        with patch("agenticops.checker.check_accounts_parallel", new_callable=AsyncMock, return_value=empty_result):
            resp = client.post("/api/health-check", json={})

        assert resp.status_code == 200
        data = resp.json()
        assert data["total_issues"] == 0
        assert len(data["accounts"]) == 0

    def test_health_check_default_values(self, client, mock_check_result):
        """Test default parameter values."""
        with patch("agenticops.checker.check_accounts_parallel", new_callable=AsyncMock, return_value=mock_check_result) as mock_check:
            resp = client.post("/api/health-check", json={})

        assert resp.status_code == 200
        # Verify defaults: account_ids=None, scope="all", deep=False
        mock_check.assert_called_once_with(
            account_ids=None,
            scope="all",
            deep=False,
        )

    def test_health_check_partial_params(self, client, mock_check_result):
        """Test with only some parameters specified."""
        with patch("agenticops.checker.check_accounts_parallel", new_callable=AsyncMock, return_value=mock_check_result) as mock_check:
            resp = client.post("/api/health-check", json={
                "scope": "RDS",
            })

        assert resp.status_code == 200
        mock_check.assert_called_once_with(
            account_ids=None,
            scope="RDS",
            deep=False,
        )
