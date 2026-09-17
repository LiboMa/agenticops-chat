# Change Management P1 — Plan A: 地基与账本（S0 + S1）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改变任何现有用户可见行为的前提下，给 FixPlan 补上状态机校验器、把 `fix_plans` 泛化为两种来源的 Plan 表、新增 `change_requests` 与 `command_audits` 表、完成 SQLite 重建迁移，并建立 Actor / Run Context / authz 影子模式 / 两本审计账本——这是 Plan B（变更闭环）与 Plan C（前端与 E2E）的共同地基。

**Architecture:** 单一 Plan 表（`fix_plans` + `plan_kind`）承载 fix 与 change 两种来源；`change_requests` 是 ITSM 工单；两个代码级状态机校验器替换全部直接赋值；身份由 `auth/actor.py` 解析、`run_context.py` 的 ContextVar 传递、`auth/authz.py` 按 `config/rbac.yaml` 判定（默认影子模式）；决策落 `audit_logs`（与状态变更同事务），写级命令落 `command_audits`（fail-soft）。

**Tech Stack:** Python 3.11, SQLAlchemy 2.x（SQLite 默认 / PostgreSQL），FastAPI, Strands `@tool`, pytest。

**Spec:** `docs/superpowers/specs/2026-09-16-change-management-p1-design.md`（§3.1-3.4、§4、§5、§6、§7 的地基部分）

## Global Constraints

- 一律在项目 `.venv` 里跑：`source /Users/malibo/MyDev/AgenticOps/.venv/bin/activate`；测试从仓库根目录跑 `python -m pytest`。**不要用** `/Users/malibo/MyDev/venv`（starlette 版本坏）。
- 全量测试约 2 分钟：`python -m pytest tests/ -q > /tmp/pytest-full.log 2>&1; tail -20 /tmp/pytest-full.log`，别管进 `tail`。唯一已知预期失败：`tests/test_web_tools.py`（本机 DNS 假失败）。
- **行为零变化**是 Plan A 的验收基线：完成后现有全量测试必须绿（除上述假失败）；fix 流对用户可见的行为不变，只多出审计行与身份绑定。
- 配置：`config.py` 只定义 schema（`Field(default=…, description="… (AIOPS_X)")`），值同时写进 `config/settings.yaml`，CLAUDE.md 配置表加行。优先级 env > .env > yaml > Field 默认。
- 凭证铁律不变：任何云调用都经 provider 层；本计划不新增云调用。
- 每个 Task 结束 `git commit`（只加本 Task 的文件；工作区里其他未相关改动——`agent-memory/`、`skills/*/SKILL.md`、`RAW-Idea-latest-v3.md`——**绝不**加进来）。**不 push**：P1 全部完成、live E2E 通过、主人确认后才 `git push --no-verify`。
- 受保护文件 `RAW-Idea-latest-v3.md`、`RAW-Creative-Idea.md`、`docs/use-cases/*`、`docs/MVP-1.0.0-RELEASE.md` 不碰。
- SQLite 外键约束在本项目**未启用**（没有 `PRAGMA foreign_keys=ON`），表重建不需要切换该 pragma；PostgreSQL 走 `ALTER COLUMN DROP NOT NULL`。

## 跨计划接口契约（Plan B / Plan C 依赖这些名字，不可改）

| 符号 | 位置 | 说明 |
|---|---|---|
| `ChangeRequest`、`VALID_CHANGE_STATUSES`、`CHANGE_TERMINAL_STATUSES`、`CHANGE_TRANSITIONS`、`validate_change_transition(current, new)`、`transition_change(cr, new_status)` | `agenticops.models` | 工单模型与状态机 |
| `VALID_PLAN_STATUSES`、`PLAN_TRANSITIONS`、`validate_plan_transition(current, new)`、`transition_plan(plan, new_status)` | `agenticops.models` | Plan 状态机 |
| `FixPlan.plan_kind`、`.change_request_id`、`.rejected_by`、`.rejected_at`、`.rejection_reason`、`.updated_at`、`.change_request` | `agenticops.models` | Plan 泛化列 |
| `CommandAudit` | `agenticops.models` | 命令账本表 `command_audits` |
| `PipelineEvent.change_request_id`；`log_event(health_issue_id, …, change_request_id=None)`；`get_timeline(health_issue_id=None, change_request_id=None)` | `agenticops.services.pipeline_events` | 事件二选一 |
| `AuditLog.actor`；`AuditService.log(..., actor=None, session=None)`；`Actions.*`、`EntityTypes.CHANGE_REQUEST/FIX_PLAN`；`AuditService.maybe_prune_daily()` | `agenticops.audit` | 决策账本 |
| `RunContext`、`get_run_context()`、`set_run_context(ctx)`、`reset_run_context(token)`、`run_context(**fields)`、`update_run_context(**fields)` | `agenticops.run_context` | 请求/任务级上下文 |
| `Actor(kind, id, user_id, permissions)`、`.key`、`actor_from_request(request)`、`cli_actor()`、`agent_actor(name)`、`im_actor(platform, sender_id)`、`web_anonymous_actor()`、`parse_actor(text)` | `agenticops.auth.actor` | 身份解析 |
| `AuthzDenied`、`check(actor, permission, subject=None)`、`get_rbac_policy(reload=False)`、`PERMISSIONS` | `agenticops.auth.authz` | 授权检查点 |
| `current_actor(request)` FastAPI 依赖 | `agenticops.web.deps` | 取 actor 并设置 Run Context |
| `record_command(*, tool, tier, command, outcome, account="", region="", target="", exit_code=None, output_excerpt="", duration_ms=0, reason="")` | `agenticops.services.command_audit` | 命令账本写入 |
| `PolicyEngine.change_required_match(command) -> Optional[str]`；`get_policy_engine().change_required_match(...)` | `agenticops.services.policy_engine` | 高风险写命令判定 |
| settings: `rbac_enforce`, `rbac_file`, `command_audit_enabled`, `audit_retention_days` | `agenticops.config` | 新配置项 |

## File Structure

| 文件 | 责任 | Task |
|---|---|---|
| `src/agenticops/models.py` | Plan/Change 状态机、`ChangeRequest`、`CommandAudit`、`fix_plans` 泛化列 + CHECK、`init_db` 2.6.0 迁移 | 1, 2, 3 |
| `src/agenticops/audit/models.py` | `AuditLog.actor` | 2 |
| `src/agenticops/audit/service.py` | `log(actor, session)`、新 Actions/EntityTypes、每日保留期清理 | 7 |
| `src/agenticops/run_context.py`（新） | ContextVar 载体 | 5 |
| `src/agenticops/auth/actor.py`（新） | Actor 数据类与六种来源解析 | 6 |
| `src/agenticops/auth/authz.py`（新） | rbac.yaml 加载、`check`、影子模式 | 6 |
| `config/rbac.yaml`（新） | 权限矩阵 + 两类结构化规则 | 6 |
| `src/agenticops/web/deps.py`（新） | `current_actor` 依赖 | 8 |
| `src/agenticops/web/app.py` | fix-plan approve/reject/execute/list 端点加固；chat 处理器设置 Run Context | 4, 8, 11 |
| `src/agenticops/web/schemas.py` | `FixPlanUpdate` 收紧、`FixPlanResponse` 新字段、审批/拒绝请求体、`AuditLogResponse.actor` | 7, 8 |
| `src/agenticops/tools/metadata_tools.py` | `approve_fix_plan`/`save_execution_result` 走校验器 + authz + 审计 | 4, 9 |
| `src/agenticops/services/pipeline_service.py` | 自动审批走校验器 + 审计；线程设置 Run Context | 4, 9, 11 |
| `src/agenticops/services/executor_service.py` | `_mark_crashed` 走校验器；worker 设置 Run Context | 4, 11 |
| `src/agenticops/cli/main.py` | `/approve` `/execute` 身份绑定 + 校验器 + 审计；REPL/headless 设置 Run Context | 4, 9, 11 |
| `src/agenticops/services/command_audit.py`（新） | `record_command` | 10 |
| `src/agenticops/services/policy_engine.py` + `config/policies.yaml` | `change_required` 段与匹配器 | 10 |
| `src/agenticops/tools/aws_cli_tool.py`、`src/agenticops/skills/execution.py`、`src/agenticops/skills/tools.py` | 写级命令记账 + `change_required` 拒绝 | 10 |
| `src/agenticops/im/feishu_ws.py`、`src/agenticops/im/slack_ws.py` | IM 入口设置 Run Context | 11 |
| `src/agenticops/config.py`、`config/settings.yaml`、`CLAUDE.md` | 四个新配置项 | 6, 7, 10 |
| `tests/test_change_state_machine.py`、`tests/test_change_schema.py`、`tests/test_migration_2_6_0.py`、`tests/test_plan_transition_enforcement.py`、`tests/test_run_context.py`、`tests/test_authz.py`、`tests/test_audit_service_actor.py`、`tests/test_fix_plan_hardening_api.py`、`tests/test_plan_approval_audit.py`、`tests/test_command_audit.py`、`tests/test_run_context_entrypoints.py` | 每个 Task 一份测试 | 1-11 |

---

### Task 1: Plan 与 ChangeRequest 状态机校验器 + `ChangeRequest` 模型

**Files:**
- Modify: `src/agenticops/models.py`（在 `FIXPLAN_LOCKED_STATUSES = {...}`（约 :501）之后新增两段；`ChangeRequest` 类放在 `class FixPlan` 之前）
- Test: `tests/test_change_state_machine.py`

**Interfaces:**
- Produces: `VALID_PLAN_STATUSES`, `PLAN_TRANSITIONS`, `validate_plan_transition(current: str, new: str) -> None`, `transition_plan(plan, new_status: str) -> None`；`ChangeRequest`；`VALID_CHANGE_STATUSES`, `CHANGE_TERMINAL_STATUSES`, `CHANGE_TRANSITIONS`, `validate_change_transition(current, new) -> None`, `transition_change(cr, new_status) -> None`。两个校验器抛现有的 `InvalidStatusTransition`（未知状态抛 `ValueError`）。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_change_state_machine.py
"""State-machine tests for FixPlan (any plan_kind) and ChangeRequest (MVP-2.6.0)."""
import pytest

from agenticops.models import (
    CHANGE_TERMINAL_STATUSES,
    CHANGE_TRANSITIONS,
    PLAN_TRANSITIONS,
    VALID_CHANGE_STATUSES,
    VALID_PLAN_STATUSES,
    InvalidStatusTransition,
    validate_change_transition,
    validate_plan_transition,
)


def _invalid_edges(transitions: dict, valid: set) -> list[tuple[str, str]]:
    return [
        (src, dst)
        for src in transitions
        for dst in sorted(valid)
        if dst != src and dst not in transitions[src]
    ]


class TestPlanTransitions:
    @pytest.mark.parametrize("cur,new", [(s, d) for s, ds in PLAN_TRANSITIONS.items() for d in sorted(ds)])
    def test_valid_edge(self, cur, new):
        validate_plan_transition(cur, new)

    @pytest.mark.parametrize("cur,new", _invalid_edges(PLAN_TRANSITIONS, VALID_PLAN_STATUSES))
    def test_invalid_edge(self, cur, new):
        with pytest.raises(InvalidStatusTransition):
            validate_plan_transition(cur, new)

    def test_same_status_is_noop(self):
        validate_plan_transition("approved", "approved")

    def test_unknown_status_raises_value_error(self):
        with pytest.raises(ValueError):
            validate_plan_transition("draft", "bogus")

    def test_terminal_states_have_no_exits(self):
        for s in ("executed", "failed", "rejected"):
            assert PLAN_TRANSITIONS[s] == set()

    def test_draft_can_be_auto_approved(self):
        validate_plan_transition("draft", "approved")

    def test_executed_cannot_be_reapproved(self):
        with pytest.raises(InvalidStatusTransition):
            validate_plan_transition("executed", "approved")

    def test_every_status_is_a_key(self):
        assert set(PLAN_TRANSITIONS) == VALID_PLAN_STATUSES


class TestChangeTransitions:
    @pytest.mark.parametrize("cur,new", [(s, d) for s, ds in CHANGE_TRANSITIONS.items() for d in sorted(ds)])
    def test_valid_edge(self, cur, new):
        validate_change_transition(cur, new)

    @pytest.mark.parametrize("cur,new", _invalid_edges(CHANGE_TRANSITIONS, VALID_CHANGE_STATUSES))
    def test_invalid_edge(self, cur, new):
        with pytest.raises(InvalidStatusTransition):
            validate_change_transition(cur, new)

    def test_terminal_set(self):
        assert CHANGE_TERMINAL_STATUSES == {"completed", "failed", "rolled_back", "rejected", "cancelled"}
        for s in CHANGE_TERMINAL_STATUSES:
            assert CHANGE_TRANSITIONS[s] == set()

    def test_watchdog_can_roll_review_back_to_draft(self):
        validate_change_transition("under_review", "draft")

    def test_needs_review_cannot_be_reapproved(self):
        with pytest.raises(InvalidStatusTransition):
            validate_change_transition("needs_review", "approved")

    def test_needs_review_resolves_to_completed_or_failed(self):
        validate_change_transition("needs_review", "completed")
        validate_change_transition("needs_review", "failed")

    def test_every_status_is_a_key(self):
        assert set(CHANGE_TRANSITIONS) == VALID_CHANGE_STATUSES


class TestTransitionHelpers:
    def test_transition_plan_sets_status_and_updated_at(self):
        from types import SimpleNamespace
        from agenticops.models import transition_plan
        plan = SimpleNamespace(status="draft", updated_at=None)
        transition_plan(plan, "approved")
        assert plan.status == "approved"
        assert plan.updated_at is not None

    def test_transition_plan_rejects_illegal_edge(self):
        from types import SimpleNamespace
        from agenticops.models import transition_plan
        plan = SimpleNamespace(status="executed", updated_at=None)
        with pytest.raises(InvalidStatusTransition):
            transition_plan(plan, "approved")
        assert plan.status == "executed"

    def test_transition_change_stamps_closed_at_on_terminal(self):
        from types import SimpleNamespace
        from agenticops.models import transition_change
        cr = SimpleNamespace(status="executing", updated_at=None, closed_at=None)
        transition_change(cr, "completed")
        assert cr.status == "completed"
        assert cr.closed_at is not None
        cr2 = SimpleNamespace(status="draft", updated_at=None, closed_at=None)
        transition_change(cr2, "under_review")
        assert cr2.closed_at is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_change_state_machine.py -q`
Expected: FAIL — `ImportError: cannot import name 'CHANGE_TERMINAL_STATUSES'`

- [ ] **Step 3: 在 `models.py` 加状态机与模型**

在 `FIXPLAN_LOCKED_STATUSES = {"pending_approval", "approved", "executing"}` 之后插入：

```python
# ── FixPlan state machine (MVP-2.6.0) ─────────────────────────────────
# Applies to BOTH plan kinds (fix | change). Replaces the direct status
# assignments that used to live in metadata_tools / pipeline_service /
# app.py / cli. Terminal: executed, failed, rejected.

VALID_PLAN_STATUSES = {
    "draft", "pending_approval", "approved", "executing", "executed", "failed", "rejected",
}

PLAN_TRANSITIONS: dict[str, set[str]] = {
    "draft":            {"pending_approval", "approved", "rejected"},
    "pending_approval": {"approved", "rejected"},
    "approved":         {"executing", "rejected"},   # rejected from approved = withdrawn before execution
    "executing":        {"executed", "failed"},
    "executed":         set(),
    "failed":           set(),
    "rejected":         set(),
}


def validate_plan_transition(current: str, new: str) -> None:
    """Validate a FixPlan status transition (raises InvalidStatusTransition / ValueError)."""
    if new not in VALID_PLAN_STATUSES:
        raise ValueError(f"Invalid plan status '{new}'. Valid: {', '.join(sorted(VALID_PLAN_STATUSES))}")
    if current == new:
        return
    allowed = PLAN_TRANSITIONS.get(current, set())
    if new not in allowed:
        raise InvalidStatusTransition(
            f"Cannot transition plan from '{current}' to '{new}'. "
            f"Allowed from '{current}': {', '.join(sorted(allowed)) or 'none (terminal)'}"
        )


def transition_plan(plan, new_status: str) -> None:
    """Validate and apply a FixPlan status change; stamps updated_at."""
    validate_plan_transition(plan.status, new_status)
    plan.status = new_status
    plan.updated_at = datetime.now(timezone.utc)


# ── ChangeRequest (MVP-2.6.0 Change Management) ───────────────────────

VALID_CHANGE_STATUSES = {
    "draft", "under_review", "needs_clarification", "planned", "approved",
    "executing", "needs_review", "completed", "failed", "rolled_back", "rejected", "cancelled",
}
CHANGE_TERMINAL_STATUSES = {"completed", "failed", "rolled_back", "rejected", "cancelled"}

CHANGE_TRANSITIONS: dict[str, set[str]] = {
    "draft":               {"under_review", "cancelled"},
    "under_review":        {"planned", "needs_clarification", "rejected", "draft"},  # draft = watchdog rollback
    "needs_clarification": {"under_review", "cancelled"},
    "planned":             {"approved", "rejected", "cancelled"},
    "approved":            {"executing", "cancelled"},
    "executing":           {"completed", "failed", "rolled_back", "needs_review"},
    "needs_review":        {"completed", "failed"},  # human verdict; a redo is a NEW change request
    "completed":           set(),
    "failed":              set(),
    "rolled_back":         set(),
    "rejected":            set(),
    "cancelled":           set(),
}


def validate_change_transition(current: str, new: str) -> None:
    """Validate a ChangeRequest status transition (raises InvalidStatusTransition / ValueError)."""
    if new not in VALID_CHANGE_STATUSES:
        raise ValueError(f"Invalid change status '{new}'. Valid: {', '.join(sorted(VALID_CHANGE_STATUSES))}")
    if current == new:
        return
    allowed = CHANGE_TRANSITIONS.get(current, set())
    if new not in allowed:
        raise InvalidStatusTransition(
            f"Cannot transition change from '{current}' to '{new}'. "
            f"Allowed from '{current}': {', '.join(sorted(allowed)) or 'none (terminal)'}"
        )


def transition_change(cr, new_status: str) -> None:
    """Validate and apply a ChangeRequest status change; stamps updated_at / closed_at."""
    validate_change_transition(cr.status, new_status)
    cr.status = new_status
    now = datetime.now(timezone.utc)
    cr.updated_at = now
    if new_status in CHANGE_TERMINAL_STATUSES:
        cr.closed_at = now


class ChangeRequest(Base):
    """ITSM change ticket: who wants what changed, reviewed by SRE, approved, executed via a Plan."""

    __tablename__ = "change_requests"
    __table_args__ = (
        Index("idx_change_request_status", "status"),
        Index("idx_change_request_requested_by", "requested_by"),
        Index("idx_change_request_account", "account_id"),
        Index("idx_change_request_created", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text)
    justification: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(20), default="api")  # chat|web|cli|im|webhook|api
    requested_by: Mapped[str] = mapped_column(String(100), index=True)  # actor key, e.g. user:admin
    requester_user_id: Mapped[Optional[int]] = mapped_column(nullable=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    account_id: Mapped[Optional[int]] = mapped_column(ForeignKey("cloud_accounts.id"), nullable=True)
    target_hints: Mapped[list] = mapped_column(JSON, default=list)  # raw strings the requester typed (ids/ARNs/names)
    target_resources: Mapped[list] = mapped_column(JSON, default=list)  # GROUNDED only: [{resource_id, resource_type, db_id, region, evidence}]
    requested_change_type: Mapped[str] = mapped_column(String(20), default="normal")  # normal|emergency
    effective_change_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # standard|normal|emergency
    risk_level: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # L0-L3
    action_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # tag|scale|config|network|iam|delete|other
    status: Mapped[str] = mapped_column(String(30), default="draft", index=True)
    review_verdict: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    review_reasons: Mapped[list] = mapped_column(JSON, default=list)
    reviewed_by: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    policy_rule: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    policy_action: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    approved_by: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    approver_user_id: Mapped[Optional[int]] = mapped_column(nullable=True)
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    approval_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    rejected_by: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    rejected_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    rejection_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    trace_id: Mapped[Optional[str]] = mapped_column(String(20), nullable=True, index=True)
    chat_session_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Relationships
    plans: Mapped[list["FixPlan"]] = relationship(back_populates="change_request")
```

`Index` 已在 models.py 顶部 import（`from sqlalchemy import ... Index`）；若没有 `CheckConstraint`，Task 2 会加。

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_change_state_machine.py -q`
Expected: 全部 PASS（参数化边约 60 条）

- [ ] **Step 5: 全量回归确认零破坏**

Run: `python -m pytest tests/ -q -x --deselect tests/test_web_tools.py > /tmp/pytest-t1.log 2>&1; tail -5 /tmp/pytest-t1.log`
Expected: passed（新增模型不影响旧测试；`FixPlan.change_request` back_populates 在 Task 2 才加——如果 SQLAlchemy 在 mapper 配置时抱怨 `back_populates="change_request"` 不存在，暂时把 `plans` 关系的 `back_populates` 去掉，Task 2 再补）

- [ ] **Step 6: Commit**

```bash
git add src/agenticops/models.py tests/test_change_state_machine.py
git commit -m "feat(models): plan + change-request state machines and ChangeRequest table (MVP-2.6.0 S0)"
```

---

### Task 2: `fix_plans` 泛化列 + CHECK、`fix_executions`/`pipeline_events` 可空、`CommandAudit`、`AuditLog.actor`

**Files:**
- Modify: `src/agenticops/models.py`（`class FixPlan` :470-496、`class FixExecution` :509-541、`class PipelineEvent` :544-567；新增 `class CommandAudit`）
- Modify: `src/agenticops/audit/models.py`（`AuditLog` 加 `actor`）
- Test: `tests/test_change_schema.py`

**Interfaces:**
- Produces: `FixPlan.plan_kind`（`"fix"|"change"`, server_default `"fix"`）、`FixPlan.change_request_id`、`FixPlan.rejected_by/rejected_at/rejection_reason/updated_at`、`FixPlan.change_request` 关系；CHECK `ck_fix_plans_origin`；`FixExecution.health_issue_id: Optional`；`PipelineEvent.health_issue_id: Optional` + `PipelineEvent.change_request_id`；`CommandAudit`；`AuditLog.actor`。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_change_schema.py
"""Schema tests for the generalized plan table, command_audits and audit_logs.actor (MVP-2.6.0)."""
import pytest
from sqlalchemy.exc import IntegrityError

from agenticops.models import (
    Base, ChangeRequest, CommandAudit, FixExecution, FixPlan, HealthIssue,
    PipelineEvent, RCAResult, get_engine, get_session,
)


@pytest.fixture
def db(tmp_path):
    import agenticops.models as models_mod
    import agenticops.audit.models  # noqa: F401 — register audit_logs
    from agenticops.config import settings

    models_mod._engine = None
    settings.database_url = f"sqlite:///{tmp_path}/schema.db"
    engine = models_mod.get_engine()
    Base.metadata.create_all(engine)
    session = get_session()
    yield session
    session.close()
    models_mod._engine = None


def _cr(session) -> ChangeRequest:
    cr = ChangeRequest(title="tag ec2", description="add Env=prod", requested_by="user:admin", source="web")
    session.add(cr)
    session.flush()
    return cr


def _issue_and_rca(session):
    issue = HealthIssue(title="t", description="d", severity="low", source="test", status="open", resource_id="r")
    session.add(issue)
    session.flush()
    rca = RCAResult(health_issue_id=issue.id, root_cause="x", confidence=0.9)
    session.add(rca)
    session.flush()
    return issue, rca


def test_change_plan_has_no_issue(db):
    cr = _cr(db)
    plan = FixPlan(plan_kind="change", change_request_id=cr.id, risk_level="L1", title="t", summary="s")
    db.add(plan)
    db.commit()
    assert plan.health_issue_id is None and plan.rca_result_id is None
    assert plan.change_request.id == cr.id
    assert cr.plans[0].id == plan.id


def test_default_plan_kind_is_fix(db):
    issue, rca = _issue_and_rca(db)
    plan = FixPlan(health_issue_id=issue.id, rca_result_id=rca.id, risk_level="L1", title="t", summary="s")
    db.add(plan)
    db.commit()
    assert plan.plan_kind == "fix"


def test_fix_plan_without_issue_violates_check(db):
    plan = FixPlan(plan_kind="fix", risk_level="L1", title="t", summary="s")
    db.add(plan)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_change_plan_with_issue_violates_check(db):
    cr = _cr(db)
    issue, rca = _issue_and_rca(db)
    plan = FixPlan(plan_kind="change", change_request_id=cr.id, health_issue_id=issue.id,
                   rca_result_id=rca.id, risk_level="L1", title="t", summary="s")
    db.add(plan)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_execution_and_event_can_belong_to_a_change(db):
    cr = _cr(db)
    plan = FixPlan(plan_kind="change", change_request_id=cr.id, risk_level="L1", title="t", summary="s")
    db.add(plan)
    db.flush()
    db.add(FixExecution(fix_plan_id=plan.id, status="pending", executed_by="user:admin"))
    db.add(PipelineEvent(change_request_id=cr.id, event_type="change_requested", stage="intake", status="completed"))
    db.commit()
    ev = db.query(PipelineEvent).filter_by(change_request_id=cr.id).one()
    assert ev.health_issue_id is None


def test_command_audit_row(db):
    row = CommandAudit(actor="cli:malibo", tool="run_aws_cli", tier="write", command="aws ec2 create-tags ...",
                       outcome="executed", exit_code=0, trace_id="TRC-abcd1234")
    db.add(row)
    db.commit()
    assert db.query(CommandAudit).count() == 1


def test_audit_log_has_actor_column(db):
    from agenticops.audit.models import AuditLog
    db.add(AuditLog(action="plan.approved", entity_type="fix_plan", entity_id="1", actor="user:admin"))
    db.commit()
    assert db.query(AuditLog).one().actor == "user:admin"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_change_schema.py -q`
Expected: FAIL — `ImportError: cannot import name 'CommandAudit'` / `TypeError: 'plan_kind' is an invalid keyword argument`

- [ ] **Step 3: 改 `FixPlan`、`FixExecution`、`PipelineEvent`，新增 `CommandAudit`**

确认 `from sqlalchemy import (...)` 里有 `CheckConstraint`；没有就加。`FixPlan` 改为：

```python
class FixPlan(Base):
    """Structured plans. plan_kind='fix' (from HealthIssue+RCA) or 'change' (from a ChangeRequest)."""

    __tablename__ = "fix_plans"
    __table_args__ = (
        Index("idx_fix_plan_kind", "plan_kind"),
        Index("idx_fix_plan_change_request", "change_request_id"),
        CheckConstraint(
            "(plan_kind = 'fix' AND health_issue_id IS NOT NULL AND rca_result_id IS NOT NULL "
            "AND change_request_id IS NULL) OR "
            "(plan_kind = 'change' AND change_request_id IS NOT NULL AND health_issue_id IS NULL "
            "AND rca_result_id IS NULL)",
            name="ck_fix_plans_origin",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_kind: Mapped[str] = mapped_column(String(10), default="fix", server_default="fix")
    health_issue_id: Mapped[Optional[int]] = mapped_column(ForeignKey("health_issues.id"), nullable=True)
    rca_result_id: Mapped[Optional[int]] = mapped_column(ForeignKey("rca_results.id"), nullable=True)
    change_request_id: Mapped[Optional[int]] = mapped_column(ForeignKey("change_requests.id"), nullable=True)
    risk_level: Mapped[str] = mapped_column(String(20))  # L0, L1, L2, L3
    title: Mapped[str] = mapped_column(String(300))
    summary: Mapped[str] = mapped_column(Text)
    steps: Mapped[list] = mapped_column(JSON, default=list)  # ordered steps
    rollback_plan: Mapped[dict] = mapped_column(JSON, default=dict)
    estimated_impact: Mapped[str] = mapped_column(Text, default="")
    pre_checks: Mapped[list] = mapped_column(JSON, default=list)
    post_checks: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(30), default="draft")
    # Lifecycle (validate_plan_transition): draft -> pending_approval -> approved -> executing -> executed | failed | rejected
    approved_by: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    approved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    rejected_by: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    rejected_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    rejection_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Relationships
    health_issue: Mapped[Optional["HealthIssue"]] = relationship(back_populates="fix_plans")
    rca_result: Mapped[Optional["RCAResult"]] = relationship()
    change_request: Mapped[Optional["ChangeRequest"]] = relationship(back_populates="plans")
    fix_executions: Mapped[list["FixExecution"]] = relationship(back_populates="fix_plan")
```

`FixExecution.health_issue_id` 改为：

```python
    health_issue_id: Mapped[Optional[int]] = mapped_column(ForeignKey("health_issues.id"), nullable=True)
    ...
    health_issue: Mapped[Optional["HealthIssue"]] = relationship(back_populates="fix_executions")
```

`PipelineEvent` 改为：

```python
class PipelineEvent(Base):
    """Timeline event log for HealthIssue AND ChangeRequest lifecycles (exactly one id set)."""

    __tablename__ = "pipeline_events"
    __table_args__ = (
        Index("idx_pipeline_event_issue", "health_issue_id"),
        Index("idx_pipeline_event_change", "change_request_id"),
        Index("idx_pipeline_event_time", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    health_issue_id: Mapped[Optional[int]] = mapped_column(nullable=True, index=True)
    change_request_id: Mapped[Optional[int]] = mapped_column(nullable=True)
    event_type: Mapped[str] = mapped_column(String(50))
    ...（其余列不变）
```

在 `PipelineEvent` 之后新增：

```python
# ============================================================================
# Command Audit (MVP-2.6.0) — tool-layer ledger of write-tier commands
# ============================================================================


class CommandAudit(Base):
    """One row per write/unknown/blocked command attempt made by run_aws_cli / run_on_host /
    run_kubectl / run_skill_script. Read-only commands are NOT recorded."""

    __tablename__ = "command_audits"
    __table_args__ = (
        Index("idx_command_audit_created", "created_at"),
        Index("idx_command_audit_actor", "actor"),
        Index("idx_command_audit_outcome", "outcome"),
        Index("idx_command_audit_plan", "fix_plan_id"),
        Index("idx_command_audit_change", "change_request_id"),
        Index("idx_command_audit_trace", "trace_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(timezone.utc))
    actor: Mapped[str] = mapped_column(String(100), default="system")
    actor_user_id: Mapped[Optional[int]] = mapped_column(nullable=True)
    on_behalf_of: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    agent_name: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    tool: Mapped[str] = mapped_column(String(30))  # run_aws_cli|run_on_host|run_kubectl|run_skill_script
    tier: Mapped[str] = mapped_column(String(10))  # write|unknown|blocked|script
    account: Mapped[str] = mapped_column(String(100), default="")
    region: Mapped[str] = mapped_column(String(30), default="")
    target: Mapped[str] = mapped_column(String(200), default="")  # host id / cluster / skill
    command: Mapped[str] = mapped_column(Text)  # redacted
    outcome: Mapped[str] = mapped_column(String(10))  # executed|refused|blocked|error
    reason: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)  # confirmation|change_required|...
    exit_code: Mapped[Optional[int]] = mapped_column(nullable=True)
    output_excerpt: Mapped[str] = mapped_column(Text, default="")  # redacted, <= 2000 chars
    duration_ms: Mapped[int] = mapped_column(default=0)
    trace_id: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    fix_plan_id: Mapped[Optional[int]] = mapped_column(nullable=True)
    change_request_id: Mapped[Optional[int]] = mapped_column(nullable=True)
```

`src/agenticops/audit/models.py` 的 `AuditLog` 在 `user_email` 之后加：

```python
    actor: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)  # actor key (user:x / cli:x / agent:x)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_change_schema.py tests/test_change_state_machine.py -q`
Expected: PASS

- [ ] **Step 5: 全量回归**

Run: `python -m pytest tests/ -q --deselect tests/test_web_tools.py > /tmp/pytest-t2.log 2>&1; tail -5 /tmp/pytest-t2.log`
Expected: passed。若 `tests/test_web_schemas.py` 或其他测试因 `FixPlanResponse.health_issue_id: int` 收到 None 而失败——此处不会（旧路径永远有 issue），Response 改 Optional 留到 Task 8。

- [ ] **Step 6: Commit**

```bash
git add src/agenticops/models.py src/agenticops/audit/models.py tests/test_change_schema.py
git commit -m "feat(models): generalize fix_plans (plan_kind + CHECK), nullable origins, command_audits, audit_logs.actor"
```

---

### Task 3: `init_db` 2.6.0 迁移 — SQLite 表重建 + ADD COLUMN + PostgreSQL 路径

**Files:**
- Modify: `src/agenticops/models.py`（`init_db`：在 `Base.metadata.create_all(engine)`（约 :1253）之后立即调用 `_migrate_2_6_0(engine)`；辅助函数放在 `init_db` 之前）
- Test: `tests/test_migration_2_6_0.py`

**Interfaces:**
- Produces: `_migrate_2_6_0(engine) -> None`（幂等）、`_sqlite_rebuild_table(engine, table) -> None`、`_sqlite_notnull_columns(engine, table_name) -> set[str]`、`_backup_sqlite_file(engine) -> Optional[str]`。

- [ ] **Step 1: 写失败测试（用 2.5.0 的旧 schema 造库）**

```python
# tests/test_migration_2_6_0.py
"""init_db must migrate a pre-2.6.0 SQLite database in place: NOT NULL → NULL on the three
plan-lineage tables, new columns, CHECK constraint, indexes rebuilt, rows preserved, idempotent."""
import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, text

OLD_SCHEMA = """
CREATE TABLE cloud_accounts (id INTEGER PRIMARY KEY, name VARCHAR(100), provider VARCHAR(20), is_enabled BOOLEAN,
  credential_source_type VARCHAR(20), credentials JSON, regions JSON, labels JSON, created_at DATETIME, last_scanned_at DATETIME);
CREATE TABLE health_issues (id INTEGER PRIMARY KEY, title VARCHAR(300), description TEXT, severity VARCHAR(20),
  source VARCHAR(50), status VARCHAR(30), resource_id VARCHAR(500), trace_id VARCHAR(20), account_id INTEGER);
CREATE TABLE rca_results (id INTEGER PRIMARY KEY, health_issue_id INTEGER NOT NULL, root_cause TEXT, confidence FLOAT);
CREATE TABLE fix_plans (
  id INTEGER NOT NULL PRIMARY KEY, health_issue_id INTEGER NOT NULL, rca_result_id INTEGER NOT NULL,
  risk_level VARCHAR(20) NOT NULL, title VARCHAR(300) NOT NULL, summary TEXT NOT NULL, steps JSON, rollback_plan JSON,
  estimated_impact TEXT NOT NULL, pre_checks JSON, post_checks JSON, status VARCHAR(30) NOT NULL,
  approved_by VARCHAR(100), approved_at DATETIME, created_at DATETIME NOT NULL,
  FOREIGN KEY(health_issue_id) REFERENCES health_issues (id), FOREIGN KEY(rca_result_id) REFERENCES rca_results (id));
CREATE TABLE fix_executions (
  id INTEGER NOT NULL PRIMARY KEY, fix_plan_id INTEGER NOT NULL, health_issue_id INTEGER NOT NULL, status VARCHAR(30) NOT NULL,
  started_at DATETIME, completed_at DATETIME, executed_by VARCHAR(100) NOT NULL, pre_check_results JSON, step_results JSON,
  post_check_results JSON, rollback_results JSON, error_message TEXT, duration_ms INTEGER NOT NULL, created_at DATETIME NOT NULL,
  FOREIGN KEY(fix_plan_id) REFERENCES fix_plans (id), FOREIGN KEY(health_issue_id) REFERENCES health_issues (id));
CREATE INDEX idx_fix_exec_status ON fix_executions (status);
CREATE INDEX idx_fix_exec_plan ON fix_executions (fix_plan_id);
CREATE TABLE pipeline_events (
  id INTEGER NOT NULL PRIMARY KEY, health_issue_id INTEGER NOT NULL, event_type VARCHAR(50) NOT NULL, stage VARCHAR(30) NOT NULL,
  status VARCHAR(20) NOT NULL, detail TEXT, actor VARCHAR(100) NOT NULL, duration_ms INTEGER, created_at DATETIME NOT NULL,
  trace_id VARCHAR(20));
CREATE INDEX idx_pipeline_event_issue ON pipeline_events (health_issue_id);
CREATE INDEX idx_pipeline_event_time ON pipeline_events (created_at);
CREATE INDEX ix_pipeline_events_health_issue_id ON pipeline_events (health_issue_id);
CREATE INDEX ix_pipeline_events_trace_id ON pipeline_events (trace_id);
INSERT INTO health_issues (id, title, description, severity, source, status, resource_id) VALUES (1, 'i', 'd', 'low', 'test', 'fix_planned', 'r');
INSERT INTO rca_results (id, health_issue_id, root_cause, confidence) VALUES (1, 1, 'rc', 0.9);
INSERT INTO fix_plans (id, health_issue_id, rca_result_id, risk_level, title, summary, steps, rollback_plan, estimated_impact,
  pre_checks, post_checks, status, approved_by, created_at)
  VALUES (7, 1, 1, 'L1', 'old plan', 'sum', '[]', '{}', '', '[]', '[]', 'approved', 'web-user', '2026-01-01 00:00:00');
INSERT INTO fix_executions (id, fix_plan_id, health_issue_id, status, executed_by, duration_ms, created_at)
  VALUES (3, 7, 1, 'succeeded', 'executor_agent', 10, '2026-01-01 00:00:00');
INSERT INTO pipeline_events (id, health_issue_id, event_type, stage, status, actor, created_at)
  VALUES (5, 1, 'fix_approved', 'approval', 'completed', 'system', '2026-01-01 00:00:00');
"""


@pytest.fixture
def old_db(tmp_path):
    path = tmp_path / "agenticops.db"
    con = sqlite3.connect(path)
    con.executescript(OLD_SCHEMA)
    con.commit()
    con.close()
    return path


def _notnull(engine, table):
    with engine.connect() as c:
        rows = c.execute(text(f"PRAGMA table_info({table})")).fetchall()
    return {r[1]: bool(r[3]) for r in rows}


def _table_sql(engine, table):
    with engine.connect() as c:
        return c.execute(text("SELECT sql FROM sqlite_master WHERE type='table' AND name=:n"), {"n": table}).scalar()


def _run_init_db(path):
    import agenticops.models as models_mod
    from agenticops.config import settings
    models_mod._engine = None
    settings.database_url = f"sqlite:///{path}"
    engine = models_mod.get_engine()
    models_mod.init_db(engine)
    return engine


def test_migration_relaxes_not_null_and_adds_columns(old_db):
    engine = _run_init_db(old_db)
    fp = _notnull(engine, "fix_plans")
    assert fp["health_issue_id"] is False and fp["rca_result_id"] is False
    for col in ("plan_kind", "change_request_id", "rejected_by", "rejected_at", "rejection_reason", "updated_at"):
        assert col in fp
    assert _notnull(engine, "fix_executions")["health_issue_id"] is False
    pe = _notnull(engine, "pipeline_events")
    assert pe["health_issue_id"] is False and "change_request_id" in pe
    assert "ck_fix_plans_origin" in _table_sql(engine, "fix_plans")


def test_migration_preserves_rows_and_defaults_plan_kind(old_db):
    engine = _run_init_db(old_db)
    with engine.connect() as c:
        row = c.execute(text("SELECT id, health_issue_id, rca_result_id, status, approved_by, plan_kind FROM fix_plans")).one()
        assert tuple(row) == (7, 1, 1, "approved", "web-user", "fix")
        assert c.execute(text("SELECT COUNT(*) FROM fix_executions")).scalar() == 1
        assert c.execute(text("SELECT id, health_issue_id FROM pipeline_events")).one()[1] == 1


def test_migration_rebuilds_indexes(old_db):
    engine = _run_init_db(old_db)
    names = {ix["name"] for ix in inspect(engine).get_indexes("fix_executions")}
    assert {"idx_fix_exec_status", "idx_fix_exec_plan"} <= names
    names = {ix["name"] for ix in inspect(engine).get_indexes("pipeline_events")}
    assert {"idx_pipeline_event_issue", "idx_pipeline_event_change", "idx_pipeline_event_time"} <= names


def test_migration_creates_backup_and_is_idempotent(old_db):
    engine = _run_init_db(old_db)
    bak = Path(str(old_db) + ".bak-pre-2.6.0")
    assert bak.exists()
    before = {t: _table_sql(engine, t) for t in ("fix_plans", "fix_executions", "pipeline_events")}
    import agenticops.models as models_mod
    models_mod.init_db(engine)  # second run: no rebuild, no error
    after = {t: _table_sql(engine, t) for t in ("fix_plans", "fix_executions", "pipeline_events")}
    assert before == after


def test_fresh_database_needs_no_rebuild(tmp_path):
    engine = _run_init_db(tmp_path / "fresh.db")
    assert not Path(str(tmp_path / "fresh.db") + ".bak-pre-2.6.0").exists()
    assert _notnull(engine, "fix_plans")["health_issue_id"] is False
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_migration_2_6_0.py -q`
Expected: FAIL — `assert fp["health_issue_id"] is False`（旧库仍是 NOT NULL）

- [ ] **Step 3: 在 `models.py` 加迁移辅助函数与调用**

在 `def init_db(engine=None):` 之前加：

```python
# ── MVP-2.6.0 migration helpers ───────────────────────────────────────

_NULLABLE_ORIGIN_COLUMNS: dict[str, tuple[str, ...]] = {
    "fix_plans": ("health_issue_id", "rca_result_id"),
    "fix_executions": ("health_issue_id",),
    "pipeline_events": ("health_issue_id",),
}

_ADD_COLUMNS_2_6_0: dict[str, dict[str, str]] = {
    "fix_plans": {
        "plan_kind": "VARCHAR(10) DEFAULT 'fix'",
        "change_request_id": "INTEGER",
        "rejected_by": "VARCHAR(100)",
        "rejected_at": "DATETIME",
        "rejection_reason": "TEXT",
        "updated_at": "DATETIME",
    },
    "pipeline_events": {"change_request_id": "INTEGER"},
    "audit_logs": {"actor": "VARCHAR(100)"},
}


def _sqlite_notnull_columns(engine, table_name: str) -> set[str]:
    with engine.connect() as conn:
        rows = conn.execute(text(f"PRAGMA table_info({table_name})")).fetchall()
    return {r[1] for r in rows if r[3]}


def _backup_sqlite_file(engine) -> Optional[str]:
    """Copy the SQLite file to <db>.bak-pre-2.6.0 once (before the first table rebuild)."""
    import shutil
    db_path = engine.url.database
    if not db_path or db_path == ":memory:":
        return None
    bak = f"{db_path}.bak-pre-2.6.0"
    if not os.path.exists(bak) and os.path.exists(db_path):
        shutil.copy2(db_path, bak)
        logger.info("Pre-2.6.0 database backup written to %s", bak)
    return bak


def _sqlite_rebuild_table(engine, table) -> None:
    """sqlite.org 'other kinds of ALTER': create <t>__new from the ORM metadata (no indexes),
    copy the common columns, drop the old table (drops its indexes), rename new → old name
    (this direction leaves other tables' FK references pointing at the surviving name), then
    recreate the indexes. FK enforcement is off in this project, so no PRAGMA dance is needed."""
    from sqlalchemy import MetaData

    tmp_name = f"{table.name}__new"
    tmp_meta = MetaData()
    tmp_table = table.to_metadata(tmp_meta, name=tmp_name)
    for idx in list(tmp_table.indexes):
        tmp_table.indexes.discard(idx)
    with engine.begin() as conn:
        conn.execute(text(f"DROP TABLE IF EXISTS {tmp_name}"))
        tmp_table.create(conn)
        old_cols = {r[1] for r in conn.execute(text(f"PRAGMA table_info({table.name})")).fetchall()}
        common = [c.name for c in table.columns if c.name in old_cols]
        cols_sql = ", ".join(common)
        conn.execute(text(f"INSERT INTO {tmp_name} ({cols_sql}) SELECT {cols_sql} FROM {table.name}"))
        conn.execute(text(f"DROP TABLE {table.name}"))
        conn.execute(text(f"ALTER TABLE {tmp_name} RENAME TO {table.name}"))
        for idx in table.indexes:
            idx.create(conn)
    logger.info("Rebuilt table %s with relaxed NOT NULL constraints (MVP-2.6.0)", table.name)


def _migrate_2_6_0(engine) -> None:
    """Idempotent MVP-2.6.0 schema migration (runs after create_all)."""
    insp = inspect(engine)
    dialect = engine.dialect.name
    if dialect == "sqlite":
        tables = {"fix_plans": FixPlan.__table__, "fix_executions": FixExecution.__table__,
                  "pipeline_events": PipelineEvent.__table__}
        needs_rebuild = [
            name for name, cols in _NULLABLE_ORIGIN_COLUMNS.items()
            if insp.has_table(name) and any(c in _sqlite_notnull_columns(engine, name) for c in cols)
        ]
        if needs_rebuild:
            _backup_sqlite_file(engine)
            for name in needs_rebuild:
                _sqlite_rebuild_table(engine, tables[name])
            insp = inspect(engine)
        # Any column still missing (e.g. table rebuilt by an older run) → plain ADD COLUMN
        for tbl, cols in _ADD_COLUMNS_2_6_0.items():
            if not insp.has_table(tbl):
                continue
            existing = {c["name"] for c in insp.get_columns(tbl)}
            with engine.begin() as conn:
                for col, ddl in cols.items():
                    if col not in existing:
                        conn.execute(text(f"ALTER TABLE {tbl} ADD COLUMN {col} {ddl}"))
                if tbl == "fix_plans":
                    conn.execute(text("UPDATE fix_plans SET plan_kind = 'fix' WHERE plan_kind IS NULL"))
                    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_fix_plan_kind ON fix_plans(plan_kind)"))
                    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_fix_plan_change_request ON fix_plans(change_request_id)"))
                if tbl == "pipeline_events":
                    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_pipeline_event_change ON pipeline_events(change_request_id)"))
                if tbl == "audit_logs":
                    conn.execute(text("CREATE INDEX IF NOT EXISTS ix_audit_logs_actor ON audit_logs(actor)"))
    elif dialect == "postgresql":
        with engine.begin() as conn:
            for tbl, cols in _NULLABLE_ORIGIN_COLUMNS.items():
                for col in cols:
                    conn.execute(text(f"ALTER TABLE {tbl} ALTER COLUMN {col} DROP NOT NULL"))
            for tbl, cols in _ADD_COLUMNS_2_6_0.items():
                for col, ddl in cols.items():
                    conn.execute(text(f"ALTER TABLE {tbl} ADD COLUMN IF NOT EXISTS {col} {ddl}"))
            conn.execute(text("UPDATE fix_plans SET plan_kind = 'fix' WHERE plan_kind IS NULL"))
            has_ck = conn.execute(text(
                "SELECT 1 FROM pg_constraint WHERE conname = 'ck_fix_plans_origin'"
            )).scalar()
            if not has_ck:
                conn.execute(text(
                    "ALTER TABLE fix_plans ADD CONSTRAINT ck_fix_plans_origin CHECK ("
                    "(plan_kind = 'fix' AND health_issue_id IS NOT NULL AND rca_result_id IS NOT NULL AND change_request_id IS NULL) OR "
                    "(plan_kind = 'change' AND change_request_id IS NOT NULL AND health_issue_id IS NULL AND rca_result_id IS NULL))"
                ))
            for stmt in (
                "CREATE INDEX IF NOT EXISTS idx_fix_plan_kind ON fix_plans(plan_kind)",
                "CREATE INDEX IF NOT EXISTS idx_fix_plan_change_request ON fix_plans(change_request_id)",
                "CREATE INDEX IF NOT EXISTS idx_pipeline_event_change ON pipeline_events(change_request_id)",
                "CREATE INDEX IF NOT EXISTS ix_audit_logs_actor ON audit_logs(actor)",
            ):
                conn.execute(text(stmt))
```

确认文件顶部有 `import os` 与 `logger = logging.getLogger(__name__)`（没有就加）。然后在 `init_db` 里 `Base.metadata.create_all(engine)` 的下一行加：

```python
    # MVP-2.6.0: relax plan-lineage NOT NULLs (table rebuild on SQLite), add change columns.
    # Raises on failure on purpose — never start on a half-migrated schema.
    _migrate_2_6_0(engine)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_migration_2_6_0.py -q`
Expected: 5 PASS。若 `to_metadata(..., name=...)` 在当前 SQLAlchemy 版本不接受 `name` 参数，改用 `table.to_metadata(tmp_meta)` 后 `tmp_table.name = tmp_name`（`Table.name` 可赋值，DDL 编译时读取）。

- [ ] **Step 5: 对本机开发库做一次真实迁移演练（只读验证，不动源库）**

```bash
cp data/agenticops.db /tmp/agenticops-migrate-test.db 2>/dev/null || ls data/*.db
AIOPS_DATABASE_URL=sqlite:////tmp/agenticops-migrate-test.db python -c "from agenticops.models import init_db; init_db(); print('ok')"
sqlite3 /tmp/agenticops-migrate-test.db "PRAGMA table_info(fix_plans);" | grep -E "health_issue_id|plan_kind"
```
Expected: `ok`；`health_issue_id` 的 notnull 列为 0；`plan_kind` 存在；`/tmp/agenticops-migrate-test.db.bak-pre-2.6.0` 生成。（开发库路径以 `settings.database_url` 为准；`sqlite3` 不在 PATH 时用 `python -c "import sqlite3;..."`。）

- [ ] **Step 6: 全量回归 + Commit**

Run: `python -m pytest tests/ -q --deselect tests/test_web_tools.py > /tmp/pytest-t3.log 2>&1; tail -5 /tmp/pytest-t3.log`

```bash
git add src/agenticops/models.py tests/test_migration_2_6_0.py
git commit -m "feat(db): MVP-2.6.0 migration — SQLite plan-lineage table rebuild, new columns, PG path"
```

---

### Task 4: 全部直接赋值改走 `transition_plan`（6 处 + 2 处 API/CLI）

**Files:**
- Modify: `src/agenticops/tools/metadata_tools.py`（`approve_fix_plan` :1043-1051；`save_execution_result` :1160-1205；import 行 :14-26）
- Modify: `src/agenticops/services/pipeline_service.py:146-149`
- Modify: `src/agenticops/web/app.py:2378-2424`（approve）、`:2442-2477`（execute）
- Modify: `src/agenticops/cli/main.py:2300-2305`（`/approve`）、`:2356-2362`（`/execute`）
- Modify: `src/agenticops/services/executor_service.py:189-202`（`_mark_crashed`）
- Test: `tests/test_plan_transition_enforcement.py`

**Interfaces:**
- Consumes: `transition_plan`, `InvalidStatusTransition`（Task 1）
- Produces: 无新符号；行为契约——非法状态变更在工具里返回 `"Cannot transition plan from ..."` 文本、在 API 返回 409、在 CLI 打印红色错误；`save_execution_result` 只接受 `approved|executing` 的计划（approved 先转 executing 再转终态）。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_plan_transition_enforcement.py
"""Every status write on FixPlan must go through validate_plan_transition (MVP-2.6.0 S0)."""
import pytest
from unittest.mock import patch

from agenticops.models import Base, FixPlan, HealthIssue, RCAResult, get_engine, get_session


@pytest.fixture
def db(tmp_path):
    import agenticops.models as models_mod
    from agenticops.config import settings
    models_mod._engine = None
    settings.database_url = f"sqlite:///{tmp_path}/enforce.db"
    Base.metadata.create_all(models_mod.get_engine())
    s = get_session()
    yield s
    s.close()
    models_mod._engine = None


def _plan(db, status="draft", risk="L1") -> FixPlan:
    issue = HealthIssue(title="t", description="d", severity="low", source="test", status="fix_planned", resource_id="r")
    db.add(issue); db.flush()
    rca = RCAResult(health_issue_id=issue.id, root_cause="x", confidence=0.9)
    db.add(rca); db.flush()
    plan = FixPlan(health_issue_id=issue.id, rca_result_id=rca.id, risk_level=risk, title="p", summary="s", status=status)
    db.add(plan); db.commit()
    return plan


def test_tool_approve_refuses_executed_plan(db):
    from agenticops.tools.metadata_tools import approve_fix_plan
    plan = _plan(db, status="executed")
    out = approve_fix_plan(fix_plan_id=plan.id, approved_by="operator:admin")
    assert "Cannot transition plan" in out
    db.refresh(plan)
    assert plan.status == "executed"


def test_tool_save_execution_result_from_approved_goes_through_executing(db):
    from agenticops.tools.metadata_tools import save_execution_result
    plan = _plan(db, status="approved")
    with patch("agenticops.services.notification_service.notify_execution_result"), \
         patch("agenticops.services.notification_service.notify_im_origin"):
        out = save_execution_result(fix_plan_id=plan.id, health_issue_id=plan.health_issue_id, status="succeeded")
    assert "FixExecution #" in out
    db.refresh(plan)
    assert plan.status == "executed"


def test_tool_save_execution_result_refuses_draft(db):
    from agenticops.tools.metadata_tools import save_execution_result
    plan = _plan(db, status="draft")
    out = save_execution_result(fix_plan_id=plan.id, health_issue_id=plan.health_issue_id, status="succeeded")
    assert "not executable" in out
    db.refresh(plan)
    assert plan.status == "draft"


def test_api_approve_executed_plan_is_409(db):
    from starlette.testclient import TestClient
    from agenticops.web.app import app
    plan = _plan(db, status="executed")
    client = TestClient(app)
    r = client.put(f"/api/fix-plans/{plan.id}/approve", json={"approved_by": "tester"})
    assert r.status_code == 409


def test_executor_service_mark_crashed_uses_validator(db):
    from agenticops.models import FixExecution
    from agenticops.services.executor_service import ExecutorService
    plan = _plan(db, status="executing")
    ex = FixExecution(fix_plan_id=plan.id, health_issue_id=plan.health_issue_id, status="running", executed_by="t")
    db.add(ex); db.commit()
    ExecutorService()._mark_crashed(ex.id, plan.id, "boom")
    db.expire_all()
    assert db.get(FixPlan, plan.id).status == "failed"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_plan_transition_enforcement.py -q`
Expected: `test_tool_approve_refuses_executed_plan`、`test_tool_save_execution_result_refuses_draft`、`test_api_approve_executed_plan_is_409` FAIL（目前直接赋值、API 返回 200）

- [ ] **Step 3: `metadata_tools.py` — import + `approve_fix_plan` + `save_execution_result`**

import 块加 `transition_plan`：

```python
from agenticops.models import (
    CloudAccount, CloudResource, FixExecution, FixPlan, HealthIssue, IMAlias,
    InvalidStatusTransition, RCAResult, get_session, transition_plan, validate_status_transition,
)
```

`approve_fix_plan` 里两处赋值改为：

```python
        # L2/L3 require human approval — flag it but still record
        if plan.risk_level in ("L2", "L3") and approved_by.startswith("agent:"):
            try:
                transition_plan(plan, "pending_approval")
            except InvalidStatusTransition as e:
                return str(e)
            session.commit()
            return (...)  # 原文案不变

        try:
            transition_plan(plan, "approved")
        except InvalidStatusTransition as e:
            return str(e)
        plan.approved_by = approved_by
        plan.approved_at = datetime.now(timezone.utc)
        session.commit()
```

`save_execution_result` 在 `plan = session.query(FixPlan)...` 之后、创建 `FixExecution` 之前加守卫，并把状态更新改为：

```python
        if plan.status not in ("approved", "executing"):
            return (
                f"FixPlan #{fix_plan_id} is '{plan.status}' — not executable. "
                f"Only approved/executing plans can record an execution result."
            )
        ...
        # Update FixPlan status through the state machine (approved → executing → terminal)
        if plan.status == "approved":
            transition_plan(plan, "executing")
        if status == "succeeded":
            transition_plan(plan, "executed")
        elif status in ("failed", "rolled_back"):
            transition_plan(plan, "failed")
        # aborted -> stays executing (operator may retry / a new execution row will follow)
```

- [ ] **Step 4: `pipeline_service.py` 自动审批**

```python
            # Approve plan (policy auto_approve, or legacy L0/L1)
            from agenticops.models import transition_plan
            transition_plan(plan, "approved")
            plan.approved_by = "agent:auto-pipeline"
            plan.approved_at = datetime.now(timezone.utc)
```

- [ ] **Step 5: `app.py` approve / execute**

`api_approve_fix_plan` 里 `plan.status = "approved"` 改为：

```python
        from agenticops.models import InvalidStatusTransition, transition_plan
        try:
            transition_plan(plan, "approved")
        except InvalidStatusTransition as e:
            raise HTTPException(status_code=409, detail=str(e))
```

（保留上面已有的 400 分支：already approved / rejected。）`api_execute_fix_plan` 里 `plan.status = "executing"` 改为 `transition_plan(plan, "executing")`（status 已在上方被校验为 approved，不会抛）。

- [ ] **Step 6: `cli/main.py` `/approve` `/execute`**

`/approve`：`plan.status = "approved"` → 

```python
        from agenticops.models import InvalidStatusTransition, transition_plan
        try:
            transition_plan(plan, "approved")
        except InvalidStatusTransition as e:
            return f"[red]{e}[/red]"
```

`/execute`：`plan.status = "executing"` → `transition_plan(plan, "executing")`。

- [ ] **Step 7: `executor_service.py` `_mark_crashed`**

```python
                plan = session.query(FixPlan).filter_by(id=fix_plan_id).first()
                if plan:
                    from agenticops.models import InvalidStatusTransition, transition_plan
                    try:
                        transition_plan(plan, "failed")
                    except InvalidStatusTransition:
                        logger.warning("Plan #%d in '%s' cannot move to failed after crash", fix_plan_id, plan.status)
```

`tests/test_executor_service.py::test_mark_crashed_updates_db` 用 MagicMock plan（status 属性为 MagicMock）——`validate_plan_transition` 会因未知状态抛 `ValueError`。在该测试的 mock plan 上补 `mock_plan.status = "executing"`（测试文件 :381-403 处）；这是让旧测试与真实状态机一致，不是放松断言。

- [ ] **Step 8: 跑测试 + 全量回归**

Run: `python -m pytest tests/test_plan_transition_enforcement.py tests/test_executor_service.py tests/test_auto_fix_pipeline.py tests/test_sre_agent.py -q`
Expected: PASS。然后 `python -m pytest tests/ -q --deselect tests/test_web_tools.py > /tmp/pytest-t4.log 2>&1; tail -5 /tmp/pytest-t4.log`

- [ ] **Step 9: Commit**

```bash
git add src/agenticops/tools/metadata_tools.py src/agenticops/services/pipeline_service.py src/agenticops/web/app.py src/agenticops/cli/main.py src/agenticops/services/executor_service.py tests/test_plan_transition_enforcement.py tests/test_executor_service.py
git commit -m "refactor(plans): route every FixPlan status write through validate_plan_transition"
```

---

### Task 5: Run Context（`run_context.py`）

**Files:**
- Create: `src/agenticops/run_context.py`
- Test: `tests/test_run_context.py`

**Interfaces:**
- Produces:
  ```python
  @dataclass(frozen=True)
  class RunContext:
      actor: str = "system"; actor_user_id: Optional[int] = None; on_behalf_of: Optional[str] = None
      trace_id: Optional[str] = None; agent_name: Optional[str] = None
      fix_plan_id: Optional[int] = None; change_request_id: Optional[int] = None
      chat_session_id: Optional[str] = None
  def get_run_context() -> RunContext
  def set_run_context(ctx: RunContext) -> contextvars.Token
  def reset_run_context(token) -> None
  def update_run_context(**fields) -> contextvars.Token     # copy-with
  @contextmanager
  def run_context(**fields)                                  # set + reset
  ```
  语义：工具内只读（Strands 在 `copy_context` 里跑同步工具，读得到、写不出）；新线程**不**继承（必须显式 set，见 Task 11）。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_run_context.py
import contextvars
import threading

from agenticops.run_context import (
    RunContext, get_run_context, reset_run_context, run_context, set_run_context, update_run_context,
)


def test_default_is_system_actor():
    ctx = get_run_context()
    assert ctx.actor == "system" and ctx.fix_plan_id is None


def test_set_and_reset():
    token = set_run_context(RunContext(actor="cli:malibo", trace_id="TRC-1"))
    assert get_run_context().actor == "cli:malibo"
    reset_run_context(token)
    assert get_run_context().actor == "system"


def test_update_copies_other_fields():
    with run_context(actor="user:admin", trace_id="TRC-2"):
        tok = update_run_context(fix_plan_id=7)
        ctx = get_run_context()
        assert (ctx.actor, ctx.trace_id, ctx.fix_plan_id) == ("user:admin", "TRC-2", 7)
        reset_run_context(tok)
        assert get_run_context().fix_plan_id is None
    assert get_run_context().actor == "system"


def test_context_manager_resets_on_exception():
    try:
        with run_context(actor="agent:executor"):
            raise RuntimeError("x")
    except RuntimeError:
        pass
    assert get_run_context().actor == "system"


def test_copy_context_propagates_reads_like_strands_tools():
    with run_context(actor="user:admin", change_request_id=3):
        seen = contextvars.copy_context().run(lambda: get_run_context().change_request_id)
    assert seen == 3


def test_new_thread_does_not_inherit():
    seen = {}
    with run_context(actor="user:admin"):
        t = threading.Thread(target=lambda: seen.setdefault("actor", get_run_context().actor))
        t.start(); t.join()
    assert seen["actor"] == "system"


def test_frozen():
    import dataclasses
    import pytest
    with pytest.raises(dataclasses.FrozenInstanceError):
        get_run_context().actor = "x"  # type: ignore[misc]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_run_context.py -q`
Expected: FAIL — `ModuleNotFoundError: agenticops.run_context`

- [ ] **Step 3: 实现**

```python
# src/agenticops/run_context.py
"""Run Context — who is acting, on what, under which trace (MVP-2.6.0).

A single ContextVar carrying the actor and the plan/change/trace identifiers for the
current request, chat turn, CLI turn, IM message, or executor run. Entry points SET it
(web deps, chat handler, CLI, IM gateways, ExecutorService worker, pipeline threads);
tools and services only READ it (get_run_context()).

Thread rule: ContextVars do NOT cross threading.Thread boundaries — every new thread
must call set_run_context() itself (the same discipline as trace_id today). Strands runs
sync tools inside copy_context(), so reads inside tools work; writes inside tools are
invisible outside — never rely on them.
"""

from __future__ import annotations

import contextvars
from contextlib import contextmanager
from dataclasses import dataclass, replace
from typing import Iterator, Optional


@dataclass(frozen=True)
class RunContext:
    actor: str = "system"                     # actor key: user:<email> | web:anonymous | cli:<os user> | agent:<name> | im:<platform>:<id> | webhook:<source>
    actor_user_id: Optional[int] = None
    on_behalf_of: Optional[str] = None        # e.g. executor runs on behalf of the approver
    trace_id: Optional[str] = None
    agent_name: Optional[str] = None
    fix_plan_id: Optional[int] = None
    change_request_id: Optional[int] = None
    chat_session_id: Optional[str] = None


_run_context_var: contextvars.ContextVar[RunContext] = contextvars.ContextVar(
    "agenticops_run_context", default=RunContext()
)


def get_run_context() -> RunContext:
    return _run_context_var.get()


def set_run_context(ctx: RunContext) -> contextvars.Token:
    return _run_context_var.set(ctx)


def reset_run_context(token: contextvars.Token) -> None:
    _run_context_var.reset(token)


def update_run_context(**fields) -> contextvars.Token:
    """Copy the current context with `fields` replaced; returns the reset token."""
    return _run_context_var.set(replace(_run_context_var.get(), **fields))


@contextmanager
def run_context(**fields) -> Iterator[RunContext]:
    token = update_run_context(**fields)
    try:
        yield _run_context_var.get()
    finally:
        _run_context_var.reset(token)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_run_context.py -q`
Expected: 7 PASS

- [ ] **Step 5: Commit**

```bash
git add src/agenticops/run_context.py tests/test_run_context.py
git commit -m "feat(core): RunContext ContextVar (actor / trace / plan / change ids)"
```

---

### Task 6: Actor 解析 + `config/rbac.yaml` + authz 影子模式 + 配置项 `rbac_enforce`/`rbac_file`

**Files:**
- Create: `src/agenticops/auth/actor.py`, `src/agenticops/auth/authz.py`, `config/rbac.yaml`
- Modify: `src/agenticops/config.py`（在 `api_auth_enabled`/`admin_password` 之后加两个 Field）、`config/settings.yaml`（`api_auth_enabled: false` 之后加两行）、`CLAUDE.md`（配置表加两行）
- Test: `tests/test_authz.py`

**Interfaces:**
- Produces:
  ```python
  # agenticops.auth.actor
  @dataclass(frozen=True)
  class Actor: kind: str; id: str; user_id: Optional[int] = None; permissions: tuple[str, ...] = ()
      @property key -> str   # f"{kind}:{id}"
  def web_anonymous_actor() -> Actor            # kind "web", id "anonymous"
  def actor_from_user(user) -> Actor            # kind "user", id=user.email, permissions=tuple(user.permissions)
  def actor_from_request(request) -> Actor      # request.state.user → actor_from_user, else web_anonymous_actor()
  def cli_actor() -> Actor                      # kind "cli", id=getpass.getuser()
  def agent_actor(name: str) -> Actor           # kind "agent"
  def im_actor(platform: str, sender_id: str) -> Actor   # kind "im", id f"{platform}:{sender_id}"
  def webhook_actor(source: str) -> Actor
  def parse_actor(text: str) -> Actor           # "cli:malibo" → Actor("cli","malibo"); no colon → Actor("web", text)
  # agenticops.auth.authz
  PERMISSIONS = ("change.request","change.review","change.approve","change.reject","change.cancel","change.execute",
                 "plan.approve","plan.reject","plan.execute","audit.read")
  class AuthzDenied(Exception): permission: str; actor: str; reason: str; rule: Optional[str]
  class RbacPolicy: permissions: dict[str, list[str]]; subjects: dict[str, list[str]]; rules: list[dict]
      @classmethod load(path) -> RbacPolicy      # 坏文件/未知规则类型 → 内置默认 + logger.error
      def effective_permissions(actor) -> set[str]
      def decide(actor, permission, subject) -> tuple[bool, str, Optional[str], bool]   # (allowed, reason, rule_name, always_enforce)
  def get_rbac_policy(reload=False) -> RbacPolicy
  def check(actor, permission, subject=None) -> None    # AuthzDenied when denied and (settings.rbac_enforce or rule.always_enforce); shadow → audit row + allow
  ```
- 非 `user` 主体的权限来自 `rbac.yaml subjects`（`Actor.permissions` 为空时按 kind 查）。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_authz.py
"""Actor resolution + rbac.yaml matrix + shadow/enforce semantics (MVP-2.6.0 S1)."""
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from agenticops.auth.actor import (
    Actor, actor_from_request, agent_actor, cli_actor, im_actor, parse_actor, web_anonymous_actor,
)
from agenticops.auth.authz import AuthzDenied, RbacPolicy, check, get_rbac_policy


class TestActor:
    def test_key_format(self):
        assert Actor("cli", "malibo").key == "cli:malibo"
        assert im_actor("feishu", "ou_1").key == "im:feishu:ou_1"
        assert agent_actor("auto-pipeline").key == "agent:auto-pipeline"

    def test_from_request_uses_state_user(self):
        user = SimpleNamespace(id=5, email="admin", permissions=["read", "write", "admin"])
        req = SimpleNamespace(state=SimpleNamespace(user=user))
        a = actor_from_request(req)
        assert (a.kind, a.id, a.user_id) == ("user", "admin", 5)
        assert "admin" in a.permissions

    def test_from_request_without_user_is_anonymous(self):
        req = SimpleNamespace(state=SimpleNamespace())
        assert actor_from_request(req) == web_anonymous_actor()

    def test_cli_actor_uses_os_user(self):
        with patch("getpass.getuser", return_value="malibo"):
            assert cli_actor().key == "cli:malibo"

    def test_parse_roundtrip(self):
        assert parse_actor("cli:malibo") == Actor("cli", "malibo")
        assert parse_actor("im:feishu:ou_1") == Actor("im", "feishu:ou_1")
        assert parse_actor("web-user") == Actor("web", "web-user")


@pytest.fixture
def policy():
    return get_rbac_policy(reload=True)


class TestMatrix:
    def test_default_file_loads(self, policy):
        assert policy.permissions["change.approve"] == ["write"]
        assert "anonymous" in policy.subjects

    def test_user_needs_write_to_approve(self, policy):
        reader = Actor("user", "ro", permissions=("read",))
        allowed, reason, _, _ = policy.decide(reader, "change.approve", None)
        assert allowed is False and "write" in reason
        writer = Actor("user", "rw", permissions=("read", "write"))
        assert policy.decide(writer, "change.approve", None)[0] is True

    def test_anonymous_can_do_everything_like_today(self, policy):
        for perm in ("change.request", "change.approve", "plan.execute", "audit.read"):
            assert policy.decide(web_anonymous_actor(), perm, None)[0] is True

    def test_im_can_only_request(self, policy):
        im = im_actor("feishu", "ou_1")
        assert policy.decide(im, "change.request", None)[0] is True
        assert policy.decide(im, "change.approve", None)[0] is False

    def test_sod_rule_denies_self_approval(self, policy):
        cr = SimpleNamespace(requested_by="user:alice", risk_level="L1")
        alice = Actor("user", "alice", permissions=("read", "write"))
        allowed, reason, rule, always = policy.decide(alice, "change.approve", cr)
        assert allowed is False and rule == "sod-change-approver-not-requester" and always is False
        bob = Actor("user", "bob", permissions=("read", "write"))
        assert policy.decide(bob, "change.approve", cr)[0] is True

    def test_agent_cannot_approve_l2_l3_and_this_is_always_enforced(self, policy):
        plan = SimpleNamespace(risk_level="L2", requested_by=None)
        allowed, _, rule, always = policy.decide(agent_actor("sre"), "plan.approve", plan)
        assert allowed is False and rule == "no-agent-approval-above-l1" and always is True
        plan_l1 = SimpleNamespace(risk_level="L1", requested_by=None)
        assert policy.decide(agent_actor("auto-pipeline"), "plan.approve", plan_l1)[0] is True

    def test_bad_file_falls_back_to_defaults(self, tmp_path):
        bad = tmp_path / "rbac.yaml"
        bad.write_text("rules:\n  - name: x\n    permission: change.approve\n    type: no_such_rule\n")
        p = RbacPolicy.load(bad)
        assert p.permissions["change.approve"] == ["write"]  # defaults, not the broken file


class TestCheck:
    def test_shadow_mode_allows_but_audits(self, policy):
        from agenticops.config import settings
        cr = SimpleNamespace(id=1, requested_by="user:alice", risk_level="L1")
        alice = Actor("user", "alice", permissions=("read", "write"))
        with patch.object(settings, "rbac_enforce", False), \
             patch("agenticops.audit.service.AuditService.log") as log:
            check(alice, "change.approve", subject=cr)  # no raise
        assert log.called
        assert log.call_args.kwargs["action"] == "authz.denied_shadow"

    def test_enforce_mode_raises(self, policy):
        from agenticops.config import settings
        cr = SimpleNamespace(id=1, requested_by="user:alice", risk_level="L1")
        alice = Actor("user", "alice", permissions=("read", "write"))
        with patch.object(settings, "rbac_enforce", True), \
             patch("agenticops.audit.service.AuditService.log"):
            with pytest.raises(AuthzDenied) as ei:
                check(alice, "change.approve", subject=cr)
        assert ei.value.permission == "change.approve"

    def test_always_enforced_rule_raises_even_in_shadow(self, policy):
        from agenticops.config import settings
        plan = SimpleNamespace(id=2, risk_level="L3", requested_by=None)
        with patch.object(settings, "rbac_enforce", False), \
             patch("agenticops.audit.service.AuditService.log"):
            with pytest.raises(AuthzDenied):
                check(agent_actor("sre"), "plan.approve", subject=plan)

    def test_allowed_is_silent(self, policy):
        with patch("agenticops.audit.service.AuditService.log") as log:
            check(cli_actor(), "change.request")
        assert not log.called
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_authz.py -q`
Expected: FAIL — `ModuleNotFoundError: agenticops.auth.actor`

- [ ] **Step 3: 配置项**

`config.py`（`admin_password` Field 之后）：

```python
    # ── RBAC seam (MVP-2.6.0) ─────────────────────────────────────────
    rbac_enforce: bool = Field(
        default=False,
        description="Enforce config/rbac.yaml (403 + separation of duties). False = shadow mode: "
        "decisions are evaluated and denials audited as authz.denied_shadow, but allowed (AIOPS_RBAC_ENFORCE)",
    )
    rbac_file: str = Field(
        default="config/rbac.yaml",
        description="Path to the RBAC permission matrix (AIOPS_RBAC_FILE)",
    )
```

`config/settings.yaml`（`api_auth_enabled: false` 之后）：

```yaml
rbac_enforce: false          # shadow mode by default — see config/rbac.yaml
rbac_file: config/rbac.yaml
```

CLAUDE.md 配置表加：

```
| `rbac_enforce` | `false` | Enforce `config/rbac.yaml` (403 + SoD). False = shadow mode: denials audited as `authz.denied_shadow`, request allowed |
| `rbac_file` | `config/rbac.yaml` | Permission matrix (permission → required `users.permissions` flags) + built-in subjects + structured SoD rules |
```

- [ ] **Step 4: `config/rbac.yaml`**

```yaml
# AgenticOps RBAC matrix (MVP-2.6.0). Loaded by agenticops.auth.authz.
#
# permissions: permission item → the users.permissions flags an authenticated user needs
#              (users.permissions is the JSON list ["read","write","admin"] on the users table).
# subjects:    default flags for actors that have no users row.
#              `anonymous` (web with api_auth_enabled=false) is deliberately all-powerful — it is
#              exactly what an unauthenticated deployment allows today.
# rules:       structured deny rules, evaluated after the matrix. Only two types exist:
#                actor_must_differ_from_field  — str(actor) != getattr(subject, field)      (SoD)
#                deny_actor_kind_when_risk_in  — actor.kind == actor_kind and subject.risk_level in risk_levels
#              `enforce: always` makes a rule bite even in shadow mode (rbac_enforce=false).
version: 1

permissions:
  change.request: [read]
  change.review:  [write]
  change.approve: [write]
  change.reject:  [write]
  change.cancel:  [write]
  change.execute: [write]
  plan.approve:   [write]
  plan.reject:    [write]
  plan.execute:   [write]
  audit.read:     [admin]

subjects:
  anonymous: [read, write, admin]
  cli:       [read, write, admin]
  agents:    [read, write]
  im:        [read]
  webhook:   [read]

rules:
  - name: sod-change-approver-not-requester
    permission: change.approve
    type: actor_must_differ_from_field
    field: requested_by

  - name: no-agent-approval-above-l1
    permission: [plan.approve, change.approve]
    type: deny_actor_kind_when_risk_in
    actor_kind: agent
    risk_levels: [L2, L3]
    enforce: always
```

- [ ] **Step 5: `auth/actor.py`**

```python
"""Actor — who is acting (MVP-2.6.0). One string form everywhere: "<kind>:<id>".

kinds: user (authenticated web user, id=email) | web (anonymous) | cli (os user) |
       agent (auto paths) | im (platform:sender) | webhook (source, P2).
"""

from __future__ import annotations

import getpass
from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class Actor:
    kind: str
    id: str
    user_id: Optional[int] = None
    permissions: tuple[str, ...] = ()

    @property
    def key(self) -> str:
        return f"{self.kind}:{self.id}"

    def __str__(self) -> str:  # so f"{actor}" gives the key
        return self.key


def web_anonymous_actor() -> Actor:
    return Actor("web", "anonymous")


def actor_from_user(user: Any) -> Actor:
    perms = tuple(getattr(user, "permissions", None) or ())
    return Actor("user", str(getattr(user, "email", "") or getattr(user, "id", "")), getattr(user, "id", None), perms)


def actor_from_request(request: Any) -> Actor:
    user = getattr(getattr(request, "state", None), "user", None)
    if user is None:
        return web_anonymous_actor()
    return actor_from_user(user)


def cli_actor() -> Actor:
    try:
        return Actor("cli", getpass.getuser())
    except Exception:
        return Actor("cli", "unknown")


def agent_actor(name: str) -> Actor:
    return Actor("agent", name)


def im_actor(platform: str, sender_id: str) -> Actor:
    return Actor("im", f"{platform}:{sender_id}")


def webhook_actor(source: str) -> Actor:
    return Actor("webhook", source)


def parse_actor(text: str) -> Actor:
    """Reconstruct an Actor from its key. Legacy free-text names (no colon) become web:<text>."""
    text = (text or "").strip()
    if ":" not in text:
        return Actor("web", text or "anonymous")
    kind, _, rest = text.partition(":")
    return Actor(kind, rest)
```

- [ ] **Step 6: `auth/authz.py`**

```python
"""authz — the single authorization checkpoint (MVP-2.6.0).

check(actor, permission, subject) evaluates config/rbac.yaml:
  1. matrix: required flags ⊆ actor flags (users.permissions for user actors, `subjects` for others)
  2. rules:  structured deny rules (SoD, agent risk ceiling)
Denials raise AuthzDenied when settings.rbac_enforce is true OR the matching rule says
`enforce: always`; otherwise (shadow mode) the denial is written to audit_logs as
`authz.denied_shadow` and the call is allowed — i.e. behavior is exactly today's.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from agenticops.auth.actor import Actor

logger = logging.getLogger(__name__)

PERMISSIONS = (
    "change.request", "change.review", "change.approve", "change.reject", "change.cancel", "change.execute",
    "plan.approve", "plan.reject", "plan.execute", "audit.read",
)

_RULE_TYPES = {"actor_must_differ_from_field", "deny_actor_kind_when_risk_in"}

DEFAULT_POLICY: dict = {
    "version": 1,
    "permissions": {
        "change.request": ["read"], "change.review": ["write"], "change.approve": ["write"],
        "change.reject": ["write"], "change.cancel": ["write"], "change.execute": ["write"],
        "plan.approve": ["write"], "plan.reject": ["write"], "plan.execute": ["write"],
        "audit.read": ["admin"],
    },
    "subjects": {
        "anonymous": ["read", "write", "admin"], "cli": ["read", "write", "admin"],
        "agents": ["read", "write"], "im": ["read"], "webhook": ["read"],
    },
    "rules": [
        {"name": "sod-change-approver-not-requester", "permission": "change.approve",
         "type": "actor_must_differ_from_field", "field": "requested_by"},
        {"name": "no-agent-approval-above-l1", "permission": ["plan.approve", "change.approve"],
         "type": "deny_actor_kind_when_risk_in", "actor_kind": "agent", "risk_levels": ["L2", "L3"],
         "enforce": "always"},
    ],
}

_SUBJECT_KEY = {"web": "anonymous", "cli": "cli", "agent": "agents", "im": "im", "webhook": "webhook"}


class AuthzDenied(Exception):
    def __init__(self, actor: str, permission: str, reason: str, rule: Optional[str] = None):
        super().__init__(f"{actor} is not allowed to {permission}: {reason}")
        self.actor, self.permission, self.reason, self.rule = actor, permission, reason, rule


@dataclass
class RbacPolicy:
    permissions: dict[str, list[str]] = field(default_factory=dict)
    subjects: dict[str, list[str]] = field(default_factory=dict)
    rules: list[dict] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "RbacPolicy":
        return cls(
            permissions=dict(data.get("permissions") or {}),
            subjects=dict(data.get("subjects") or {}),
            rules=list(data.get("rules") or []),
        )

    @classmethod
    def load(cls, path: str | Path | None = None) -> "RbacPolicy":
        import yaml
        if path is None:
            from agenticops.config import settings
            path = settings.rbac_file
        p = Path(path)
        if not p.is_absolute():
            from agenticops.config import PROJECT_ROOT
            p = PROJECT_ROOT / p
        if not p.exists():
            logger.info("rbac file %s not found — using built-in defaults", p)
            return cls.from_dict(DEFAULT_POLICY)
        try:
            data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            errors = validate_rbac(data)
            if errors:
                raise ValueError("; ".join(errors))
            return cls.from_dict(data)
        except Exception as e:
            logger.error("Failed to load rbac file %s (%s) — using built-in defaults", p, e)
            return cls.from_dict(DEFAULT_POLICY)

    def effective_permissions(self, actor: Actor) -> set[str]:
        if actor.kind == "user":
            return set(actor.permissions)
        if actor.permissions:
            return set(actor.permissions)
        return set(self.subjects.get(_SUBJECT_KEY.get(actor.kind, actor.kind), []))

    def decide(self, actor: Actor, permission: str, subject: Any) -> tuple[bool, str, Optional[str], bool]:
        """Returns (allowed, reason, rule_name, always_enforce)."""
        required = set(self.permissions.get(permission, ["admin"]))
        have = self.effective_permissions(actor)
        if not required.issubset(have):
            missing = ", ".join(sorted(required - have))
            return False, f"missing permission flag(s): {missing}", None, False
        for rule in self.rules:
            perms = rule.get("permission")
            perms = [perms] if isinstance(perms, str) else list(perms or [])
            if permission not in perms:
                continue
            always = str(rule.get("enforce", "")).lower() == "always"
            rtype = rule.get("type")
            if rtype == "actor_must_differ_from_field" and subject is not None:
                other = getattr(subject, rule.get("field", ""), None)
                if other and str(other) == actor.key:
                    return False, f"separation of duties: actor equals {rule.get('field')}", rule.get("name"), always
            elif rtype == "deny_actor_kind_when_risk_in" and subject is not None:
                risk = getattr(subject, "risk_level", None)
                if actor.kind == rule.get("actor_kind") and risk in (rule.get("risk_levels") or []):
                    return False, f"{actor.kind} actors may not {permission} at risk {risk}", rule.get("name"), always
        return True, "allowed", None, False


def validate_rbac(data: dict) -> list[str]:
    errors: list[str] = []
    if not isinstance(data.get("permissions", {}), dict):
        errors.append("'permissions' must be a mapping")
    for i, rule in enumerate(data.get("rules") or []):
        label = rule.get("name") or f"rules[{i}]"
        if rule.get("type") not in _RULE_TYPES:
            errors.append(f"{label}: unknown rule type {rule.get('type')!r}")
        if not rule.get("permission"):
            errors.append(f"{label}: 'permission' is required")
    return errors


_policy: Optional[RbacPolicy] = None
_policy_lock = threading.Lock()


def get_rbac_policy(reload: bool = False) -> RbacPolicy:
    global _policy
    with _policy_lock:
        if _policy is None or reload:
            _policy = RbacPolicy.load()
        return _policy


def _audit_shadow_denial(actor: Actor, permission: str, reason: str, rule: Optional[str], subject: Any, enforced: bool) -> None:
    try:
        from agenticops.audit.service import AuditService
        entity_type = type(subject).__name__.lower() if subject is not None else "system"
        entity_id = str(getattr(subject, "id", "") or "-")
        AuditService.log(
            action="authz.denied" if enforced else "authz.denied_shadow",
            entity_type=entity_type, entity_id=entity_id, actor=actor.key, user_id=actor.user_id,
            details={"permission": permission, "reason": reason, "rule": rule},
        )
    except Exception:
        logger.debug("authz audit write failed", exc_info=True)


def check(actor: Actor, permission: str, subject: Any = None) -> None:
    """Raise AuthzDenied when denied under enforce (or an always-enforced rule); shadow otherwise."""
    from agenticops.config import settings
    if permission not in PERMISSIONS:
        raise ValueError(f"unknown permission {permission!r}")
    allowed, reason, rule, always = get_rbac_policy().decide(actor, permission, subject)
    if allowed:
        return
    enforced = bool(settings.rbac_enforce) or always
    _audit_shadow_denial(actor, permission, reason, rule, subject, enforced)
    if enforced:
        raise AuthzDenied(actor.key, permission, reason, rule)
    logger.info("authz shadow: %s would be denied %s (%s)", actor.key, permission, reason)
```

`AuditService.log(..., actor=…)` 的 `actor` 关键字在 Task 7 才加；本 Task 的测试 patch 掉了 `AuditService.log`，所以顺序无碍——但 Task 7 完成前**不要**在真实路径调用 `check`（Task 8/9 才接入）。

- [ ] **Step 7: 跑测试确认通过**

Run: `python -m pytest tests/test_authz.py -q`
Expected: 16 PASS

- [ ] **Step 8: Commit**

```bash
git add src/agenticops/auth/actor.py src/agenticops/auth/authz.py config/rbac.yaml src/agenticops/config.py config/settings.yaml CLAUDE.md tests/test_authz.py
git commit -m "feat(auth): Actor resolution, rbac.yaml matrix + SoD rules, authz checkpoint with shadow mode"
```

---

### Task 7: `AuditService` 扩展（`actor`、同事务 `session`、新 Actions/EntityTypes、每日保留期清理）+ `AuditLogResponse.actor`

**Files:**
- Modify: `src/agenticops/audit/service.py`（`Actions` :20-45、`EntityTypes` :52-64、`AuditService.log` :87-145、末尾加 `maybe_prune_daily`）
- Modify: `src/agenticops/web/schemas.py:764-779`（`AuditLogResponse` 加 `actor: Optional[str] = None`）
- Modify: `src/agenticops/config.py`（`audit_retention_days`）、`config/settings.yaml`、`CLAUDE.md`
- Test: `tests/test_audit_service_actor.py`

**Interfaces:**
- Produces: `AuditService.log(action, entity_type, entity_id, *, entity_name=None, user_id=None, user_email=None, actor=None, details=None, old_values=None, new_values=None, ip_address=None, user_agent=None, request_id=None, session=None) -> AuditLog`（传 `session` 时不开新 session、不 commit——调用方同事务提交）；`Actions.CHANGE_REQUESTED = "change.requested"` … 见下；`EntityTypes.CHANGE_REQUEST = "change_request"`, `EntityTypes.FIX_PLAN = "fix_plan"`；`AuditService.maybe_prune_daily() -> None`（每进程每日一次，删 `audit_logs` 与 `command_audits` 中早于 `audit_retention_days` 的行）。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_audit_service_actor.py
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from agenticops.models import Base, CommandAudit, get_engine, get_session


@pytest.fixture
def db(tmp_path):
    import agenticops.models as models_mod
    import agenticops.audit.models  # noqa: F401
    from agenticops.config import settings
    models_mod._engine = None
    settings.database_url = f"sqlite:///{tmp_path}/audit.db"
    Base.metadata.create_all(models_mod.get_engine())
    s = get_session()
    yield s
    s.close()
    models_mod._engine = None


def test_log_records_actor(db):
    from agenticops.audit.service import Actions, AuditService, EntityTypes
    from agenticops.audit.models import AuditLog
    AuditService.log(Actions.PLAN_APPROVED, EntityTypes.FIX_PLAN, "9", actor="user:admin",
                     details={"reason": "ok"}, old_values={"status": "draft"}, new_values={"status": "approved"})
    row = db.query(AuditLog).one()
    assert row.actor == "user:admin" and row.action == "plan.approved" and row.entity_type == "fix_plan"


def test_log_with_caller_session_does_not_commit(db):
    from agenticops.audit.service import Actions, AuditService, EntityTypes
    from agenticops.audit.models import AuditLog
    AuditService.log(Actions.CHANGE_REQUESTED, EntityTypes.CHANGE_REQUEST, "1", actor="cli:x", session=db)
    db.rollback()
    assert db.query(AuditLog).count() == 0  # never committed by the service
    AuditService.log(Actions.CHANGE_REQUESTED, EntityTypes.CHANGE_REQUEST, "1", actor="cli:x", session=db)
    db.commit()
    assert db.query(AuditLog).count() == 1


def test_new_action_constants_exist():
    from agenticops.audit.service import Actions
    for name in ("CHANGE_REQUESTED", "CHANGE_REVIEWED", "CHANGE_CLARIFIED", "CHANGE_APPROVED", "CHANGE_REJECTED",
                 "CHANGE_CANCELLED", "CHANGE_EXECUTION_STARTED", "CHANGE_COMPLETED", "CHANGE_FAILED",
                 "CHANGE_ROLLED_BACK", "CHANGE_NEEDS_REVIEW", "PLAN_APPROVED", "PLAN_REJECTED",
                 "PLAN_EXECUTE_REQUESTED", "AUTHZ_DENIED", "AUTHZ_DENIED_SHADOW"):
        assert getattr(Actions, name).startswith(("change.", "plan.", "authz."))


def test_prune_daily_deletes_old_rows_once_per_day(db):
    from agenticops.audit import service as svc
    from agenticops.audit.models import AuditLog
    from agenticops.config import settings
    old = datetime.now(timezone.utc) - timedelta(days=400)
    db.add(AuditLog(action="x", entity_type="t", entity_id="1", timestamp=old))
    db.add(AuditLog(action="y", entity_type="t", entity_id="2"))
    db.add(CommandAudit(actor="a", tool="run_aws_cli", tier="write", command="c", outcome="executed", created_at=old))
    db.commit()
    svc._last_prune_date = None
    with patch.object(settings, "audit_retention_days", 365):
        svc.AuditService.maybe_prune_daily()
    db.expire_all()
    assert db.query(AuditLog).count() == 1
    assert db.query(CommandAudit).count() == 0
    # second call same day is a no-op even if new old rows appear
    db.add(AuditLog(action="z", entity_type="t", entity_id="3", timestamp=old)); db.commit()
    svc.AuditService.maybe_prune_daily()
    db.expire_all()
    assert db.query(AuditLog).count() == 2


def test_prune_disabled_when_retention_zero(db):
    from agenticops.audit import service as svc
    from agenticops.audit.models import AuditLog
    from agenticops.config import settings
    db.add(AuditLog(action="x", entity_type="t", entity_id="1", timestamp=datetime(2000, 1, 1))); db.commit()
    svc._last_prune_date = None
    with patch.object(settings, "audit_retention_days", 0):
        svc.AuditService.maybe_prune_daily()
    assert db.query(AuditLog).count() == 1
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_audit_service_actor.py -q`
Expected: FAIL — `TypeError: log() got an unexpected keyword argument 'actor'`

- [ ] **Step 3: 实现**

`config.py`（rbac 块之后）：

```python
    audit_retention_days: int = Field(
        default=365,
        description="Days of audit_logs + command_audits rows retained; 0 disables pruning (AIOPS_AUDIT_RETENTION_DAYS)",
    )
```
`settings.yaml`：`audit_retention_days: 365`。CLAUDE.md 配置表：`| audit_retention_days | 365 | Retention for audit_logs + command_audits (daily prune; 0 = keep forever) |`。

`audit/service.py`：`Actions` 类末尾加

```python
    # ── Change Management (MVP-2.6.0) — dotted names, one per decision ──
    CHANGE_REQUESTED = "change.requested"
    CHANGE_REVIEWED = "change.reviewed"
    CHANGE_CLARIFIED = "change.clarified"
    CHANGE_APPROVED = "change.approved"
    CHANGE_REJECTED = "change.rejected"
    CHANGE_CANCELLED = "change.cancelled"
    CHANGE_EXECUTION_STARTED = "change.execution_started"
    CHANGE_COMPLETED = "change.completed"
    CHANGE_FAILED = "change.failed"
    CHANGE_ROLLED_BACK = "change.rolled_back"
    CHANGE_NEEDS_REVIEW = "change.needs_review"
    PLAN_APPROVED = "plan.approved"
    PLAN_REJECTED = "plan.rejected"
    PLAN_EXECUTE_REQUESTED = "plan.execute_requested"
    AUTHZ_DENIED = "authz.denied"
    AUTHZ_DENIED_SHADOW = "authz.denied_shadow"
```

`EntityTypes` 加 `CHANGE_REQUEST = "change_request"`、`FIX_PLAN = "fix_plan"`。

`AuditService.log` 签名与体改为：

```python
    @staticmethod
    def log(
        action: str,
        entity_type: str,
        entity_id: str,
        entity_name: Optional[str] = None,
        user_id: Optional[int] = None,
        user_email: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        old_values: Optional[Dict[str, Any]] = None,
        new_values: Optional[Dict[str, Any]] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        request_id: Optional[str] = None,
        actor: Optional[str] = None,
        session=None,
    ) -> AuditLog:
        """Create an audit log entry.

        `actor` is the actor key (user:x / cli:x / agent:x / im:p:x). When `session` is given the
        row is added to THAT session and NOT committed — the caller commits it together with the
        state change it audits (decision + state in one transaction). Without `session` the row is
        written in its own transaction (legacy behavior).
        """
        audit_log = AuditLog(
            action=action, entity_type=entity_type, entity_id=str(entity_id), entity_name=entity_name,
            user_id=user_id, user_email=user_email, actor=actor, details=details or {},
            old_values=old_values, new_values=new_values, ip_address=ip_address,
            user_agent=user_agent, request_id=request_id,
        )
        if session is not None:
            session.add(audit_log)
            session.flush()
            return audit_log
        init_db()
        with get_db_session() as db:
            db.add(audit_log)
            db.flush()
            logger.info("Audit: %s %s/%s by %s", action, entity_type, entity_id, actor or user_email or user_id or "system")
            return audit_log
```

文件末尾（`log_action` 之前）加模块级 `_last_prune_date = None` 与：

```python
    @staticmethod
    def maybe_prune_daily() -> None:
        """Once per process-day: delete audit_logs + command_audits older than audit_retention_days."""
        global _last_prune_date
        from agenticops.config import settings
        days = int(getattr(settings, "audit_retention_days", 0) or 0)
        today = datetime.now(timezone.utc).date()
        if days <= 0 or _last_prune_date == today:
            return
        _last_prune_date = today
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        try:
            from agenticops.models import CommandAudit
            with get_db_session() as db:
                a = db.query(AuditLog).filter(AuditLog.timestamp < cutoff).delete(synchronize_session=False)
                c = db.query(CommandAudit).filter(CommandAudit.created_at < cutoff).delete(synchronize_session=False)
            if a or c:
                logger.info("audit: pruned %d audit_logs + %d command_audits older than %dd", a, c, days)
        except Exception:
            logger.debug("audit prune failed", exc_info=True)
```

（`maybe_prune_daily` 是 `AuditService` 的 staticmethod，`_last_prune_date` 是模块全局；`global` 语句放在方法内第一行。）`schemas.py` 的 `AuditLogResponse` 加 `actor: Optional[str] = None`。

- [ ] **Step 4: 跑测试**

Run: `python -m pytest tests/test_audit_service_actor.py tests/test_authz.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/agenticops/audit/service.py src/agenticops/web/schemas.py src/agenticops/config.py config/settings.yaml CLAUDE.md tests/test_audit_service_actor.py
git commit -m "feat(audit): actor + same-transaction logging, change/plan/authz actions, daily retention prune"
```

---

### Task 8: `web/deps.current_actor` + FixPlan 端点加固（身份绑定、理由、审计、reject 端点、`PUT` 收紧、`kind` 筛选、响应新字段）

**Files:**
- Create: `src/agenticops/web/deps.py`
- Modify: `src/agenticops/web/schemas.py`（`FixPlanUpdate` :334-345、`FixPlanResponse` :348-367、`FixExecutionResponse.health_issue_id`；新增 `FixPlanApproveBody`、`FixPlanRejectBody`）
- Modify: `src/agenticops/web/app.py`（`api_list_fix_plans` :2264-2298、`api_get_fix_plan` :2301-2311、`api_update_fix_plan` :2362-2375、`api_approve_fix_plan` :2378-2424、新增 `api_reject_fix_plan`、`api_execute_fix_plan` :2442-2477）
- Test: `tests/test_fix_plan_hardening_api.py`

**Interfaces:**
- Produces: `current_actor(request) -> Actor`（FastAPI 依赖：解析 actor、`update_run_context(actor=..., actor_user_id=..., trace_id=当前 trace)`，请求结束不重置——每个请求在独立 task 里跑，ContextVar 自然隔离）；`FixPlanApproveBody(approved_by: Optional[str]=None, reason: Optional[str]=None)`；`FixPlanRejectBody(reason: str = Field(..., min_length=1))`；`FixPlanResponse` 新字段 `plan_kind: str = "fix"`, `change_request_id: Optional[int] = None`, `rejected_by/rejected_at/rejection_reason/updated_at` Optional, `health_issue_id/rca_result_id: Optional[int]`；`POST /api/fix-plans/{id}/reject`；`GET /api/fix-plans?kind=fix|change`。
- 契约：approve 的 `approved_by` 只在 **actor 是 web:anonymous** 时作为 `claimed_name` 记进审计 details，`plan.approved_by` 永远写 `actor.key`；`PUT /api/fix-plans/{id}` 只接受内容字段，`status`/`approved_by` 被 Pydantic 拒绝（422）——**唯一例外**：`{"status": "rejected"}` 作为已弃用别名转到 reject 逻辑（旧前端在 Plan C 之前还在用），其他 status 值 400。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_fix_plan_hardening_api.py
"""Identity-bound approval, reject endpoint, tightened PUT, kind filter (MVP-2.6.0 S1)."""
import pytest
from starlette.testclient import TestClient

from agenticops.models import Base, FixPlan, HealthIssue, RCAResult, get_session


@pytest.fixture
def client(tmp_path):
    import agenticops.models as models_mod
    import agenticops.audit.models  # noqa: F401
    from agenticops.config import settings
    from agenticops.web.app import app
    models_mod._engine = None
    settings.database_url = f"sqlite:///{tmp_path}/api.db"
    Base.metadata.create_all(models_mod.get_engine())
    yield TestClient(app)
    models_mod._engine = None


def _plan(status="pending_approval", risk="L1") -> int:
    s = get_session()
    try:
        issue = HealthIssue(title="t", description="d", severity="low", source="test", status="fix_planned", resource_id="r")
        s.add(issue); s.flush()
        rca = RCAResult(health_issue_id=issue.id, root_cause="x", confidence=0.9)
        s.add(rca); s.flush()
        plan = FixPlan(health_issue_id=issue.id, rca_result_id=rca.id, risk_level=risk, title="p", summary="s", status=status)
        s.add(plan); s.commit()
        return plan.id
    finally:
        s.close()


def _audit_rows(action=None):
    from agenticops.audit.models import AuditLog
    s = get_session()
    try:
        q = s.query(AuditLog)
        if action:
            q = q.filter_by(action=action)
        return q.all()
    finally:
        s.close()


def test_approve_binds_identity_not_body(client, monkeypatch):
    from unittest.mock import patch
    pid = _plan()
    with patch("agenticops.services.pipeline_service.trigger_auto_execute"):
        r = client.put(f"/api/fix-plans/{pid}/approve", json={"approved_by": "Mallory", "reason": "looks fine"})
    assert r.status_code == 200
    body = r.json()
    assert body["approved_by"] == "web:anonymous"      # auth disabled → anonymous actor, never the client string
    rows = _audit_rows("plan.approved")
    assert len(rows) == 1
    assert rows[0].actor == "web:anonymous"
    assert rows[0].details["claimed_name"] == "Mallory" and rows[0].details["reason"] == "looks fine"
    assert rows[0].old_values == {"status": "pending_approval"} and rows[0].new_values == {"status": "approved"}


def test_reject_endpoint_requires_reason(client):
    pid = _plan()
    r = client.post(f"/api/fix-plans/{pid}/reject", json={})
    assert r.status_code == 422
    r = client.post(f"/api/fix-plans/{pid}/reject", json={"reason": "not needed"})
    assert r.status_code == 200
    assert r.json()["status"] == "rejected" and r.json()["rejected_by"] == "web:anonymous"
    assert r.json()["rejection_reason"] == "not needed"
    assert len(_audit_rows("plan.rejected")) == 1


def test_reject_terminal_plan_is_409(client):
    pid = _plan(status="executed")
    r = client.post(f"/api/fix-plans/{pid}/reject", json={"reason": "late"})
    assert r.status_code == 409


def test_put_no_longer_accepts_status_or_approver(client):
    pid = _plan(status="draft")
    r = client.put(f"/api/fix-plans/{pid}", json={"approved_by": "x"})
    assert r.status_code == 422
    r = client.put(f"/api/fix-plans/{pid}", json={"status": "approved"})
    assert r.status_code == 400
    r = client.put(f"/api/fix-plans/{pid}", json={"title": "renamed"})
    assert r.status_code == 200 and r.json()["title"] == "renamed"


def test_put_status_rejected_is_a_deprecated_alias(client):
    pid = _plan(status="draft")
    r = client.put(f"/api/fix-plans/{pid}", json={"status": "rejected"})
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    assert r.json()["rejection_reason"] == "(rejected via deprecated PUT status)"
    assert len(_audit_rows("plan.rejected")) == 1


def test_execute_records_actor(client):
    from unittest.mock import patch
    from agenticops.config import settings
    pid = _plan(status="approved")
    with patch.object(settings, "executor_enabled", True):
        r = client.post(f"/api/fix-plans/{pid}/execute", json={})
    assert r.status_code == 202
    assert r.json()["executed_by"] == "web:anonymous"
    assert len(_audit_rows("plan.execute_requested")) == 1


def test_list_kind_filter_and_new_fields(client):
    _plan(status="draft")
    r = client.get("/api/fix-plans?kind=fix")
    assert r.status_code == 200 and len(r.json()) == 1
    row = r.json()[0]
    assert row["plan_kind"] == "fix" and row["change_request_id"] is None and "rejected_by" in row
    assert client.get("/api/fix-plans?kind=change").json() == []
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_fix_plan_hardening_api.py -q`
Expected: 多数 FAIL（approved_by 回显 "Mallory"、reject 404、PUT 接受 approved_by）

- [ ] **Step 3: `web/deps.py`**

```python
"""FastAPI dependencies shared by routers (MVP-2.6.0)."""

from __future__ import annotations

from fastapi import Request

from agenticops.auth.actor import Actor, actor_from_request
from agenticops.run_context import update_run_context


def current_actor(request: Request) -> Actor:
    """Resolve the acting identity for this request and stamp it on the Run Context.

    api_auth_enabled=true → APIAuthMiddleware put the User on request.state → user:<email>.
    Otherwise → web:anonymous (exactly today's trust level). Never reads identity from the body.
    """
    actor = actor_from_request(request)
    from agenticops.config import get_trace_id
    update_run_context(actor=actor.key, actor_user_id=actor.user_id, trace_id=get_trace_id())
    return actor
```

- [ ] **Step 4: `schemas.py`**

```python
class FixPlanUpdate(BaseModel):
    """Content-only update. Status changes go through /approve, /reject, /execute.
    `status: "rejected"` is still accepted as a DEPRECATED alias for POST /reject (old UI)."""
    model_config = ConfigDict(extra="forbid")
    risk_level: Optional[str] = Field(None, pattern="^(L0|L1|L2|L3)$")
    title: Optional[str] = Field(None, max_length=300)
    summary: Optional[str] = None
    steps: Optional[List] = None
    rollback_plan: Optional[dict] = None
    estimated_impact: Optional[str] = None
    pre_checks: Optional[List] = None
    post_checks: Optional[List] = None
    status: Optional[str] = Field(None, pattern="^(rejected)$", description="DEPRECATED alias for POST /reject")


class FixPlanApproveBody(BaseModel):
    approved_by: Optional[str] = Field(None, max_length=100, description="Legacy claimed name; audited, never trusted")
    reason: Optional[str] = Field(None, max_length=2000)


class FixPlanRejectBody(BaseModel):
    reason: str = Field(..., min_length=1, max_length=2000)


class FixPlanResponse(BaseModel):
    """Schema for fix plan response."""
    id: int
    plan_kind: str = "fix"
    health_issue_id: Optional[int] = None
    rca_result_id: Optional[int] = None
    change_request_id: Optional[int] = None
    risk_level: str
    title: str
    summary: str
    steps: list
    rollback_plan: dict
    estimated_impact: str
    pre_checks: list
    post_checks: list
    status: str
    approved_by: Optional[str]
    approved_at: Optional[datetime]
    rejected_by: Optional[str] = None
    rejected_at: Optional[datetime] = None
    rejection_reason: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    account_id: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)
```

`FixExecutionResponse.health_issue_id: Optional[int] = None`。`test_put_no_longer_accepts_status_or_approver` 期望 `{"status": "approved"}` → 400：Pydantic pattern 会先给 422；把 `status` 的 `pattern` 去掉、改在处理器里判断（非 `rejected` → 400）。**采用处理器判断**（`status: Optional[str] = Field(None, description=...)`）。

- [ ] **Step 5: `app.py` 端点**

import 处加 `from agenticops.web.deps import current_actor`、`from agenticops.auth.actor import Actor`、`from fastapi import Depends`（若未导入）、schemas 里加 `FixPlanApproveBody, FixPlanRejectBody`。加一个模块级辅助（放在 FixPlan API 区块前）：

```python
def _fix_plan_response(session, plan) -> FixPlanResponse:
    resp = FixPlanResponse.model_validate(plan)
    if plan.health_issue_id:
        resp.account_id = session.query(HealthIssue.account_id).filter_by(id=plan.health_issue_id).scalar()
    return resp


def _reject_plan(session, plan, actor: Actor, reason: str) -> None:
    """Shared by POST /reject and the deprecated PUT status alias. Raises HTTPException 409."""
    from agenticops.audit.service import Actions, AuditService, EntityTypes
    from agenticops.auth import authz
    from agenticops.models import InvalidStatusTransition, transition_plan
    try:
        authz.check(actor, "plan.reject", subject=plan)
    except authz.AuthzDenied as e:
        raise HTTPException(status_code=403, detail=str(e))
    old = plan.status
    try:
        transition_plan(plan, "rejected")
    except InvalidStatusTransition as e:
        raise HTTPException(status_code=409, detail=str(e))
    plan.rejected_by = actor.key
    plan.rejected_at = datetime.now(timezone.utc)
    plan.rejection_reason = reason
    AuditService.log(Actions.PLAN_REJECTED, EntityTypes.FIX_PLAN, str(plan.id), actor=actor.key,
                     user_id=actor.user_id, details={"reason": reason, "risk_level": plan.risk_level},
                     old_values={"status": old}, new_values={"status": "rejected"}, session=session)
```

`api_list_fix_plans` 加参数 `kind: Optional[str] = Query(None, pattern="^(fix|change)$")`，查询里 `if kind: query = query.filter_by(plan_kind=kind)`；`issue_ids = {p.health_issue_id for p in plans if p.health_issue_id}`；结果用 `_fix_plan_response`（或保留原逻辑但跳过 None）。`api_get_fix_plan` 用 `_fix_plan_response`。

`api_update_fix_plan`：

```python
@app.put("/api/fix-plans/{plan_id}", response_model=FixPlanResponse)
async def api_update_fix_plan(plan_id: int, data: FixPlanUpdate, actor: Actor = Depends(current_actor)):
    """Update plan CONTENT. Status changes must use /approve, /reject, /execute
    (status="rejected" is kept as a deprecated alias for the pre-2.6 UI)."""
    with get_db_session() as session:
        plan = session.query(FixPlan).filter_by(id=plan_id).first()
        if not plan:
            raise HTTPException(status_code=404, detail="Fix plan not found")
        update_data = data.model_dump(exclude_unset=True)
        status_alias = update_data.pop("status", None)
        if status_alias is not None and status_alias != "rejected":
            raise HTTPException(status_code=400, detail="Status changes must use /approve, /reject or /execute")
        for key, value in update_data.items():
            setattr(plan, key, value)
        if status_alias == "rejected":
            _reject_plan(session, plan, actor, "(rejected via deprecated PUT status)")
        plan.updated_at = datetime.now(timezone.utc)
        session.flush()
        return _fix_plan_response(session, plan)
```

`api_approve_fix_plan`：

```python
@app.put("/api/fix-plans/{plan_id}/approve", response_model=FixPlanResponse)
async def api_approve_fix_plan(plan_id: int, data: FixPlanApproveBody = Body(default=FixPlanApproveBody()),
                               actor: Actor = Depends(current_actor)):
    """Approve a plan as the authenticated actor. The body's approved_by is a legacy claimed name:
    it is audited (details.claimed_name) but never stored as the approver."""
    from agenticops.audit.service import Actions, AuditService, EntityTypes
    from agenticops.auth import authz
    from agenticops.models import InvalidStatusTransition, transition_plan
    with get_db_session() as session:
        plan = session.query(FixPlan).filter_by(id=plan_id).first()
        if not plan:
            raise HTTPException(status_code=404, detail="Fix plan not found")
        if plan.status == "approved":
            raise HTTPException(status_code=400, detail="Fix plan is already approved")
        if plan.status == "rejected":
            raise HTTPException(status_code=400, detail="Fix plan was rejected. Create a new plan instead")
        try:
            authz.check(actor, "plan.approve", subject=plan)
        except authz.AuthzDenied as e:
            raise HTTPException(status_code=403, detail=str(e))
        old = plan.status
        try:
            transition_plan(plan, "approved")
        except InvalidStatusTransition as e:
            raise HTTPException(status_code=409, detail=str(e))
        plan.approved_by = actor.key
        plan.approved_at = datetime.now(timezone.utc)
        issue = session.query(HealthIssue).filter_by(id=plan.health_issue_id).first() if plan.health_issue_id else None
        if issue:
            issue.status = "fix_approved"
        details = {"reason": data.reason, "risk_level": plan.risk_level, "plan_kind": plan.plan_kind}
        if data.approved_by and actor.kind == "web":
            details["claimed_name"] = data.approved_by
        AuditService.log(Actions.PLAN_APPROVED, EntityTypes.FIX_PLAN, str(plan.id), actor=actor.key,
                         user_id=actor.user_id, details=details,
                         old_values={"status": old}, new_values={"status": "approved"}, session=session)
        approved_plan_id = plan.id
        session.flush()
        response = _fix_plan_response(session, plan)
    try:
        from agenticops.services.pipeline_service import trigger_auto_execute
        trigger_auto_execute(approved_plan_id)
    except Exception:
        logger.warning("Failed to trigger auto-execute for plan #%d", approved_plan_id, exc_info=True)
    return response


@app.post("/api/fix-plans/{plan_id}/reject", response_model=FixPlanResponse)
async def api_reject_fix_plan(plan_id: int, data: FixPlanRejectBody, actor: Actor = Depends(current_actor)):
    """Reject a draft / pending / approved (withdraw) plan with a mandatory reason."""
    with get_db_session() as session:
        plan = session.query(FixPlan).filter_by(id=plan_id).first()
        if not plan:
            raise HTTPException(status_code=404, detail="Fix plan not found")
        _reject_plan(session, plan, actor, data.reason)
        session.flush()
        return _fix_plan_response(session, plan)
```

`api_execute_fix_plan`：签名改为 `async def api_execute_fix_plan(plan_id: int, actor: Actor = Depends(current_actor))`（去掉 `executed_by` Body），`authz.check(actor, "plan.execute", subject=plan)`（403），`transition_plan(plan, "executing")`，`FixExecution(..., executed_by=actor.key)`，然后 `AuditService.log(Actions.PLAN_EXECUTE_REQUESTED, EntityTypes.FIX_PLAN, str(plan.id), actor=actor.key, user_id=actor.user_id, details={"execution_id": execution.id}, session=session)`（在 `session.flush()` 之后取到 `execution.id`）。

- [ ] **Step 6: 跑测试**

Run: `python -m pytest tests/test_fix_plan_hardening_api.py tests/test_web_schemas.py tests/test_fix_plan_consolidation.py tests/test_resource_detail_api.py -q`
Expected: PASS。`tests/test_web_schemas.py` 若断言 `FixPlanUpdate(status="approved")` 合法——改为断言 `extra="forbid"` 拒绝 `approved_by`（与新契约一致）。

- [ ] **Step 7: 全量回归 + Commit**

```bash
python -m pytest tests/ -q --deselect tests/test_web_tools.py > /tmp/pytest-t8.log 2>&1; tail -5 /tmp/pytest-t8.log
git add src/agenticops/web/deps.py src/agenticops/web/schemas.py src/agenticops/web/app.py tests/test_fix_plan_hardening_api.py tests/test_web_schemas.py
git commit -m "feat(web): identity-bound plan approval, reject endpoint with reason, audit rows, kind filter"
```

---

### Task 9: Agent 工具 / 自动审批 / CLI 的审批与执行 → authz + 审计 + 身份

**Files:**
- Modify: `src/agenticops/tools/metadata_tools.py`（`approve_fix_plan` :1019-1091）
- Modify: `src/agenticops/services/pipeline_service.py`（`trigger_auto_approve` 审批块 :146-165）
- Modify: `src/agenticops/cli/main.py`（`_slash_approve` :2261-2314、`_slash_execute` :2317-2370）
- Test: `tests/test_plan_approval_audit.py`

**Interfaces:**
- Consumes: `authz.check`, `Actor`, `parse_actor`, `agent_actor`, `cli_actor`, `get_run_context`, `AuditService.log(session=...)`。
- Produces: 行为契约——`approve_fix_plan(fix_plan_id, approved_by)`：真实 actor = Run Context 的 actor（不是 `system` 时）否则 `parse_actor(approved_by)`；agent 对 L2/L3 → `pending_approval` + `authz.denied` 审计（规则 always 生效）；成功 → `plan.approved` 审计。自动审批 → 审计 `plan.approved` actor `agent:auto-pipeline` + `details.policy_rule`。CLI `/approve [id] [理由...]` 不再询问名字；`/execute` 的 `executed_by` = `cli:<user>`。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_plan_approval_audit.py
from unittest.mock import patch

import pytest

from agenticops.models import Base, FixPlan, HealthIssue, RCAResult, get_session
from agenticops.run_context import run_context


@pytest.fixture
def db(tmp_path):
    import agenticops.models as models_mod
    import agenticops.audit.models  # noqa: F401
    from agenticops.config import settings
    models_mod._engine = None
    settings.database_url = f"sqlite:///{tmp_path}/approval.db"
    Base.metadata.create_all(models_mod.get_engine())
    s = get_session()
    yield s
    s.close()
    models_mod._engine = None


def _plan(db, status="draft", risk="L1"):
    issue = HealthIssue(title="t", description="d", severity="low", source="test", status="fix_planned", resource_id="r")
    db.add(issue); db.flush()
    rca = RCAResult(health_issue_id=issue.id, root_cause="x", confidence=0.9)
    db.add(rca); db.flush()
    plan = FixPlan(health_issue_id=issue.id, rca_result_id=rca.id, risk_level=risk, title="p", summary="s", status=status)
    db.add(plan); db.commit()
    return plan


def _audits(db, action):
    from agenticops.audit.models import AuditLog
    return db.query(AuditLog).filter_by(action=action).all()


def test_tool_approve_uses_run_context_actor(db):
    from agenticops.tools.metadata_tools import approve_fix_plan
    plan = _plan(db)
    with run_context(actor="user:alice", actor_user_id=3), \
         patch("agenticops.services.pipeline_service.trigger_auto_execute"), \
         patch("agenticops.services.notification_service.notify_fix_approved"):
        out = approve_fix_plan(fix_plan_id=plan.id, approved_by="Some Name")
    assert "approved by user:alice" in out
    db.refresh(plan)
    assert plan.approved_by == "user:alice"
    rows = _audits(db, "plan.approved")
    assert len(rows) == 1 and rows[0].actor == "user:alice" and rows[0].details["claimed_name"] == "Some Name"


def test_tool_approve_without_context_parses_string(db):
    from agenticops.tools.metadata_tools import approve_fix_plan
    plan = _plan(db)
    with patch("agenticops.services.pipeline_service.trigger_auto_execute"), \
         patch("agenticops.services.notification_service.notify_fix_approved"):
        approve_fix_plan(fix_plan_id=plan.id, approved_by="operator:admin")
    db.refresh(plan)
    assert plan.approved_by == "operator:admin"


def test_agent_cannot_approve_l2_even_in_shadow_mode(db):
    from agenticops.config import settings
    from agenticops.tools.metadata_tools import approve_fix_plan
    plan = _plan(db, risk="L2")
    with patch.object(settings, "rbac_enforce", False):
        out = approve_fix_plan(fix_plan_id=plan.id, approved_by="agent:sre_agent")
    assert "requires human approval" in out
    db.refresh(plan)
    assert plan.status == "pending_approval" and plan.approved_by is None
    assert len(_audits(db, "authz.denied")) == 1


def test_auto_approve_writes_audit_with_rule(db):
    from agenticops.config import settings
    from agenticops.services.pipeline_service import trigger_auto_approve
    plan = _plan(db)
    with patch.object(settings, "auto_fix_enabled", True), patch.object(settings, "executor_auto_approve_l0_l1", True), \
         patch.object(settings, "policy_engine_enabled", True), \
         patch("agenticops.services.pipeline_service.trigger_auto_execute"):
        trigger_auto_approve(plan.id)
    db.refresh(plan)
    assert plan.status == "approved" and plan.approved_by == "agent:auto-pipeline"
    rows = _audits(db, "plan.approved")
    assert len(rows) == 1 and rows[0].actor == "agent:auto-pipeline"
    assert rows[0].details["policy_rule"] == "auto-approve-low-risk"


def test_cli_approve_binds_cli_actor(db):
    from agenticops.cli.main import _slash_approve
    plan = _plan(db)
    with patch("getpass.getuser", return_value="malibo"), \
         patch("agenticops.cli.main.init_db"), \
         patch("agenticops.services.pipeline_service.trigger_auto_execute"):
        out = _slash_approve(None, [str(plan.id), "looks", "good"])
    assert "approved by cli:malibo" in out
    db.refresh(plan)
    assert plan.approved_by == "cli:malibo"
    rows = _audits(db, "plan.approved")
    assert rows[0].details["reason"] == "looks good"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_plan_approval_audit.py -q`
Expected: FAIL（approved_by 写的是字符串、无审计行、CLI 会 `Prompt.ask`）

- [ ] **Step 3: `metadata_tools.approve_fix_plan`**

替换函数体（保留 docstring，追加一句 "The real approver is the Run Context actor; approved_by is a claimed name when a context exists."）：

```python
    from agenticops.audit.service import Actions, AuditService, EntityTypes
    from agenticops.auth import authz
    from agenticops.auth.actor import Actor, parse_actor
    from agenticops.run_context import get_run_context

    ctx = get_run_context()
    if ctx.actor != "system":
        base = parse_actor(ctx.actor)
        actor = Actor(base.kind, base.id, ctx.actor_user_id, base.permissions)
        claimed = approved_by if approved_by and approved_by != actor.key else None
    else:
        actor = parse_actor(approved_by)
        claimed = None

    session = get_session()
    try:
        plan = session.query(FixPlan).filter_by(id=fix_plan_id).first()
        if not plan:
            return f"FixPlan #{fix_plan_id} not found."
        if plan.status == "approved":
            return f"FixPlan #{fix_plan_id} is already approved."
        if plan.status == "rejected":
            return f"FixPlan #{fix_plan_id} was rejected. Create a new plan instead."

        try:
            authz.check(actor, "plan.approve", subject=plan)
        except authz.AuthzDenied as e:
            # Agent on L2/L3 (always-enforced rule) or an enforced RBAC denial:
            # park the plan for a human instead of approving.
            try:
                transition_plan(plan, "pending_approval")
                session.commit()
            except InvalidStatusTransition:
                session.rollback()
            return (
                f"FixPlan #{fix_plan_id} (risk {plan.risk_level}) requires human approval: {e.reason}. "
                f"Status set to 'pending_approval'. A human operator must approve it."
            )

        old = plan.status
        try:
            transition_plan(plan, "approved")
        except InvalidStatusTransition as e:
            return str(e)
        plan.approved_by = actor.key
        plan.approved_at = datetime.now(timezone.utc)

        issue = session.query(HealthIssue).filter_by(id=plan.health_issue_id).first() if plan.health_issue_id else None
        if issue:
            issue.status = "fix_approved"

        details = {"risk_level": plan.risk_level, "plan_kind": plan.plan_kind, "via": "agent_tool"}
        if claimed:
            details["claimed_name"] = claimed
        AuditService.log(Actions.PLAN_APPROVED, EntityTypes.FIX_PLAN, str(plan.id), actor=actor.key,
                         user_id=actor.user_id, details=details,
                         old_values={"status": old}, new_values={"status": "approved"}, session=session)
        session.commit()

        try:
            from agenticops.services.pipeline_service import trigger_auto_execute
            trigger_auto_execute(fix_plan_id, trace_id=issue.trace_id if issue else None)
        except Exception as e:
            logger.warning("Failed to trigger auto-execute: %s", e)
        try:
            from agenticops.services.notification_service import notify_fix_approved
            notify_fix_approved(fix_plan_id, actor.key, plan.risk_level)
        except Exception:
            logger.debug("Notification trigger failed", exc_info=True)

        return (
            f"FixPlan #{fix_plan_id} approved by {actor.key}. "
            f"Risk: {plan.risk_level}. HealthIssue status updated to 'fix_approved'."
        )
    except Exception as e:
        session.rollback()
        return f"Error approving fix plan: {e}"
    finally:
        session.close()
```

现有 `tests/test_sre_agent.py::…approve_fix_plan(approved_by="agent:sre_agent")` 对 L2 的断言仍成立（pending_approval）。

- [ ] **Step 4: `pipeline_service.trigger_auto_approve`**

在 `plan.approved_at = datetime.now(timezone.utc)` 之后、`risk_level = plan.risk_level` 之前加：

```python
            from agenticops.audit.service import Actions, AuditService, EntityTypes
            AuditService.log(
                Actions.PLAN_APPROVED, EntityTypes.FIX_PLAN, str(plan.id), actor="agent:auto-pipeline",
                details={"risk_level": plan.risk_level, "plan_kind": plan.plan_kind,
                         "policy_rule": decision.rule_name if decision else "legacy-l0-l1",
                         "policy_action": decision.action if decision else "auto_approve"},
                old_values={"status": "draft"}, new_values={"status": "approved"}, session=session,
            )
```

（`plan.status = "approved"` 已在 Task 4 改为 `transition_plan`。）

- [ ] **Step 5: CLI `/approve` `/execute`**

`_slash_approve(ctx, args)`：删掉 `approver = Prompt.ask(...)` 与相关校验，改为：

```python
    reason = " ".join(args[1:]).strip()
    from agenticops.auth import authz
    from agenticops.auth.actor import cli_actor
    from agenticops.audit.service import Actions, AuditService, EntityTypes
    from agenticops.models import InvalidStatusTransition, transition_plan
    actor = cli_actor()
    ...
        try:
            authz.check(actor, "plan.approve", subject=plan)
        except authz.AuthzDenied as e:
            return f"[red]{e}[/red]"
        old = plan.status
        try:
            transition_plan(plan, "approved")
        except InvalidStatusTransition as e:
            return f"[red]{e}[/red]"
        plan.approved_by = actor.key
        plan.approved_at = datetime.now(timezone.utc)
        issue = session.query(HealthIssue).filter_by(id=plan.health_issue_id).first() if plan.health_issue_id else None
        if issue:
            issue.status = "fix_approved"
        AuditService.log(Actions.PLAN_APPROVED, EntityTypes.FIX_PLAN, str(plan.id), actor=actor.key,
                         details={"reason": reason or None, "risk_level": plan.risk_level, "via": "cli"},
                         old_values={"status": old}, new_values={"status": "approved"}, session=session)
        session.commit()
        try:
            from agenticops.services.pipeline_service import trigger_auto_execute
            trigger_auto_execute(plan.id)
        except Exception:
            pass
        return f"[green]Fix plan #{plan_id} approved by {actor.key}.[/green]"
```

用法文案改 `Usage: /approve <plan_id> [reason...]`。L2/L3 的 `Confirm.ask` 保留。`_slash_execute`：`executed_by="cli_user"` → `executed_by=cli_actor().key`，并加 `authz.check(actor, "plan.execute", subject=plan)`（403 → 红字）与 `AuditService.log(Actions.PLAN_EXECUTE_REQUESTED, ..., session=session)`。

- [ ] **Step 6: 跑测试 + 回归 + Commit**

```bash
python -m pytest tests/test_plan_approval_audit.py tests/test_sre_agent.py tests/test_auto_fix_pipeline.py tests/test_pipeline_service.py -q
python -m pytest tests/ -q --deselect tests/test_web_tools.py > /tmp/pytest-t9.log 2>&1; tail -5 /tmp/pytest-t9.log
git add src/agenticops/tools/metadata_tools.py src/agenticops/services/pipeline_service.py src/agenticops/cli/main.py tests/test_plan_approval_audit.py
git commit -m "feat(approval): agent/auto/CLI approvals go through authz + audit, approver bound to actor"
```

`tests/test_pipeline_service.py::…approved_by == "agent:auto-pipeline"` 用 MagicMock plan：`AuditService.log(session=mock_session)` 会 `session.add/flush` 一个 MagicMock——无害；若该测试用了 `autospec` 导致 `plan.plan_kind` 缺失，给 mock 补 `plan_kind="fix"`。

---

### Task 10: 命令账本 `command_audit.record_command` + `policies.yaml change_required` + 三个执行工具接入

**Files:**
- Create: `src/agenticops/services/command_audit.py`
- Modify: `src/agenticops/services/policy_engine.py`（`PolicyEngine.__init__` :83-92、新增 `change_required_match`、`validate_policy` :263-280）
- Modify: `config/policies.yaml`（文件末尾追加 `change_required:` 段）
- Modify: `src/agenticops/tools/aws_cli_tool.py`（`run_aws_cli` :253-313、`_execute_aws_cli` :192-250）
- Modify: `src/agenticops/skills/execution.py`（`run_on_host` :96-166、`run_kubectl` :384-437）
- Modify: `src/agenticops/skills/tools.py`（`run_skill_script` :404-460）
- Modify: `src/agenticops/config.py`（`command_audit_enabled`）、`config/settings.yaml`、`CLAUDE.md`
- Test: `tests/test_command_audit.py`

**Interfaces:**
- Produces: `record_command(*, tool, tier, command, outcome, account="", region="", target="", exit_code=None, output_excerpt="", duration_ms=0, reason="") -> None`（fail-soft；读 Run Context 填 actor/agent/plan/CR/trace；命令与摘要经 `redact_secrets`；摘要截 2000 字符；`settings.command_audit_enabled=false` 直接返回；顺带 `AuditService.maybe_prune_daily()`）；`approved_plan_in_context() -> Optional[int]`（Run Context 的 `fix_plan_id` 对应计划 status ∈ {approved, executing} 时返回 id）；`PolicyEngine.change_required_match(command: str) -> Optional[str]`；`config/policies.yaml` 新段 `change_required: [<prefix>, ...]`（大小写不敏感的子串匹配，与 `_classify_command` 同风格）。
- 行为契约：`run_aws_cli` / `run_on_host` / `run_kubectl` 的 write|unknown|blocked 三档都记账（含被拒绝的尝试，`outcome=refused reason=confirmation|change_required`，`outcome=blocked`）；**readonly 不记**；命中 `change_required` 且 `approved_plan_in_context()` 为 None → 拒绝并提示 `/change`；`run_skill_script` 每次记账（tier `script`）。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_command_audit.py
"""Tool-layer command ledger + change_required refusal (MVP-2.6.0 S1)."""
from unittest.mock import patch

import pytest

from agenticops.models import Base, CommandAudit, FixPlan, HealthIssue, RCAResult, get_session
from agenticops.run_context import run_context


@pytest.fixture
def db(tmp_path):
    import agenticops.models as models_mod
    import agenticops.audit.models  # noqa: F401
    from agenticops.config import settings
    models_mod._engine = None
    settings.database_url = f"sqlite:///{tmp_path}/cmd.db"
    Base.metadata.create_all(models_mod.get_engine())
    s = get_session()
    yield s
    s.close()
    models_mod._engine = None


def _rows(db):
    db.expire_all()
    return db.query(CommandAudit).order_by(CommandAudit.id).all()


class TestRecordCommand:
    def test_writes_row_with_run_context(self, db):
        from agenticops.services.command_audit import record_command
        with run_context(actor="cli:malibo", trace_id="TRC-aa", fix_plan_id=4, change_request_id=2, agent_name="executor"):
            record_command(tool="run_aws_cli", tier="write", command="aws ec2 create-tags --resources i-1",
                           outcome="executed", account="dev", region="ap-southeast-1", exit_code=0,
                           output_excerpt="{}", duration_ms=120)
        (row,) = _rows(db)
        assert (row.actor, row.trace_id, row.fix_plan_id, row.change_request_id, row.agent_name) == \
               ("cli:malibo", "TRC-aa", 4, 2, "executor")
        assert row.outcome == "executed" and row.exit_code == 0 and row.account == "dev"

    def test_redacts_secrets_and_caps_excerpt(self, db):
        from agenticops.services.command_audit import record_command
        # AWS's documented EXAMPLE access key id (never a real credential) — redact_secrets masks the AKIA… pattern
        record_command(tool="run_on_host", tier="write", command="aws configure set aws_access_key_id AKIAIOSFODNN7EXAMPLE",
                       outcome="executed", output_excerpt="x" * 5000)
        (row,) = _rows(db)
        assert "AKIAIOSFODNN7EXAMPLE" not in row.command
        assert len(row.output_excerpt) <= 2000

    def test_disabled_writes_nothing(self, db):
        from agenticops.config import settings
        from agenticops.services.command_audit import record_command
        with patch.object(settings, "command_audit_enabled", False):
            record_command(tool="run_aws_cli", tier="write", command="aws ec2 create-tags", outcome="executed")
        assert _rows(db) == []

    def test_fail_soft_when_db_broken(self, db):
        from agenticops.services import command_audit
        with patch.object(command_audit, "get_db_session", side_effect=RuntimeError("db down")):
            command_audit.record_command(tool="run_aws_cli", tier="write", command="aws x", outcome="executed")  # no raise


class TestChangeRequiredMatch:
    def test_default_policy_file_has_change_required(self):
        from agenticops.services.policy_engine import get_policy_engine
        eng = get_policy_engine(reload=True)
        assert eng.change_required_match("aws ec2 modify-security-group-rules --group-id sg-1") is not None
        assert eng.change_required_match("aws rds modify-db-instance --x") is not None
        assert eng.change_required_match("aws ec2 create-tags --resources i-1") is None
        assert eng.change_required_match("kubectl scale deployment/x --replicas=2") is None

    def test_validate_rejects_non_list(self):
        from agenticops.services.policy_engine import validate_policy
        assert validate_policy({"rules": [], "change_required": "aws rds modify-"})


def _approved_plan(db) -> int:
    issue = HealthIssue(title="t", description="d", severity="low", source="test", status="fix_approved", resource_id="r")
    db.add(issue); db.flush()
    rca = RCAResult(health_issue_id=issue.id, root_cause="x", confidence=0.9)
    db.add(rca); db.flush()
    plan = FixPlan(health_issue_id=issue.id, rca_result_id=rca.id, risk_level="L2", title="p", summary="s", status="approved")
    db.add(plan); db.commit()
    return plan.id


class TestRunAwsCliLedger:
    def test_write_without_confirmation_is_recorded_as_refused(self, db):
        from agenticops.tools.aws_cli_tool import run_aws_cli
        out = run_aws_cli(command="aws ec2 create-tags --resources i-1 --tags Key=a,Value=b")
        assert "requires confirmation" in out
        (row,) = _rows(db)
        assert (row.outcome, row.reason, row.tier) == ("refused", "confirmation", "write")

    def test_blocked_is_recorded(self, db):
        from agenticops.tools.aws_cli_tool import run_aws_cli
        run_aws_cli(command="aws ec2 terminate-instances --instance-ids i-1", require_confirmation=True)
        (row,) = _rows(db)
        assert row.outcome == "blocked"

    def test_readonly_is_not_recorded(self, db):
        from agenticops.tools.aws_cli_tool import run_aws_cli
        with patch("agenticops.tools.aws_cli_tool._execute_aws_cli", return_value="{}"):
            run_aws_cli(command="aws ec2 describe-instances")
        assert _rows(db) == []

    def test_change_required_refused_outside_approved_plan(self, db):
        from agenticops.tools.aws_cli_tool import run_aws_cli
        out = run_aws_cli(command="aws ec2 modify-security-group-rules --group-id sg-1", require_confirmation=True)
        assert "/change" in out and "change request" in out.lower()
        (row,) = _rows(db)
        assert (row.outcome, row.reason) == ("refused", "change_required")

    def test_change_required_allowed_inside_approved_plan(self, db):
        from agenticops.tools.aws_cli_tool import run_aws_cli
        pid = _approved_plan(db)
        with run_context(actor="agent:executor", fix_plan_id=pid), \
             patch("agenticops.tools.aws_cli_tool._execute_aws_cli", return_value="ok") as ex:
            out = run_aws_cli(command="aws ec2 modify-security-group-rules --group-id sg-1", require_confirmation=True)
        assert out == "ok" and ex.called
        (row,) = _rows(db)
        assert (row.outcome, row.fix_plan_id) == ("executed", pid)

    def test_executed_write_records_exit_code(self, db):
        from agenticops.tools.aws_cli_tool import run_aws_cli
        with patch("agenticops.tools.aws_cli_tool._execute_aws_cli", return_value="Error (exit code 254): boom"):
            run_aws_cli(command="aws ec2 create-tags --resources i-1 --tags Key=a,Value=b", require_confirmation=True)
        (row,) = _rows(db)
        assert row.outcome == "error" and row.exit_code == 254


class TestRunOnHostLedger:
    def test_write_refused_is_recorded(self, db):
        from agenticops.skills.execution import run_on_host
        out = run_on_host(host_id="i-1", command="systemctl restart nginx")
        assert "requires confirmation" in out
        (row,) = _rows(db)
        assert (row.tool, row.outcome, row.target) == ("run_on_host", "refused", "i-1")

    def test_change_required_shell_command_refused(self, db):
        from agenticops.skills.execution import run_on_host
        out = run_on_host(host_id="i-1", command="systemctl restart nginx", require_confirmation=True)
        assert "/change" in out
        (row,) = _rows(db)
        assert row.reason == "change_required"

    def test_readonly_not_recorded(self, db):
        from agenticops.skills.execution import run_on_host
        with patch("agenticops.skills.execution._run_auto_ladder", return_value="ok"):
            run_on_host(host_id="i-1", command="df -h")
        assert _rows(db) == []
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_command_audit.py -q`
Expected: FAIL — `ModuleNotFoundError: agenticops.services.command_audit`

- [ ] **Step 3: 配置项与 policies.yaml**

`config.py`（audit 块之后）：

```python
    command_audit_enabled: bool = Field(
        default=True,
        description="Record every write/unknown/blocked command attempt from run_aws_cli / run_on_host / "
        "run_kubectl / run_skill_script into command_audits (AIOPS_COMMAND_AUDIT_ENABLED)",
    )
```
`settings.yaml`：`command_audit_enabled: true`。CLAUDE.md：`| command_audit_enabled | true | Tool-layer ledger of write-tier command attempts (command_audits); read-only commands are not recorded |`。

`config/policies.yaml` 末尾追加：

```yaml

# ── Change Management (MVP-2.6.0) ────────────────────────────────────────
# Write commands matching any of these (case-insensitive substring) are REFUSED
# outside an approved plan (fix or change) and the agent is told to open a change
# request (/change). Deliberately conservative — L1-class writes such as tagging
# or a single-workload `kubectl scale` are NOT here (the SRE risk rubric says L1).
# Tune here, not in code.
change_required:
  - aws ec2 modify-security-group
  - aws ec2 revoke-
  - aws ec2 authorize-
  - aws rds modify-
  - aws rds reboot-
  - aws autoscaling update-
  - aws autoscaling set-
  - aws lambda update-
  - aws eks update-
  - kubectl delete
  - kubectl drain
  - systemctl stop
  - systemctl restart
  - reboot
  - shutdown
```

- [ ] **Step 4: `policy_engine.py`**

`__init__` 末尾加：

```python
        raw = self.policy.get("change_required") or []
        self.change_required: list[str] = [str(p).lower() for p in raw if str(p).strip()]
```

新方法（`_active_freeze_window` 之后）：

```python
    def change_required_match(self, command: str) -> Optional[str]:
        """Return the change_required pattern the command matches, or None."""
        cmd = (command or "").lower()
        for pattern in self.change_required:
            if pattern in cmd:
                return pattern
        return None
```

`validate_policy` 末尾加：

```python
    cr = data.get("change_required")
    if cr is not None and not isinstance(cr, list):
        errors.append("'change_required' must be a list of strings")
```

`DEFAULT_POLICY` 不加 `change_required`（默认策略 = 历史行为，不拒绝任何命令）。

- [ ] **Step 5: `services/command_audit.py`**

```python
"""Command audit — tool-layer ledger of write-tier command attempts (MVP-2.6.0).

record_command() is called by run_aws_cli / run_on_host / run_kubectl / run_skill_script for
every write|unknown|blocked attempt (executed, refused, blocked, error). It reads the Run Context
for attribution and is FAIL-SOFT: any failure is logged at debug level and never changes the
tool's return value. Read-only commands are deliberately not recorded (volume).
"""

from __future__ import annotations

import logging
from typing import Optional

from agenticops.models import get_db_session

logger = logging.getLogger(__name__)

EXCERPT_LIMIT = 2000
VALID_OUTCOMES = {"executed", "refused", "blocked", "error"}


def record_command(
    *,
    tool: str,
    tier: str,
    command: str,
    outcome: str,
    account: str = "",
    region: str = "",
    target: str = "",
    exit_code: Optional[int] = None,
    output_excerpt: str = "",
    duration_ms: int = 0,
    reason: str = "",
) -> None:
    try:
        from agenticops.config import settings
        if not getattr(settings, "command_audit_enabled", True):
            return
        if outcome not in VALID_OUTCOMES:
            outcome = "error"
        from agenticops.models import CommandAudit
        from agenticops.run_context import get_run_context
        from agenticops.security import redact_secrets

        ctx = get_run_context()
        row = CommandAudit(
            actor=ctx.actor, actor_user_id=ctx.actor_user_id, on_behalf_of=ctx.on_behalf_of,
            agent_name=ctx.agent_name, tool=tool, tier=tier, account=account or "", region=region or "",
            target=(target or "")[:200], command=redact_secrets(command or "")[:10000], outcome=outcome,
            reason=(reason or None), exit_code=exit_code,
            output_excerpt=redact_secrets(output_excerpt or "")[:EXCERPT_LIMIT], duration_ms=int(duration_ms or 0),
            trace_id=ctx.trace_id, fix_plan_id=ctx.fix_plan_id, change_request_id=ctx.change_request_id,
        )
        with get_db_session() as db:
            db.add(row)
        try:
            from agenticops.audit.service import AuditService
            AuditService.maybe_prune_daily()
        except Exception:
            pass
    except Exception:
        logger.debug("command audit write failed (tool=%s outcome=%s)", tool, outcome, exc_info=True)


def approved_plan_in_context() -> Optional[int]:
    """The Run Context's plan id when that plan is approved/executing, else None."""
    try:
        from agenticops.models import FixPlan
        from agenticops.run_context import get_run_context
        pid = get_run_context().fix_plan_id
        if not pid:
            return None
        with get_db_session() as db:
            status = db.query(FixPlan.status).filter_by(id=pid).scalar()
        return pid if status in ("approved", "executing") else None
    except Exception:
        return None


def change_required_refusal(command: str, pattern: str) -> str:
    return (
        f"This command matches the high-risk pattern '{pattern}' (config/policies.yaml change_required) and "
        f"can only run inside an approved plan. Open a change request instead: in Chat type "
        f"/change <what you want changed>, or use the Web UI Plans & Changes → New change request. "
        f"Command: {command}"
    )
```

- [ ] **Step 6: `aws_cli_tool.run_aws_cli`**

把第 3 步及执行改为（其余不变）：

```python
    # 3. Classify and enforce security tier — write-tier attempts are ledgered (command_audits)
    tier = _classify_command(command)
    from agenticops.services.command_audit import approved_plan_in_context, change_required_refusal, record_command

    if tier == "blocked":
        record_command(tool="run_aws_cli", tier=tier, command=command, outcome="blocked", account=account)
        return (...原文案...)

    if tier in ("write", "unknown") and not require_confirmation:
        record_command(tool="run_aws_cli", tier=tier, command=command, outcome="refused", reason="confirmation", account=account)
        return (...原文案...)

    if tier in ("write", "unknown"):
        from agenticops.services.policy_engine import get_policy_engine
        pattern = get_policy_engine().change_required_match(command)
        if pattern and approved_plan_in_context() is None:
            record_command(tool="run_aws_cli", tier=tier, command=command, outcome="refused",
                           reason="change_required", account=account)
            return change_required_refusal(command, pattern)

    # 4. Execute
    if tier in ("write", "unknown"):
        import time as _time
        t0 = _time.monotonic()
        result = _execute_aws_cli(command, account)
        exit_code, outcome = _parse_exit(result)
        record_command(tool="run_aws_cli", tier=tier, command=command, outcome=outcome, account=account,
                       exit_code=exit_code, output_excerpt=result, duration_ms=int((_time.monotonic() - t0) * 1000))
        return result
    return _execute_aws_cli(command, account)
```

模块级辅助：

```python
_EXIT_RE = re.compile(r"^Error \(exit code (\d+)\)")


def _parse_exit(result: str) -> tuple[Optional[int], str]:
    """Map _execute_aws_cli's text result to (exit_code, outcome)."""
    m = _EXIT_RE.match(result or "")
    if m:
        return int(m.group(1)), "error"
    if (result or "").startswith("Error:"):
        return None, "error"
    return 0, "executed"
```

（顶部 `import re` 与 `from typing import Optional`。）

- [ ] **Step 7: `skills/execution.py` `run_on_host` / `run_kubectl`**

`run_on_host` 分级块改为：

```python
    tier = classify_shell_command(command)
    from agenticops.services.command_audit import approved_plan_in_context, change_required_refusal, record_command
    if tier == "blocked":
        record_command(tool="run_on_host", tier=tier, command=command, outcome="blocked", account=account, region=region, target=host_id)
        return (...原文案...)
    if tier in ("write", "unknown") and not require_confirmation:
        record_command(tool="run_on_host", tier=tier, command=command, outcome="refused", reason="confirmation",
                       account=account, region=region, target=host_id)
        return (...原文案...)
    if tier in ("write", "unknown"):
        from agenticops.services.policy_engine import get_policy_engine
        pattern = get_policy_engine().change_required_match(command)
        if pattern and approved_plan_in_context() is None:
            record_command(tool="run_on_host", tier=tier, command=command, outcome="refused", reason="change_required",
                           account=account, region=region, target=host_id)
            return change_required_refusal(command, pattern)
```

并把三条 `return _run_ssh_for_host(...)` / `return text` / `return _run_auto_ladder(...)` 收拢到一个 `result = ...` 后：

```python
    if tier in ("write", "unknown"):
        record_command(tool="run_on_host", tier=tier, command=command,
                       outcome="error" if result.startswith("Error") else "executed",
                       account=account, region=region, target=host_id, output_excerpt=result)
    return result
```

`run_kubectl` 同构（`tool="run_kubectl"`, `target=cluster_name`, 记账命令为 `f"kubectl -n {namespace} {command}"`，`change_required_match` 用同一字符串）。

- [ ] **Step 8: `skills/tools.py` `run_skill_script`**

在 `res = _sandbox.run_script(...)` 成功后加 `record_command(tool="run_skill_script", tier="script", command=f"{skill_name}/{script} {args}".strip(), outcome="executed" if res.exit_code == 0 else "error", exit_code=res.exit_code, target=skill_name, output_excerpt=(res.stdout or "")[:2000])`；两个 `except` 分支分别记 `outcome="refused", reason="sandbox"` 与 `outcome="error"`。（`SandboxResult` 字段名以 `skills/sandbox.py` 的 dataclass 为准——读它的定义再写。）

- [ ] **Step 9: 跑测试**

Run: `python -m pytest tests/test_command_audit.py tests/test_execution_tools.py tests/test_execution_skills.py tests/test_policy_engine_simulation.py -q`
Expected: PASS。`test_execution_tools.py` 里任何断言"write 未确认返回原文案"的用例不受影响（文案未变）。

- [ ] **Step 10: 全量回归 + Commit**

```bash
python -m pytest tests/ -q --deselect tests/test_web_tools.py > /tmp/pytest-t10.log 2>&1; tail -5 /tmp/pytest-t10.log
git add src/agenticops/services/command_audit.py src/agenticops/services/policy_engine.py config/policies.yaml src/agenticops/tools/aws_cli_tool.py src/agenticops/skills/execution.py src/agenticops/skills/tools.py src/agenticops/config.py config/settings.yaml CLAUDE.md tests/test_command_audit.py
git commit -m "feat(audit): tool-layer command ledger + change_required refusal outside approved plans"
```

---

### Task 11: 入口设置 Run Context（Chat SSE、CLI、IM、ExecutorService、pipeline 线程）

**Files:**
- Modify: `src/agenticops/web/app.py`（chat 处理器 `_generate` :3838-3846）
- Modify: `src/agenticops/cli/main.py`（headless :3818-3820；REPL :4246-4247）
- Modify: `src/agenticops/im/feishu_ws.py:290-296`、`src/agenticops/im/slack_ws.py:294-300`
- Modify: `src/agenticops/services/executor_service.py`（`_run_executor` :156-172）
- Modify: `src/agenticops/services/pipeline_service.py`（`_run_auto_sre` :77-89、`_run_auto_execute` :281-323）
- Test: `tests/test_run_context_entrypoints.py`

**Interfaces:**
- Consumes: `set_run_context`, `RunContext`, `update_run_context`, `actor_from_request`, `cli_actor`, `im_actor`, `agent_actor`。
- 契约：每个入口在设置 trace_id 的**同一处**设置 Run Context；线程入口显式 set（不依赖继承）。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_run_context_entrypoints.py
from unittest.mock import patch

import pytest

from agenticops.models import Base, FixExecution, FixPlan, HealthIssue, RCAResult, get_session


@pytest.fixture
def db(tmp_path):
    import agenticops.models as models_mod
    from agenticops.config import settings
    models_mod._engine = None
    settings.database_url = f"sqlite:///{tmp_path}/rc.db"
    Base.metadata.create_all(models_mod.get_engine())
    s = get_session()
    yield s
    s.close()
    models_mod._engine = None


def _approved_plan(db):
    issue = HealthIssue(title="t", description="d", severity="low", source="test", status="fix_approved",
                        resource_id="r", trace_id="TRC-issue1")
    db.add(issue); db.flush()
    rca = RCAResult(health_issue_id=issue.id, root_cause="x", confidence=0.9)
    db.add(rca); db.flush()
    plan = FixPlan(health_issue_id=issue.id, rca_result_id=rca.id, risk_level="L1", title="p", summary="s",
                   status="executing", approved_by="user:alice")
    db.add(plan); db.flush()
    ex = FixExecution(fix_plan_id=plan.id, health_issue_id=issue.id, status="running", executed_by="user:alice")
    db.add(ex); db.commit()
    return plan, ex


def test_executor_service_worker_sets_context(db):
    from agenticops.run_context import get_run_context
    from agenticops.services.executor_service import ExecutorService
    plan, ex = _approved_plan(db)
    seen = {}

    def fake_executor(fix_plan_id):
        seen.update(get_run_context().__dict__)
        return "done"

    with patch("agenticops.agents.executor_agent.executor_agent", side_effect=fake_executor):
        ExecutorService()._run_executor(ex.id, plan.id)
    assert seen["actor"] == "agent:executor" and seen["on_behalf_of"] == "user:alice"
    assert seen["fix_plan_id"] == plan.id and seen["trace_id"] == "TRC-issue1" and seen["agent_name"] == "executor"


def test_pipeline_auto_execute_thread_sets_context(db):
    from agenticops.run_context import get_run_context
    from agenticops.services import pipeline_service
    plan, _ = _approved_plan(db)
    seen = {}

    def fake_executor(fix_plan_id):
        seen.update(get_run_context().__dict__)
        return "done"

    with patch("agenticops.agents.executor_agent.executor_agent", side_effect=fake_executor):
        pipeline_service._run_auto_execute(plan.id, trace_id="TRC-x")
    assert seen["actor"] == "agent:auto-pipeline" and seen["fix_plan_id"] == plan.id and seen["trace_id"] == "TRC-x"


def test_pipeline_auto_sre_thread_sets_context(db):
    from agenticops.run_context import get_run_context
    from agenticops.services import pipeline_service
    seen = {}
    with patch("agenticops.agents.sre_agent.sre_agent", side_effect=lambda issue_id: seen.update(get_run_context().__dict__) or "ok"):
        pipeline_service._run_auto_sre(1, trace_id="TRC-y")
    assert seen["actor"] == "agent:auto-pipeline" and seen["agent_name"] == "sre"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_run_context_entrypoints.py -q`
Expected: FAIL — `seen["actor"] == "system"`

- [ ] **Step 3: ExecutorService `_run_executor`**

```python
    def _run_executor(self, execution_id: int, fix_plan_id: int):
        """Invoke executor_agent for a specific fix plan (worker thread — sets its own Run Context)."""
        from agenticops.run_context import RunContext, set_run_context
        from agenticops.config import set_trace_id
        try:
            from agenticops.models import FixPlan, HealthIssue, get_db_session
            approved_by = trace_id = None
            change_request_id = None
            with get_db_session() as db:
                plan = db.query(FixPlan).filter_by(id=fix_plan_id).first()
                if plan:
                    approved_by = plan.approved_by
                    change_request_id = plan.change_request_id
                    if plan.health_issue_id:
                        trace_id = db.query(HealthIssue.trace_id).filter_by(id=plan.health_issue_id).scalar()
                    elif plan.change_request:
                        trace_id = plan.change_request.trace_id
            if trace_id:
                set_trace_id(trace_id)
            set_run_context(RunContext(actor="agent:executor", on_behalf_of=approved_by, trace_id=trace_id,
                                       agent_name="executor", fix_plan_id=fix_plan_id,
                                       change_request_id=change_request_id))
        except Exception:
            logger.debug("executor run-context setup failed", exc_info=True)
        try:
            from agenticops.agents.executor_agent import executor_agent
            ...（原体不变）
```

- [ ] **Step 4: pipeline 线程**

`_run_auto_sre` 开头（`_restore_trace_id` 之后）：

```python
    from agenticops.run_context import RunContext, set_run_context
    from agenticops.config import get_trace_id
    set_run_context(RunContext(actor="agent:auto-pipeline", trace_id=get_trace_id(), agent_name="sre"))
```

`_run_auto_execute` 在查到 `_issue_id` 之后：

```python
    from agenticops.run_context import RunContext, set_run_context
    from agenticops.config import get_trace_id
    set_run_context(RunContext(actor="agent:auto-pipeline", trace_id=trace_id or get_trace_id(),
                               agent_name="executor", fix_plan_id=fix_plan_id))
```

- [ ] **Step 5: Web chat、CLI、IM**

`app.py` `_generate` 里 `set_trace_id(_chat_trace_id)` 之后：

```python
        from agenticops.auth.actor import actor_from_request
        from agenticops.run_context import RunContext, set_run_context
        _actor = actor_from_request(request)
        set_run_context(RunContext(actor=_actor.key, actor_user_id=_actor.user_id, trace_id=_chat_trace_id,
                                   agent_name="main", chat_session_id=session_id))
```

`cli/main.py` headless（`set_trace_id(generate_trace_id())` 之后）与 REPL（`_set_tid(_gen_tid())` 之后）各加：

```python
    from agenticops.auth.actor import cli_actor as _cli_actor
    from agenticops.run_context import RunContext as _RC, set_run_context as _set_rc
    from agenticops.config import get_trace_id as _get_tid
    _set_rc(_RC(actor=_cli_actor().key, trace_id=_get_tid(), agent_name="main"))
```

`feishu_ws.py`（`_trace_token = set_trace_id(...)` 之后）：

```python
                from agenticops.auth.actor import im_actor
                from agenticops.run_context import RunContext, set_run_context
                _rc_token = set_run_context(RunContext(actor=im_actor("feishu", chat_id).key,
                                                       trace_id=get_trace_id(), agent_name="main"))
```
并在 `set_trace_id(None)` 之后 `reset_run_context(_rc_token)`（import `get_trace_id`、`reset_run_context`）。`slack_ws.py` 同构（platform `"slack"`）。P1 用 `chat_id` 作 IM 身份（spec §3.3），P3 换 open_id。

- [ ] **Step 6: 跑测试 + 回归 + Commit**

```bash
python -m pytest tests/test_run_context_entrypoints.py tests/test_executor_service.py tests/test_pipeline_service.py tests/test_chat_api.py -q
python -m pytest tests/ -q --deselect tests/test_web_tools.py > /tmp/pytest-t11.log 2>&1; tail -5 /tmp/pytest-t11.log
git add src/agenticops/web/app.py src/agenticops/cli/main.py src/agenticops/im/feishu_ws.py src/agenticops/im/slack_ws.py src/agenticops/services/executor_service.py src/agenticops/services/pipeline_service.py tests/test_run_context_entrypoints.py
git commit -m "feat(context): set RunContext at every entry point (chat, CLI, IM, executor worker, pipeline threads)"
```

---

### Task 12: Plan A 收尾 — 全量回归、迁移演练复核、提示词预算

- [ ] **Step 1: 全量测试**

Run: `python -m pytest tests/ -q > /tmp/pytest-planA.log 2>&1; tail -15 /tmp/pytest-planA.log`
Expected: 只有 `tests/test_web_tools.py` 的 DNS 假失败；其余全绿。把 passed/failed 数字记到 `docs/superpowers/plans/2026-09-17-change-management-p1-a-foundation.md` 末尾的「执行记录」小节（追加两行：日期、结果）。

- [ ] **Step 2: 提示词预算未变**

Run: `python -m pytest tests/test_prompt_budget.py -q`
Expected: PASS（Plan A 不改提示词）。

- [ ] **Step 3: 服务能启动并完成迁移**

```bash
cp $(python -c "from agenticops.config import settings; print(settings.database_url.replace('sqlite:///',''))") /tmp/planA-smoke.db
AIOPS_DATABASE_URL=sqlite:////tmp/planA-smoke.db timeout 20 uvicorn agenticops.web.app:app --port 8099 > /tmp/planA-uvicorn.log 2>&1 || true
grep -E "Rebuilt table|backup written|Application startup complete|Error|Traceback" /tmp/planA-uvicorn.log | head
```
Expected: 看到 `Rebuilt table fix_plans ...`（或已迁移则无）与 `Application startup complete`；无 Traceback。

- [ ] **Step 4: Commit（若第 1 步追加了执行记录）**

```bash
git add docs/superpowers/plans/2026-09-17-change-management-p1-a-foundation.md
git commit -m "docs(plan): Plan A execution record"
```

## 执行记录

（执行时追加：日期 · 全量测试结果 · 迁移演练结果）
