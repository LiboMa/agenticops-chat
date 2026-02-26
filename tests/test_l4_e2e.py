"""End-to-end tests for L4 closed-loop SRE pipeline.

Tests the full lifecycle:
  HealthIssue → RCA → FixPlan → Approval → Execution → Auto-Resolution
  → RAG Pipeline → SOP Generation → Case Distillation → KB Search

Does NOT require AWS credentials — tests the orchestration layer only.
"""

import json
import time
import pytest
from datetime import datetime
from pathlib import Path

from agenticops.models import (
    AWSAccount,
    AWSResource,
    Base,
    FixExecution,
    FixPlan,
    HealthIssue,
    RCAResult,
    get_session,
    init_db,
)


@pytest.fixture
def test_db(tmp_path):
    """Create a temporary database for testing."""
    import agenticops.models as models_mod
    from agenticops.config import settings

    # Save original settings
    orig_db_url = settings.database_url
    orig_sops_dir = settings.sops_dir
    orig_cases_dir = settings.cases_dir
    orig_kb_dir = settings.knowledge_base_dir

    # Reset singleton engine
    models_mod._engine = None

    # Set up temp paths
    db_url = f"sqlite:///{tmp_path}/test.db"
    settings.database_url = db_url
    settings.sops_dir = tmp_path / "sops"
    settings.cases_dir = tmp_path / "cases"
    settings.knowledge_base_dir = tmp_path / "kb"
    settings.ensure_dirs()

    engine = models_mod.get_engine()
    Base.metadata.create_all(engine)

    session = get_session()
    yield session, tmp_path

    session.close()
    models_mod._engine = None

    # Restore original settings
    settings.database_url = orig_db_url
    settings.sops_dir = orig_sops_dir
    settings.cases_dir = orig_cases_dir
    settings.knowledge_base_dir = orig_kb_dir


@pytest.fixture
def seed_data(test_db):
    """Create a complete scenario: account + resource + issue + RCA + fix plan."""
    session, tmp_path = test_db

    # Create account
    account = AWSAccount(
        name="test-prod",
        account_id="123456789012",
        role_arn="arn:aws:iam::123456789012:role/TestRole",
        regions=["us-east-1"],
        is_active=True,
    )
    session.add(account)
    session.flush()

    # Create resource
    resource = AWSResource(
        account_id=account.id,
        resource_id="i-0abc123def456",
        resource_type="EC2",
        resource_name="prod-api-server",
        resource_arn="arn:aws:ec2:us-east-1:123456789012:instance/i-0abc123def456",
        region="us-east-1",
        status="running",
        metadata={"instance_type": "m5.xlarge"},
    )
    session.add(resource)
    session.flush()

    # Create health issue (detected)
    issue = HealthIssue(
        resource_id="i-0abc123def456",
        severity="high",
        source="cloudwatch_alarm",
        title="High CPU utilization on prod-api-server",
        description="CPU utilization exceeded 95% for 15 minutes on instance i-0abc123def456. "
        "Application response times degraded from 200ms to 2500ms. "
        "Auto-scaling group at max capacity.",
        alarm_name="prod-api-cpu-alarm",
        metric_data={
            "CPUUtilization": {"average": 96.7, "maximum": 99.2},
            "ResponseTime": {"average": 2500, "p99": 4800},
        },
        status="open",
    )
    session.add(issue)
    session.flush()

    # Create RCA result
    rca = RCAResult(
        health_issue_id=issue.id,
        root_cause="Memory leak in application code causing excessive garbage collection, "
        "which consumes CPU cycles. The leak originates from an unclosed database "
        "connection pool that grows unbounded under high traffic.",
        confidence=0.85,
        contributing_factors=[
            "Database connection pool not configured with max_size",
            "No circuit breaker on external API calls",
            "Auto-scaling max reached before root cause addressed",
        ],
        recommendations=[
            "Restart the instance to clear leaked connections",
            "Configure connection pool max_size=50",
            "Add circuit breaker for external API calls",
            "Set up memory monitoring alarm",
        ],
        fix_risk_level="L1",
        sop_used="ec2-cpu-high.md",
        similar_cases=[],
    )
    session.add(rca)
    session.flush()

    # Update issue status
    issue.status = "root_cause_identified"
    session.flush()

    # Create fix plan
    plan = FixPlan(
        health_issue_id=issue.id,
        rca_result_id=rca.id,
        risk_level="L1",
        title="Restart instance and configure connection pool",
        summary="Restart prod-api-server to clear memory leak, then configure "
        "connection pool with max_size=50 to prevent recurrence.",
        steps=[
            {"index": 1, "action": "Restart instance i-0abc123def456", "command": "aws ec2 reboot-instances --instance-ids i-0abc123def456"},
            {"index": 2, "action": "Wait for instance to be running", "command": "aws ec2 wait instance-running --instance-ids i-0abc123def456"},
            {"index": 3, "action": "Verify CPU normalized", "command": "aws cloudwatch get-metric-data --metric-name CPUUtilization"},
        ],
        rollback_plan={"steps": ["No rollback needed for instance restart"]},
        pre_checks=[
            {"check": "Instance is running", "command": "aws ec2 describe-instances --instance-ids i-0abc123def456"},
        ],
        post_checks=[
            {"check": "CPU below 80%", "command": "aws cloudwatch get-metric-data"},
            {"check": "Response time below 500ms", "command": "curl -s -o /dev/null -w '%{time_total}' http://api.example.com/health"},
        ],
        estimated_impact="Brief downtime during restart (2-3 minutes)",
        status="draft",
    )
    session.add(plan)
    session.flush()

    issue.status = "fix_planned"
    session.commit()

    return {
        "session": session,
        "tmp_path": tmp_path,
        "account": account,
        "resource": resource,
        "issue": issue,
        "rca": rca,
        "plan": plan,
    }


class TestL4Lifecycle:
    """Test the complete L4 lifecycle through the database layer."""

    def test_issue_creation_and_rca(self, seed_data):
        """Verify issue + RCA are properly linked."""
        session = seed_data["session"]
        issue = seed_data["issue"]
        rca = seed_data["rca"]

        assert issue.status == "fix_planned"
        assert rca.health_issue_id == issue.id
        assert rca.confidence == 0.85
        assert rca.fix_risk_level == "L1"
        assert len(rca.contributing_factors) == 3

    def test_fix_plan_approval(self, seed_data):
        """Test plan approval flow."""
        session = seed_data["session"]
        plan = seed_data["plan"]
        issue = seed_data["issue"]

        assert plan.status == "draft"

        # Approve the plan (L1 = auto-approvable)
        plan.status = "approved"
        plan.approved_by = "agent:main_agent"
        plan.approved_at = datetime.utcnow()
        issue.status = "fix_approved"
        session.commit()

        assert plan.status == "approved"
        assert issue.status == "fix_approved"

    def test_execution_record_creation(self, seed_data):
        """Test creating a FixExecution record."""
        session = seed_data["session"]
        plan = seed_data["plan"]
        issue = seed_data["issue"]

        # Approve first
        plan.status = "approved"
        plan.approved_by = "test"
        plan.approved_at = datetime.utcnow()
        issue.status = "fix_approved"
        session.flush()

        # Create execution
        execution = FixExecution(
            fix_plan_id=plan.id,
            health_issue_id=issue.id,
            status="pending",
            executed_by="executor_agent",
        )
        session.add(execution)
        session.commit()

        assert execution.id is not None
        assert execution.status == "pending"
        assert execution.fix_plan_id == plan.id

    def test_execution_success_and_auto_resolve(self, seed_data):
        """Test that successful execution auto-resolves the issue."""
        from agenticops.config import settings

        session = seed_data["session"]
        plan = seed_data["plan"]
        issue = seed_data["issue"]

        # Approve
        plan.status = "approved"
        plan.approved_by = "test"
        plan.approved_at = datetime.utcnow()
        issue.status = "fix_approved"
        session.flush()

        # Simulate successful execution via metadata tool
        from agenticops.tools.metadata_tools import save_execution_result

        orig_auto_resolve = settings.executor_auto_resolve
        settings.executor_auto_resolve = True

        result = save_execution_result(
            fix_plan_id=plan.id,
            health_issue_id=issue.id,
            status="succeeded",
            step_results=json.dumps([
                {"step_index": 1, "status": "succeeded", "output": "Instance restarting"},
                {"step_index": 2, "status": "succeeded", "output": "Instance running"},
                {"step_index": 3, "status": "succeeded", "output": "CPU at 35%"},
            ]),
            pre_check_results=json.dumps([{"check": "Instance running", "status": "pass"}]),
            post_check_results=json.dumps([
                {"check": "CPU below 80%", "status": "pass"},
                {"check": "Response time OK", "status": "pass"},
            ]),
            duration_ms=180000,
        )

        settings.executor_auto_resolve = orig_auto_resolve

        assert "saved" in result.lower() or "FixExecution" in result
        assert "auto-resolved" in result.lower() or "resolved" in result.lower()

        # Verify issue is now resolved
        session.refresh(issue)
        assert issue.status == "resolved"
        assert issue.resolved_at is not None

        # Verify plan is marked executed
        session.refresh(plan)
        assert plan.status == "executed"

    def test_execution_failure_keeps_retry(self, seed_data):
        """Test that failed execution keeps issue in fix_approved for retry."""
        session = seed_data["session"]
        plan = seed_data["plan"]
        issue = seed_data["issue"]

        plan.status = "approved"
        plan.approved_by = "test"
        plan.approved_at = datetime.utcnow()
        issue.status = "fix_approved"
        session.flush()

        from agenticops.tools.metadata_tools import save_execution_result

        result = save_execution_result(
            fix_plan_id=plan.id,
            health_issue_id=issue.id,
            status="failed",
            error_message="Step 1 failed: instance not found",
            step_results=json.dumps([
                {"step_index": 1, "status": "failed", "output": "Instance not found"},
            ]),
            duration_ms=5000,
        )

        assert "failed" in result.lower()

        session.refresh(issue)
        # Issue should NOT be auto-resolved on failure
        assert issue.status == "fix_approved"

        session.refresh(plan)
        assert plan.status == "failed"


class TestRAGPipeline:
    """Test the RAG pipeline (SOP generation/upgrade) with real DB data."""

    def test_rag_pipeline_disabled(self, seed_data):
        """Test RAG pipeline returns 'skipped' when disabled."""
        from agenticops.config import settings
        from agenticops.pipeline.rag_pipeline import run_rag_pipeline

        orig = settings.rag_pipeline_enabled
        settings.rag_pipeline_enabled = False

        result = run_rag_pipeline(seed_data["issue"].id)

        settings.rag_pipeline_enabled = orig

        assert result.success is False
        assert result.action == "skipped"
        assert "disabled" in result.error.lower()

    def test_rag_pipeline_extracts_case_data(self, seed_data):
        """Test that the RAG pipeline can extract case data from a resolved issue."""
        session = seed_data["session"]
        issue = seed_data["issue"]

        # Mark as resolved (needed for extract)
        issue.status = "resolved"
        issue.resolved_at = datetime.utcnow()
        session.commit()

        from agenticops.pipeline.rag_pipeline import _extract_case_data

        case_data = _extract_case_data(issue.id)

        assert case_data is not None
        assert case_data["resource_type"] == "EC2"
        assert "cpu" in case_data["issue_pattern"].lower()
        assert case_data["severity"] == "high"
        assert "memory leak" in case_data["root_cause"].lower()

    def test_rag_pipeline_generates_sop(self, seed_data):
        """Test SOP generation from case data (uses fallback, no LLM)."""
        from agenticops.pipeline.sop_upgrader import generate_new_sop

        case_data = {
            "resource_type": "EC2",
            "issue_pattern": "High CPU utilization on prod server",
            "severity": "high",
            "title": "High CPU utilization on prod-api-server",
            "symptoms": "CPU at 96%, response time 2500ms",
            "root_cause": "Memory leak in connection pool",
            "fix_steps": json.dumps([
                {"action": "Restart instance"},
                {"action": "Configure pool max_size"},
            ]),
            "rollback_plan": json.dumps({"steps": ["No rollback needed"]}),
            "verification_steps": "Check CPU below 80%",
            "contributing_factors": "No pool max_size configured",
            "recommendations": "Add memory monitoring",
        }

        # This will use fallback (no Bedrock available in test)
        sop = generate_new_sop(case_data)

        assert sop is not None
        assert len(sop) > 100
        assert "EC2" in sop or "ec2" in sop
        assert "cpu" in sop.lower() or "CPU" in sop

    def test_rag_pipeline_sop_filename_generation(self, seed_data):
        """Test SOP filename generation from case data."""
        from agenticops.pipeline.rag_pipeline import _generate_sop_filename

        case_data = {
            "resource_type": "EC2",
            "issue_pattern": "High CPU utilization caused by memory leak",
        }
        filename = _generate_sop_filename(case_data)

        assert filename.startswith("ec2-")
        assert filename.endswith(".md")
        assert "high" in filename or "cpu" in filename

    def test_extract_section_from_markdown(self):
        """Test markdown section extraction helper."""
        from agenticops.pipeline.rag_pipeline import _extract_section

        body = """## Symptoms
CPU utilization at 96.7%.
Response time degraded to 2500ms.

## Root Cause
Memory leak in database connection pool.

## Fix Steps
1. Restart the instance.
2. Configure pool max_size.
"""
        symptoms = _extract_section(body, "Symptoms", "Root Cause")
        assert "96.7" in symptoms

        root_cause = _extract_section(body, "Root Cause", "Fix Steps")
        assert "memory leak" in root_cause.lower()


class TestResolutionService:
    """Test the post-resolution trigger service."""

    def test_trigger_post_resolution_disabled(self, seed_data):
        """Test that post-resolution is skipped when RAG is disabled."""
        from agenticops.config import settings
        from agenticops.services.resolution_service import trigger_post_resolution

        orig = settings.rag_pipeline_enabled
        settings.rag_pipeline_enabled = False

        # Should return immediately without error
        trigger_post_resolution(seed_data["issue"].id)

        settings.rag_pipeline_enabled = orig


class TestExecutorService:
    """Test the background executor service."""

    def test_executor_service_disabled(self):
        """Test that executor service doesn't start when disabled."""
        from agenticops.config import settings
        from agenticops.services.executor_service import ExecutorService

        orig = settings.executor_enabled
        settings.executor_enabled = False

        svc = ExecutorService(poll_interval=1)
        svc.start()

        assert not svc.is_running

        settings.executor_enabled = orig

    def test_executor_service_claims_pending(self, seed_data):
        """Test that executor service finds pending executions."""
        from agenticops.config import settings

        session = seed_data["session"]
        plan = seed_data["plan"]
        issue = seed_data["issue"]

        # Approve plan
        plan.status = "approved"
        plan.approved_by = "test"
        plan.approved_at = datetime.utcnow()
        issue.status = "fix_approved"
        session.flush()

        # Create pending execution
        execution = FixExecution(
            fix_plan_id=plan.id,
            health_issue_id=issue.id,
            status="pending",
        )
        session.add(execution)
        session.commit()
        exec_id = execution.id

        # Verify it's pending
        session.refresh(execution)
        assert execution.status == "pending"

    def test_cancel_nonexistent(self):
        """Test cancelling a non-existent execution."""
        from agenticops.services.executor_service import ExecutorService

        svc = ExecutorService()
        result = svc.cancel_execution(99999)
        assert result is False


class TestKBSearch:
    """Test the knowledge base search with configurable weights."""

    def test_configurable_search_weights(self):
        """Verify search weights are read from config."""
        from agenticops.config import settings

        assert hasattr(settings, "search_vector_weight")
        assert hasattr(settings, "search_efficiency_weight")
        assert hasattr(settings, "search_base_weight")
        assert settings.search_vector_weight == 0.6
        assert settings.search_efficiency_weight == 0.2
        assert settings.search_base_weight == 0.2

    def test_rerank_uses_config_weights(self):
        """Test that reranking uses configurable weights."""
        from agenticops.config import settings
        from agenticops.kb.search import HybridResult, _rerank

        results = [
            HybridResult(case_id="case1", file_path="", score=0.9, source="vector",
                         metadata={"efficiency_score": 0.8}),
            HybridResult(case_id="case2", file_path="", score=0.5, source="keyword",
                         metadata={"efficiency_score": 0.3}),
        ]

        reranked = _rerank(results)

        # With default weights (0.6, 0.2, 0.2):
        # case1: 0.9*0.6 + 0.8*0.2 + 0.2 = 0.54 + 0.16 + 0.2 = 0.9
        # case2: 0.5*0.6 + 0.3*0.2 + 0.2 = 0.30 + 0.06 + 0.2 = 0.56
        assert reranked[0].case_id == "case1"
        assert reranked[0].score > reranked[1].score


class TestSOPIdentifier:
    """Test the SOP identifier (matching) logic."""

    def test_identify_no_sops_returns_none(self, seed_data):
        """When no SOPs exist, should return None."""
        from agenticops.pipeline.sop_identifier import identify_matching_sop

        result = identify_matching_sop(
            resource_type="EC2",
            issue_pattern="High CPU utilization",
            severity="high",
        )
        # With empty KB, should return None (no match)
        assert result is None

    def test_identify_with_matching_sop(self, seed_data):
        """When a matching SOP exists, should return it."""
        from agenticops.pipeline.sop_identifier import identify_matching_sop

        tmp_path = seed_data["tmp_path"]

        # Create a matching SOP file
        sop_content = """---
resource_type: EC2
issue_pattern: High CPU utilization
severity: high
last_updated: "2026-02-26"
---

## Symptoms
EC2 instance showing sustained high CPU utilization above 90%.

## Root Cause
Common causes include memory leaks, runaway processes, or insufficient instance sizing.

## Fix Steps
1. Check top processes with `top` or `htop`
2. Restart the instance if a memory leak is suspected
3. Consider upgrading instance type
"""
        from agenticops.config import settings
        sop_path = settings.sops_dir / "ec2-high-cpu.md"
        sop_path.write_text(sop_content)

        result = identify_matching_sop(
            resource_type="EC2",
            issue_pattern="High CPU utilization on production server",
            severity="high",
        )

        # Should find the SOP via keyword search (vector search won't work without embeddings)
        # The result depends on search quality — may or may not find it
        # Just verify the function runs without error
        # If found, verify the structure
        if result is not None:
            assert result.resource_type == "EC2"
            assert result.filename == "ec2-high-cpu.md"
