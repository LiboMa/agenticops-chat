"""Test POST /api/scan endpoint."""
import pytest
from unittest.mock import patch, AsyncMock
from starlette.testclient import TestClient
from agenticops.web.app import app
from agenticops.scanner.engine import ScanResult, AccountScanResult


@pytest.fixture
def client():
    return TestClient(app)


def test_scan_endpoint_returns_result(client):
    mock_result = ScanResult(
        accounts=[AccountScanResult(
            account_id=1, account_name="test-aws", provider="aws",
            resources_found=5, resources_updated=2, regions_scanned=["us-east-1"],
        )],
        total_found=5, total_updated=2, duration_s=1.5,
    )
    with patch("agenticops.scanner.scan_accounts_parallel", new_callable=AsyncMock, return_value=mock_result):
        resp = client.post("/api/scan", json={})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_found"] == 5
    assert len(data["accounts"]) == 1


def test_scan_endpoint_with_filters(client):
    mock_result = ScanResult(total_found=0, duration_s=0.1)
    with patch("agenticops.scanner.scan_accounts_parallel", new_callable=AsyncMock, return_value=mock_result):
        resp = client.post("/api/scan", json={
            "account_ids": [1, 2],
            "focus": "computing",
            "regions": ["us-east-1"],
        })
    assert resp.status_code == 200
