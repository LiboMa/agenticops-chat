"""Tests for services/graph_sync_service.py — sync control and lifecycle."""

import threading
import pytest
from unittest.mock import patch, MagicMock

from agenticops.config import settings


@pytest.fixture(autouse=True)
def _reset_module_state():
    """Reset module-level state between tests."""
    import agenticops.services.graph_sync_service as mod
    mod._sync_thread = None
    mod._stop_event.clear()
    yield
    mod._stop_event.set()  # ensure any running threads stop
    mod._sync_thread = None


class TestStartGraphSync:
    def test_disabled_does_not_start(self):
        from agenticops.services.graph_sync_service import start_graph_sync, _sync_thread
        import agenticops.services.graph_sync_service as mod

        original = settings.graph_sync_enabled
        settings.graph_sync_enabled = False
        try:
            start_graph_sync()
            assert mod._sync_thread is None
        finally:
            settings.graph_sync_enabled = original

    @patch("agenticops.services.graph_sync_service._sync_loop")
    def test_enabled_starts_thread(self, mock_loop):
        import agenticops.services.graph_sync_service as mod

        original = settings.graph_sync_enabled
        settings.graph_sync_enabled = True
        try:
            mod.start_graph_sync()
            assert mod._sync_thread is not None
            assert mod._sync_thread.daemon is True
            assert mod._sync_thread.name == "graph-sync"
            # Wait briefly for thread to start
            mod._sync_thread.join(timeout=1)
        finally:
            settings.graph_sync_enabled = original
            mod._stop_event.set()

    def test_double_start_reuses_alive_thread(self):
        """If thread is still alive, second start is a no-op."""
        import agenticops.services.graph_sync_service as mod

        original = settings.graph_sync_enabled
        settings.graph_sync_enabled = True
        try:
            # Use a blocking loop so the thread stays alive
            barrier = threading.Event()
            original_loop = mod._sync_loop

            def _blocking_loop():
                barrier.wait(timeout=5)

            with patch.object(mod, "_sync_loop", _blocking_loop):
                mod.start_graph_sync()
                first_thread = mod._sync_thread
                assert first_thread.is_alive()
                mod.start_graph_sync()  # second call — should be no-op
                assert mod._sync_thread is first_thread
                barrier.set()
                first_thread.join(timeout=2)
        finally:
            settings.graph_sync_enabled = original
            mod._stop_event.set()


class TestStopGraphSync:
    def test_stop_sets_event(self):
        from agenticops.services.graph_sync_service import stop_graph_sync, _stop_event
        import agenticops.services.graph_sync_service as mod
        mod._stop_event.clear()
        stop_graph_sync()
        assert mod._stop_event.is_set()


class TestSyncAll:
    @patch("agenticops.services.graph_sync_service.sync_region")
    @patch("boto3.client")
    @patch("agenticops.services.graph_sync_service._ensure_aws_session", create=True)
    def test_sync_all_calls_sync_region(self, mock_ensure, mock_boto, mock_sync_region):
        """sync_all should discover regions and call sync_region."""
        # Mock STS
        mock_sts = MagicMock()
        mock_sts.get_caller_identity.return_value = {"Account": "123456789012"}
        mock_boto.return_value = mock_sts
        mock_sync_region.return_value = {"vpcs": {}}

        # We need to also mock the import inside sync_all
        with patch("agenticops.graph.api._ensure_aws_session"):
            from agenticops.services.graph_sync_service import sync_all
            stats = sync_all()

        assert "regions" in stats
        mock_sync_region.assert_called()

    @patch("boto3.client")
    def test_sync_all_handles_sts_failure(self, mock_boto):
        """sync_all should handle STS failures gracefully."""
        mock_boto.side_effect = Exception("No credentials")

        with patch("agenticops.graph.api._ensure_aws_session"):
            with patch("agenticops.services.graph_sync_service.sync_region") as mock_sr:
                mock_sr.return_value = {"vpcs": {}}
                from agenticops.services.graph_sync_service import sync_all
                stats = sync_all()
                assert "regions" in stats


class TestSyncVpc:
    @patch("agenticops.graph.store.GraphStore")
    @patch("agenticops.graph.api._build_enriched_vpc_graph")
    def test_sync_vpc_calls_store(self, mock_build, mock_store_cls):
        mock_build.return_value = {"nodes": [], "edges": []}
        mock_store = MagicMock()
        mock_store.save_graph.return_value = {"nodes": 5, "edges": 3}
        mock_store_cls.return_value = mock_store

        from agenticops.services.graph_sync_service import sync_vpc
        result = sync_vpc("us-east-1", "vpc-123", account_id="111")
        assert result == {"nodes": 5, "edges": 3}
        mock_store.save_graph.assert_called_once()


class TestSyncRegion:
    @patch("agenticops.services.graph_sync_service.sync_vpc")
    @patch("agenticops.graph.api._ensure_aws_session")
    def test_sync_region_iterates_vpcs(self, mock_ensure, mock_sync_vpc):
        mock_sync_vpc.return_value = {"nodes": 2}

        mock_ec2 = MagicMock()
        mock_ec2.describe_vpcs.return_value = {
            "Vpcs": [{"VpcId": "vpc-aaa"}, {"VpcId": "vpc-bbb"}]
        }

        with patch("agenticops.graph.collectors._get_client", return_value=mock_ec2):
            from agenticops.services.graph_sync_service import sync_region
            stats = sync_region("us-east-1", account_id="123")

        assert "vpcs" in stats
        assert "vpc-aaa" in stats["vpcs"]
        assert "vpc-bbb" in stats["vpcs"]
        assert mock_sync_vpc.call_count == 2

    @patch("agenticops.graph.api._ensure_aws_session")
    def test_sync_region_handles_list_failure(self, mock_ensure):
        with patch("agenticops.graph.collectors._get_client", side_effect=Exception("boom")):
            from agenticops.services.graph_sync_service import sync_region
            stats = sync_region("us-east-1")
            assert stats == {"vpcs": {}}


class TestTriggerSyncForResource:
    @patch("agenticops.services.graph_sync_service._sync_for_resource")
    def test_trigger_starts_thread(self, mock_sync):
        from agenticops.services.graph_sync_service import trigger_sync_for_resource
        trigger_sync_for_resource("vpc-123")
        # Give thread a moment to start
        import time
        time.sleep(0.1)
        mock_sync.assert_called_with("vpc-123")

    @patch("agenticops.services.graph_sync_service.sync_vpc")
    def test_sync_for_resource_vpc_direct(self, mock_sync_vpc):
        from agenticops.services.graph_sync_service import _sync_for_resource
        _sync_for_resource("vpc-abc")
        mock_sync_vpc.assert_called_once()

    @patch("agenticops.graph.store.GraphStore")
    def test_sync_for_resource_lookup(self, mock_store_cls):
        """Non-VPC resource triggers graph lookup."""
        mock_store = MagicMock()
        mock_store.search_nodes.return_value = [{"vpc_id": "vpc-found", "region": "us-east-1"}]
        mock_store_cls.return_value = mock_store

        with patch("agenticops.services.graph_sync_service.sync_vpc") as mock_sync:
            from agenticops.services.graph_sync_service import _sync_for_resource
            _sync_for_resource("i-12345")
            mock_sync.assert_called_once_with("us-east-1", "vpc-found")

    @patch("agenticops.graph.store.GraphStore")
    def test_sync_for_resource_not_found(self, mock_store_cls):
        """When resource cannot be resolved, no error raised."""
        mock_store = MagicMock()
        mock_store.search_nodes.return_value = []
        mock_store_cls.return_value = mock_store

        from agenticops.services.graph_sync_service import _sync_for_resource
        _sync_for_resource("unknown-resource")  # should not raise
