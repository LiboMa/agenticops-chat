"""Unit tests for agenticops.services.graph_sync_service module.

Covers: start_graph_sync, stop_graph_sync, sync_all, sync_region,
sync_vpc, trigger_sync_for_resource, _sync_loop.
"""

import threading
from unittest.mock import patch, MagicMock, call

import pytest

from agenticops.services import graph_sync_service
from agenticops.services.graph_sync_service import (
    start_graph_sync,
    stop_graph_sync,
    sync_all,
    sync_region,
    sync_vpc,
    trigger_sync_for_resource,
    _sync_loop,
    _sync_for_resource,
)


# ── start/stop tests ────────────────────────────────────────────────


class TestStartStopSync:
    def setup_method(self):
        """Reset module state between tests."""
        graph_sync_service._sync_thread = None
        graph_sync_service._stop_event = threading.Event()

    @patch("agenticops.services.graph_sync_service.settings")
    def test_start_disabled(self, mock_settings):
        mock_settings.graph_sync_enabled = False
        start_graph_sync()
        assert graph_sync_service._sync_thread is None

    @patch("agenticops.services.graph_sync_service._sync_loop")
    @patch("agenticops.services.graph_sync_service.settings")
    def test_start_enabled(self, mock_settings, mock_loop):
        mock_settings.graph_sync_enabled = True
        mock_settings.graph_sync_interval_minutes = 5
        start_graph_sync()
        assert graph_sync_service._sync_thread is not None
        assert graph_sync_service._sync_thread.daemon is True
        # Wait briefly for thread to start
        graph_sync_service._sync_thread.join(timeout=0.5)

    @patch("agenticops.services.graph_sync_service.settings")
    def test_start_already_running(self, mock_settings):
        mock_settings.graph_sync_enabled = True
        mock_settings.graph_sync_interval_minutes = 5
        # Create a fake alive thread
        fake_thread = MagicMock()
        fake_thread.is_alive.return_value = True
        graph_sync_service._sync_thread = fake_thread
        start_graph_sync()
        # Should not create new thread
        assert graph_sync_service._sync_thread is fake_thread

    def test_stop_sets_event(self):
        stop_graph_sync()
        assert graph_sync_service._stop_event.is_set()


# ── _sync_loop tests ────────────────────────────────────────────────


class TestSyncLoop:
    def setup_method(self):
        graph_sync_service._stop_event = threading.Event()

    @patch("agenticops.services.graph_sync_service.settings")
    def test_loop_calls_sync_all(self, mock_settings):
        mock_settings.graph_sync_interval_minutes = 1
        mock_settings.graph_node_ttl_hours = 24

        # Make is_set() return False once (enter loop), then True (exit wait)
        call_count = [0]
        original_event = graph_sync_service._stop_event

        def side_effect_is_set():
            call_count[0] += 1
            return call_count[0] > 1

        mock_store_mod = MagicMock()
        mock_store_mod.GraphStore.return_value.remove_stale_nodes.return_value = 0

        with patch.dict("sys.modules", {"agenticops.graph.store": mock_store_mod}):
            with patch.object(graph_sync_service, "sync_all", return_value={}) as mock_sa:
                with patch.object(graph_sync_service._stop_event, "is_set", side_effect=side_effect_is_set):
                    with patch.object(graph_sync_service._stop_event, "wait", return_value=True):
                        _sync_loop()
                mock_sa.assert_called_once()

    @patch("agenticops.services.graph_sync_service.settings")
    def test_loop_handles_sync_exception(self, mock_settings):
        mock_settings.graph_sync_interval_minutes = 1
        mock_settings.graph_node_ttl_hours = 24

        call_count = [0]

        def side_effect_is_set():
            call_count[0] += 1
            return call_count[0] > 1

        mock_store_mod = MagicMock()
        mock_store_mod.GraphStore.return_value.remove_stale_nodes.return_value = 0

        with patch.dict("sys.modules", {"agenticops.graph.store": mock_store_mod}):
            with patch.object(graph_sync_service, "sync_all", side_effect=RuntimeError("AWS error")):
                with patch.object(graph_sync_service._stop_event, "is_set", side_effect=side_effect_is_set):
                    with patch.object(graph_sync_service._stop_event, "wait", return_value=True):
                        # Should not raise
                        _sync_loop()


# ── sync_all tests ───────────────────────────────────────────────────


class TestSyncAll:
    @patch("agenticops.services.graph_sync_service.sync_region")
    @patch("agenticops.services.graph_sync_service.settings")
    @patch("boto3.client")
    def test_sync_all_success(self, mock_boto, mock_settings, mock_sync_region):
        mock_settings.bedrock_region = "us-east-1"
        mock_sts = MagicMock()
        mock_sts.get_caller_identity.return_value = {"Account": "123456789012"}
        mock_boto.return_value = mock_sts
        mock_sync_region.return_value = {"vpcs": {}}

        with patch("agenticops.services.graph_sync_service._ensure_aws_session", create=True):
            with patch.dict("sys.modules", {"agenticops.graph.api": MagicMock()}):
                # Patch the import inside
                with patch("agenticops.services.graph_sync_service.sync_region") as sr:
                    sr.return_value = {"vpcs": {}}
                    result = sync_all()

        assert "regions" in result

    @patch("agenticops.services.graph_sync_service.settings")
    @patch("boto3.client")
    def test_sync_all_sts_failure(self, mock_boto, mock_settings):
        mock_settings.bedrock_region = "us-east-1"
        mock_boto.side_effect = Exception("No credentials")

        with patch.dict("sys.modules", {"agenticops.graph.api": MagicMock()}):
            with patch("agenticops.services.graph_sync_service.sync_region") as sr:
                sr.return_value = {"vpcs": {}}
                result = sync_all()

        # Should still proceed with empty account_id
        assert "regions" in result


# ── sync_region tests ────────────────────────────────────────────────


class TestSyncRegion:
    @patch("agenticops.services.graph_sync_service.sync_vpc")
    def test_sync_region_success(self, mock_sync_vpc):
        mock_sync_vpc.return_value = {"nodes": 10}

        mock_api = MagicMock()
        mock_collectors = MagicMock()
        mock_ec2 = MagicMock()
        mock_ec2.describe_vpcs.return_value = {
            "Vpcs": [{"VpcId": "vpc-123"}, {"VpcId": "vpc-456"}]
        }
        mock_collectors._get_client.return_value = mock_ec2

        with patch.dict("sys.modules", {
            "agenticops.graph.api": mock_api,
            "agenticops.graph.collectors": mock_collectors,
        }):
            with patch("agenticops.services.graph_sync_service.sync_vpc") as sv:
                sv.return_value = {"nodes": 10}
                result = sync_region("us-east-1", account_id="123")

        assert "vpcs" in result

    @patch("agenticops.services.graph_sync_service.sync_vpc")
    def test_sync_region_vpc_failure(self, mock_sync_vpc):
        """Individual VPC failure should not crash the region sync."""
        mock_sync_vpc.side_effect = RuntimeError("VPC error")

        mock_api = MagicMock()
        mock_collectors = MagicMock()
        mock_ec2 = MagicMock()
        mock_ec2.describe_vpcs.return_value = {"Vpcs": [{"VpcId": "vpc-bad"}]}
        mock_collectors._get_client.return_value = mock_ec2

        with patch.dict("sys.modules", {
            "agenticops.graph.api": mock_api,
            "agenticops.graph.collectors": mock_collectors,
        }):
            result = sync_region("us-east-1")

        assert "vpcs" in result


# ── sync_vpc tests ───────────────────────────────────────────────────


class TestSyncVpc:
    def test_sync_vpc_calls_graph_store(self):
        mock_graph_api = MagicMock()
        mock_graph_api._build_enriched_vpc_graph.return_value = {"nodes": [], "edges": []}
        mock_store_class = MagicMock()
        mock_store_instance = MagicMock()
        mock_store_instance.save_graph.return_value = {"nodes": 5, "edges": 3}
        mock_store_class.return_value = mock_store_instance

        with patch.dict("sys.modules", {
            "agenticops.graph.api": mock_graph_api,
            "agenticops.graph.store": MagicMock(GraphStore=mock_store_class),
        }):
            result = sync_vpc("us-east-1", "vpc-123", account_id="111")

        assert result == {"nodes": 5, "edges": 3}


# ── trigger_sync_for_resource tests ──────────────────────────────────


class TestTriggerSyncForResource:
    @patch("agenticops.services.graph_sync_service._sync_for_resource")
    def test_trigger_starts_thread(self, mock_sync):
        trigger_sync_for_resource("vpc-123")
        # Give thread time to start
        import time
        time.sleep(0.1)
        # The function was called (in a thread)


class TestSyncForResource:
    @patch("agenticops.services.graph_sync_service.sync_vpc")
    @patch("agenticops.services.graph_sync_service.settings")
    def test_vpc_id_direct(self, mock_settings, mock_sync_vpc):
        mock_settings.bedrock_region = "us-east-1"
        mock_sync_vpc.return_value = {"nodes": 3}
        _sync_for_resource("vpc-abc123")
        mock_sync_vpc.assert_called_once_with("us-east-1", "vpc-abc123")

    @patch("agenticops.services.graph_sync_service.sync_vpc")
    @patch("agenticops.services.graph_sync_service.settings")
    def test_instance_id_lookup(self, mock_settings, mock_sync_vpc):
        mock_settings.bedrock_region = "us-east-1"
        mock_sync_vpc.return_value = {"nodes": 3}

        mock_store = MagicMock()
        mock_store.search_nodes.return_value = [{"vpc_id": "vpc-found", "region": "us-west-2"}]

        with patch.dict("sys.modules", {
            "agenticops.graph.store": MagicMock(GraphStore=MagicMock(return_value=mock_store)),
        }):
            _sync_for_resource("i-0abc123")

        mock_sync_vpc.assert_called_once_with("us-west-2", "vpc-found")

    @patch("agenticops.services.graph_sync_service.settings")
    def test_resource_not_found(self, mock_settings):
        mock_settings.bedrock_region = "us-east-1"

        mock_store = MagicMock()
        mock_store.search_nodes.return_value = []

        with patch.dict("sys.modules", {
            "agenticops.graph.store": MagicMock(GraphStore=MagicMock(return_value=mock_store)),
        }):
            # Should not raise
            _sync_for_resource("unknown-resource")

    @patch("agenticops.services.graph_sync_service.settings")
    def test_exception_handled(self, mock_settings):
        mock_settings.bedrock_region = "us-east-1"

        with patch.dict("sys.modules", {
            "agenticops.graph.store": MagicMock(side_effect=ImportError("no module")),
        }):
            # Should not raise
            _sync_for_resource("i-broken")
