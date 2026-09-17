# Change Management P1 — Plan B: 后端变更闭环（S2 + S3 + 通知 + 统计）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Plan A 的地基上交付完整的后端变更闭环：`change_service`（状态机与事务的唯一所有者）、策略引擎扩展、SRE 变更审核模式（Mode C）、Main agent 变更意图路由、CLI 斜杠命令、`/api/changes/*` + `/api/plans/stats` + `/api/command-audits`、三个通知点，以及 mock-agent 的 pipeline 端到端测试。

**Architecture:** 一切写路径都进 `services/change_service.py`（authz → 校验器 → 同事务审计 → 事件 → 通知）；SRE 与 Main 只拿到薄的 `@tool` 包装（`tools/change_tools.py`）；Executor 一行不改，只在 `save_execution_result` 与 `executor_service` 的崩溃/超时路径上接一个确定性的终态映射器 `change_service.on_execution_result`；Web 层是纯路由 + Pydantic schema，错误由 `ChangeError` 子类映射为 400/404/409/422/403。

**Tech Stack:** Python 3.11, SQLAlchemy 2.x, FastAPI, Strands `@tool`, pytest（mock agents）。

**Spec:** `docs/superpowers/specs/2026-09-16-change-management-p1-design.md`（§3.1、§3.5-3.8、§3.10、§5、§6、§7）
**前置:** Plan A（`docs/superpowers/plans/2026-09-17-change-management-p1-a-foundation.md`）全部 Task 完成并提交。

## Global Constraints

- 与 Plan A 相同的运行/测试/提交/不 push 纪律（`.venv`、全量测试重定向到文件、每 Task 一 commit、只加本 Task 的文件、受保护文件不碰）。
- **Executor agent（提示词、工具列表、`get_approved_fix_plan`）不改**；唯一例外是 `executor_agent()` 里按账户解析 CLI 工具时兼容 change 计划（从 `ChangeRequest.account_id` 取账户）。
- 提示词只能加英文（`tests/test_prompt_budget.py::test_no_cjk_in_base_prompts`）；Main/SRE 基线金标 `BASE_PROMPT_GOLDENS` 在增量落地后**按实际值重设**（±25% 之外才需要），装配后总预算 20,000 字符不放宽。
- 云调用只经 provider 层：`attach_target` 的只读 describe 经 `agenticops.tools.aws_cli_tool._execute_aws_cli(command, account_name)`（账户寻址、fail-closed），不得裸用 boto3。
- 终态不变量：`ChangeRequest` 的 completed / failed / rolled_back / needs_review **只**由 `change_service.on_execution_result` 与 `resolve_review` 写；agent 工具里没有任何能写终态的路径。
- `change_management_enabled=false` 时：Main 不注入变更工具、`/api/changes/*` 返回 404、CLI 斜杠命令返回"未启用"提示；fix 流不受影响。

## 跨计划接口契约（Plan C 依赖；Plan A 提供的见其文档）

| 符号 | 位置 | 说明 |
|---|---|---|
| `ChangeError(status_code=400)`, `ChangeNotFound(404)`, `ChangeStateError(409)`, `ChangeValidationError(422)`, `ChangeForbidden(403)` | `agenticops.services.change_service` | 异常 → HTTP |
| `create_change_request(...) -> dict`, `start_review(cr_id, *, sync) -> Optional[str]`, `restart_review(cr_id, *, actor)`, `ground_targets(cr_id) -> dict`, `attach_target(cr_id, resource_id, resource_type, *, actor, region="") -> dict`, `evaluate_policy(cr_id, risk_level, action_type) -> PolicyDecision`, `submit_review(cr_id, *, verdict, risk_level, action_type, reasons, actor) -> dict`, `approve / reject / cancel / clarify / request_execution / resolve_review`, `on_execution_result(fix_plan_id, execution_status, *, post_check_results=None, error="")`, `get_change(cr_id) -> dict`, `list_changes(...) -> list[dict]`, `change_timeline(cr_id) -> list[dict]`, `active_plan_for(cr_id) -> Optional[FixPlan]` | 同上 | 服务层 API（全部接受/返回 dict 快照，线程安全） |
| `CHANGE_SOURCES`, `CHANGE_ACTION_TYPES`, `REVIEW_VERDICTS` | 同上 | 枚举 |
| `PolicyEngine.evaluate(..., plan_kind="fix", emergency=False, action_type=None)` | `agenticops.services.policy_engine` | 扩展 |
| `notify_change_requested(cr)`, `notify_change_pending_approval(cr, plan)`, `notify_change_result(cr, outcome)` | `agenticops.services.notification_service` | 三个通知点 |
| `plan_stats(start, end, kind="all", bucket="day") -> dict` | `agenticops.services.plan_stats_service` | 统计 |
| 路由 `web/routers/changes.py`（`/api/changes*`）、`web/routers/plans.py`（`/api/plans/stats`）、`web/routers/audit.py`（`/api/command-audits`） | | Plan C 的前端只依赖这些 URL 与下面的 schema 名 |
| `ChangeRequestCreate`, `ChangeRequestResponse`, `ChangeRequestDetail`, `ChangeReasonBody`, `ChangeClarifyBody`, `ChangeResolveReviewBody`, `ChangeTimelineEntry`, `CommandAuditResponse` | `agenticops.web.schemas` | |
| Agent tools `request_change`, `get_change_request`, `list_change_requests`, `execute_change`, `ground_change_targets`, `attach_change_target`, `evaluate_change_policy`, `submit_change_review` | `agenticops.tools.change_tools` | |
| `review_change(change_request_id)` @tool、`sre_agent_review_change(change_request_id) -> str` | `agenticops.agents.sre_agent` | |
| settings: `change_management_enabled`, `change_auto_approve_standard`, `change_review_timeout_seconds` | `agenticops.config` | |

## File Structure

| 文件 | 责任 | Task |
|---|---|---|
| `src/agenticops/services/pipeline_events.py` | `log_event`/`get_timeline` 支持 `change_request_id` | 1 |
| `src/agenticops/services/notification_service.py` | 三个变更通知 + `notification_sent` 记到 CR 时间线 | 1, 9 |
| `src/agenticops/services/policy_engine.py` + `config/policies.yaml` | `plan_kind`/`emergency`/`action_type` 匹配、emergency 穿越冻结 | 2 |
| `src/agenticops/config.py` + `config/settings.yaml` + `CLAUDE.md` | 三个新配置项 | 3 |
| `src/agenticops/services/change_service.py`（新） | 工单生命周期、grounding、策略、审批、执行、终态映射 | 3, 4, 5 |
| `src/agenticops/tools/metadata_tools.py` | `save_fix_plan(plan_kind, change_request_id)`、`save_execution_result` 接映射器、`get_approved_fix_plan` 输出 kind | 6 |
| `src/agenticops/services/executor_service.py`、`src/agenticops/agents/executor_agent.py` | 崩溃/超时接映射器；按 CR 账户解析 CLI 工具 | 6 |
| `src/agenticops/tools/change_tools.py`（新） | 8 个 agent 工具 | 7 |
| `src/agenticops/agents/sre_agent.py` | Mode C 提示词、工具、`sre_agent_review_change`、`review_change` | 8 |
| `src/agenticops/agents/main_agent.py`、`src/agenticops/chat/preprocessor.py`、`src/agenticops/chat/reference_resolver.py` | 规则 5.7、工具注入、`C#N` 引用 | 9 |
| `src/agenticops/cli/main.py` | `/change` `/changes` `/reject`，`/approve` `/execute` 支持 `C<id>` | 10 |
| `src/agenticops/web/schemas.py`、`src/agenticops/web/routers/changes.py`（新）、`src/agenticops/web/routers/audit.py`、`src/agenticops/web/app.py` | REST API | 11 |
| `src/agenticops/services/plan_stats_service.py`（新）、`src/agenticops/web/routers/plans.py`（新） | 统计 | 12 |
| `tests/test_pipeline_events_change.py`、`tests/test_policy_engine_change.py`、`tests/test_change_service.py`、`tests/test_change_service_review.py`、`tests/test_change_service_execution.py`、`tests/test_save_fix_plan_change.py`、`tests/test_change_tools.py`、`tests/test_sre_change_review.py`、`tests/test_main_change_routing.py`、`tests/test_cli_change_commands.py`、`tests/test_changes_api.py`、`tests/test_plan_stats.py`、`tests/test_change_pipeline.py` | 每 Task 一份 | 1-13 |

---

### Task 1: `pipeline_events` 支持 `change_request_id`；`notification_sent` 可记到 CR 时间线

**Files:**
- Modify: `src/agenticops/services/pipeline_events.py`（`_resolve_trace_id` :54-80、`log_event` :83-117、`get_timeline` :120-144）
- Modify: `src/agenticops/services/notification_service.py:150-170`（`notification_sent` 元组块）
- Test: `tests/test_pipeline_events_change.py`

**Interfaces:**
- Produces: `log_event(health_issue_id: Optional[int], event_type, stage, status="completed", detail=None, actor="system", duration_ms=None, trace_id=None, *, change_request_id: Optional[int] = None) -> None`（两个 id 都空 → 只 debug 日志不落库；订阅者只在 `health_issue_id` 非空时通知——ITSM bridge 仍只看 issue 事件）；`get_timeline(health_issue_id: Optional[int] = None, *, change_request_id: Optional[int] = None) -> list[dict]`（返回项多一个 `change_request_id` 键）。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_pipeline_events_change.py
import pytest

from agenticops.models import Base, ChangeRequest, PipelineEvent, get_session


@pytest.fixture
def db(tmp_path):
    import agenticops.models as models_mod
    from agenticops.config import settings
    models_mod._engine = None
    settings.database_url = f"sqlite:///{tmp_path}/pe.db"
    Base.metadata.create_all(models_mod.get_engine())
    s = get_session()
    yield s
    s.close()
    models_mod._engine = None


def test_log_event_for_change_request(db):
    from agenticops.services.pipeline_events import get_timeline, log_event
    cr = ChangeRequest(title="t", description="d", requested_by="cli:x", trace_id="TRC-cr01")
    db.add(cr); db.commit()
    log_event(None, "change_requested", "intake", detail={"source": "cli"}, actor="cli:x", change_request_id=cr.id)
    rows = db.query(PipelineEvent).all()
    assert len(rows) == 1 and rows[0].change_request_id == cr.id and rows[0].health_issue_id is None
    assert rows[0].trace_id == "TRC-cr01"  # resolved from the ChangeRequest
    tl = get_timeline(change_request_id=cr.id)
    assert tl[0]["event_type"] == "change_requested" and tl[0]["change_request_id"] == cr.id


def test_log_event_without_any_id_is_dropped(db):
    from agenticops.services.pipeline_events import log_event
    log_event(None, "orphan", "x")
    assert db.query(PipelineEvent).count() == 0


def test_subscribers_not_called_for_change_events(db):
    from agenticops.services import pipeline_events as pe
    calls = []
    pe.subscribe(lambda *a: calls.append(a))
    try:
        pe.log_event(None, "change_requested", "intake", change_request_id=1)
        import time; time.sleep(0.05)
        assert calls == []
        pe.log_event(1, "issue_created", "detection")
        time.sleep(0.05)
        assert len(calls) == 1
    finally:
        pe._subscribers.clear()


def test_issue_timeline_unchanged(db):
    from agenticops.services.pipeline_events import get_timeline, log_event
    log_event(42, "rca_started", "rca", trace_id="TRC-x")
    assert get_timeline(42)[0]["event_type"] == "rca_started"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_pipeline_events_change.py -q`
Expected: FAIL — `TypeError: log_event() got an unexpected keyword argument 'change_request_id'`

- [ ] **Step 3: 实现**

`_resolve_trace_id(trace_id, health_issue_id, change_request_id=None)`：DB 回退分支改为

```python
    try:
        from agenticops.models import ChangeRequest, HealthIssue, get_db_session
        with get_db_session() as session:
            if health_issue_id:
                issue = session.query(HealthIssue).filter_by(id=health_issue_id).first()
                if issue and issue.trace_id:
                    return issue.trace_id
            if change_request_id:
                cr = session.query(ChangeRequest).filter_by(id=change_request_id).first()
                if cr and cr.trace_id:
                    return cr.trace_id
    except Exception:
        pass
    return None
```

`log_event`：

```python
def log_event(
    health_issue_id: Optional[int],
    event_type: str,
    stage: str,
    status: str = "completed",
    detail: Optional[dict] = None,
    actor: str = "system",
    duration_ms: Optional[int] = None,
    trace_id: Optional[str] = None,
    *,
    change_request_id: Optional[int] = None,
) -> None:
    """Log a pipeline event for a HealthIssue OR a ChangeRequest (best-effort, never raises)."""
    if not health_issue_id and not change_request_id:
        logger.debug("pipeline event %s dropped: no issue or change id", event_type)
        return
    try:
        from agenticops.models import PipelineEvent, get_db_session
        resolved_tid = _resolve_trace_id(trace_id, health_issue_id, change_request_id)
        with get_db_session() as session:
            session.add(PipelineEvent(
                health_issue_id=health_issue_id or None, change_request_id=change_request_id or None,
                event_type=event_type, stage=stage, status=status,
                detail=json.dumps(detail) if detail else None, actor=actor,
                duration_ms=duration_ms, trace_id=resolved_tid,
            ))
    except Exception:
        logger.debug("Failed to log pipeline event %s (issue=%s change=%s)", event_type, health_issue_id, change_request_id, exc_info=True)
    if health_issue_id:
        try:
            _notify_subscribers(health_issue_id, event_type, stage, status, detail)
        except Exception:
            logger.debug("Subscriber notification failed for %s", event_type, exc_info=True)
```

`get_timeline(health_issue_id: Optional[int] = None, *, change_request_id: Optional[int] = None)`：查询按给定的 id 过滤（两者都空 → 返回 `[]`），返回字典加 `"change_request_id": e.change_request_id`。

`notification_service.py:156-170`：把硬编码元组块改成

```python
                _ISSUE_EVENTS = ("issue_created", "rca_completed", "fix_planned", "fix_approved", "execution_result")
                if event_type in _ISSUE_EVENTS or event_type.startswith("change_"):
                    try:
                        import re
                        from agenticops.services.pipeline_events import log_event as _log_pe
                        detail = {"channels": list(results.keys()), "sent": ok, "failed": fail}
                        if event_type.startswith("change_"):
                            m = re.search(r"Change #(\d+)", subject)
                            if m:
                                _log_pe(None, "notification_sent", "notification", detail=detail,
                                        change_request_id=int(m.group(1)))
                        else:
                            m = re.search(r"Issue #(\d+)", subject) or re.search(r"#(\d+)", subject)
                            if m:
                                _log_pe(int(m.group(1)), "notification_sent", "notification", detail=detail)
                    except Exception:
                        pass
```

- [ ] **Step 4: 跑测试 + 回归（`test_pipeline_events.py`、`test_itsm.py`、`test_notification_service.py`）**

Run: `python -m pytest tests/test_pipeline_events_change.py tests/test_pipeline_events.py tests/test_itsm.py tests/test_notification_service.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/agenticops/services/pipeline_events.py src/agenticops/services/notification_service.py tests/test_pipeline_events_change.py
git commit -m "feat(events): pipeline events and notification_sent can belong to a ChangeRequest"
```

---

### Task 2: 策略引擎扩展 — `plan_kind` / `emergency` / `action_type` 匹配，emergency 穿越冻结

**Files:**
- Modify: `src/agenticops/services/policy_engine.py`（`evaluate` :129-192、`_matches` :194-249、`validate_policy` :263-280、模块常量）
- Modify: `config/policies.yaml`（头部注释加三个 match 字段说明；在 `freeze-window-block` 规则加 emergency 说明）
- Test: `tests/test_policy_engine_change.py`

**Interfaces:**
- Produces: `CHANGE_ACTION_TYPES = ("tag","scale","config","network","iam","delete","other")`；`evaluate(..., plan_kind: str = "fix", emergency: bool = False, action_type: Optional[str] = None)`；yaml `match` 支持 `plan_kind: [fix, change]`、`action_type: [tag, ...]`、`emergency: true|false`；`in_change_freeze` 规则在 `emergency=True` 时不匹配。旧规则/`DEFAULT_POLICY` 对 fix 流行为不变。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_policy_engine_change.py
from datetime import datetime, timedelta, timezone

from agenticops.services.policy_engine import PolicyEngine, validate_policy


def _engine(rules, freeze=None):
    return PolicyEngine({"version": 1, "defaults": {"action": "require_human"},
                         "freeze_windows": freeze or [], "rules": rules})


def test_plan_kind_match_isolates_change_rules():
    eng = _engine([
        {"name": "change-tags-auto", "match": {"plan_kind": ["change"], "action_type": ["tag"], "risk_level": ["L0", "L1"]},
         "action": "auto_approve", "itsm_change_type": "standard"},
        {"name": "fix-low-auto", "match": {"plan_kind": ["fix"], "risk_level": ["L0", "L1"]}, "action": "auto_approve"},
    ])
    d = eng.evaluate(risk_level="L1", plan_kind="change", action_type="tag")
    assert d.action == "auto_approve" and d.rule_name == "change-tags-auto" and d.itsm_change_type == "standard"
    d2 = eng.evaluate(risk_level="L1", plan_kind="change", action_type="network")
    assert d2.action == "require_human" and d2.rule_name == "(default)"
    d3 = eng.evaluate(risk_level="L1")  # fix, default plan_kind
    assert d3.rule_name == "fix-low-auto"


def test_emergency_bypasses_freeze_window():
    now = datetime.now(timezone.utc)
    freeze = [{"name": "cny", "start": (now - timedelta(hours=1)).isoformat(), "end": (now + timedelta(hours=1)).isoformat()}]
    eng = _engine([
        {"name": "freeze-window-block", "match": {"in_change_freeze": True}, "action": "block"},
        {"name": "human", "match": {}, "action": "require_human"},
    ], freeze)
    assert eng.evaluate(risk_level="L1", plan_kind="change").action == "block"
    d = eng.evaluate(risk_level="L1", plan_kind="change", emergency=True)
    assert d.action == "require_human" and d.rule_name == "human"


def test_emergency_match_field():
    eng = _engine([{"name": "emergency-human", "match": {"emergency": True}, "action": "require_human", "itsm_change_type": "emergency"},
                   {"name": "rest", "match": {}, "action": "auto_approve"}])
    assert eng.evaluate(risk_level="L1", emergency=True).itsm_change_type == "emergency"
    assert eng.evaluate(risk_level="L1", emergency=False).rule_name == "rest"


def test_legacy_rules_unchanged_for_fix():
    from agenticops.services.policy_engine import DEFAULT_POLICY
    eng = PolicyEngine(DEFAULT_POLICY)
    assert eng.evaluate(risk_level="L1").action == "auto_approve"
    assert eng.evaluate(risk_level="L2").action == "require_human"


def test_validate_new_fields():
    bad = {"rules": [{"name": "x", "match": {"plan_kind": ["bogus"]}, "action": "block"},
                     {"name": "y", "match": {"action_type": "tag"}, "action": "block"},
                     {"name": "z", "match": {"emergency": "yes"}, "action": "block"}]}
    errors = validate_policy(bad)
    assert len(errors) == 3


def test_shipped_policy_file_valid_and_has_change_rules():
    from agenticops.services.policy_engine import get_policy_engine
    eng = get_policy_engine(reload=True)
    d = eng.evaluate(risk_level="L1", plan_kind="change", action_type="tag")
    assert d.action == "auto_approve" and d.itsm_change_type == "standard"
    assert eng.evaluate(risk_level="L3", plan_kind="change").action == "require_human"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_policy_engine_change.py -q`
Expected: FAIL — `TypeError: evaluate() got an unexpected keyword argument 'plan_kind'`

- [ ] **Step 3: 实现**

模块常量（`VALID_ACTIONS` 之后）：

```python
PLAN_KINDS = ("fix", "change")
CHANGE_ACTION_TYPES = ("tag", "scale", "config", "network", "iam", "delete", "other")
```

`evaluate` 签名加 `plan_kind: str = "fix", emergency: bool = False, action_type: Optional[str] = None`，并把三者传给 `self._matches(...)`。`_matches` 签名加同名参数，在 `impact_severities` 块之后、`in_change_freeze` 之前加：

```python
        kinds = match.get("plan_kind")
        if kinds is not None:
            if plan_kind not in kinds:
                return False, []
            reasons.append(f"plan_kind={plan_kind}")

        action_types = match.get("action_type")
        if action_types is not None:
            if action_type not in action_types:
                return False, []
            reasons.append(f"action_type={action_type}")

        want_emergency = match.get("emergency")
        if want_emergency is not None:
            if bool(want_emergency) != bool(emergency):
                return False, []
            reasons.append(f"emergency={bool(emergency)}")
```

`in_change_freeze` 块改为：

```python
        if match.get("in_change_freeze"):
            if emergency:
                return False, []  # emergency changes are allowed to cross a freeze window (still human-gated by other rules)
            window = self._active_freeze_window(now)
            ...
```

`validate_policy` 在 `resource_pattern` 校验后加：

```python
        m = match or {}
        if "plan_kind" in m and (not isinstance(m["plan_kind"], list) or any(k not in PLAN_KINDS for k in m["plan_kind"])):
            errors.append(f"{label}: plan_kind must be a list from {list(PLAN_KINDS)}")
        if "action_type" in m and (not isinstance(m["action_type"], list) or any(a not in CHANGE_ACTION_TYPES for a in m["action_type"])):
            errors.append(f"{label}: action_type must be a list from {list(CHANGE_ACTION_TYPES)}")
        if "emergency" in m and not isinstance(m["emergency"], bool):
            errors.append(f"{label}: emergency must be true/false")
```

`config/policies.yaml`：头部 "Match fields" 注释加三行（`plan_kind: [fix, change]`、`action_type: [tag, scale, config, network, iam, delete, other]`、`emergency: true|false — requested_change_type=emergency (also lets the change cross freeze windows)`）；在 `auto-approve-low-risk` 规则之前插入两条**change 专用**规则（放在通用规则之前，first-match）：

```yaml
  # ── Change Management (MVP-2.6.0) ──
  # Standard change: low-risk tagging/config on a change request. auto_approve here is
  # NECESSARY but not sufficient — settings.change_auto_approve_standard (default false)
  # must also be on, otherwise the plan waits for a human approver.
  - name: change-standard-low-risk
    match: { plan_kind: [change], risk_level: [L0, L1], action_type: [tag, config, scale] }
    action: auto_approve
    itsm_change_type: standard

  # Any other change (L2/L3, network/iam/delete, emergency) needs a human approver.
  - name: change-normal-human
    match: { plan_kind: [change] }
    action: require_human
    itsm_change_type: normal
```

- [ ] **Step 4: 跑测试 + 回归**

Run: `python -m pytest tests/test_policy_engine_change.py tests/test_policy_engine_simulation.py tests/test_pipeline_service.py -q`
Expected: PASS（fix 流规则未变：新规则都带 `plan_kind: [change]`）

- [ ] **Step 5: Commit**

```bash
git add src/agenticops/services/policy_engine.py config/policies.yaml tests/test_policy_engine_change.py
git commit -m "feat(policy): plan_kind / action_type / emergency match fields; emergency crosses freeze windows"
```

---

### Task 3: `change_service` 核心 — 配置项、异常、快照、`create_change_request`、`start_review` 线程 + 看门狗

**Files:**
- Create: `src/agenticops/services/change_service.py`
- Modify: `src/agenticops/config.py`（`policy_file` 之后加三个 Field）、`config/settings.yaml`（`policy_file` 之后）、`CLAUDE.md`（配置表三行）
- Test: `tests/test_change_service.py`

**Interfaces:**
- Produces（本 Task）：异常类；`CHANGE_SOURCES = {"chat","web","cli","im","webhook","api"}`；`REVIEW_VERDICTS = ("approved_for_planning","needs_clarification","rejected")`；`to_dict(cr) -> dict`；`get_change(cr_id) -> dict`；`list_changes(*, status=None, account_id=None, requested_by=None, since=None, limit=50, offset=0) -> list[dict]`；`create_change_request(*, source, actor, title, description, account_name=None, targets=(), requested_change_type="normal", justification="", chat_session_id=None, start_review=True) -> dict`；`start_review(cr_id, *, sync: bool) -> Optional[str]`；`restart_review(cr_id, *, actor) -> dict`；`_run_review(cr_id, trace_id)`（线程体，调 `agents.sre_agent.sre_agent_review_change`）；`_review_failed(cr_id, error)`。
- settings：`change_management_enabled: bool = True`，`change_auto_approve_standard: bool = False`，`change_review_timeout_seconds: int = 600`。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_change_service.py
"""change_service: creation, review lifecycle, watchdog (MVP-2.6.0 S2)."""
from unittest.mock import patch

import pytest

from agenticops.auth.actor import Actor, cli_actor
from agenticops.models import Base, ChangeRequest, CloudAccount, PipelineEvent, get_session


@pytest.fixture
def db(tmp_path):
    import agenticops.models as models_mod
    import agenticops.audit.models  # noqa: F401
    from agenticops.config import settings
    models_mod._engine = None
    settings.database_url = f"sqlite:///{tmp_path}/cs.db"
    Base.metadata.create_all(models_mod.get_engine())
    s = get_session()
    s.add(CloudAccount(name="dev", provider="aws", is_enabled=True, credentials={"account_id": "111111111111"}, regions=["ap-southeast-1"]))
    s.commit()
    yield s
    s.close()
    models_mod._engine = None


ALICE = Actor("user", "alice", user_id=1, permissions=("read", "write"))


def _audits(db, action):
    from agenticops.audit.models import AuditLog
    return db.query(AuditLog).filter_by(action=action).all()


class TestCreate:
    def test_create_writes_cr_audit_event_and_notifies(self, db):
        from agenticops.services import change_service as cs
        with patch.object(cs, "notify_change_requested") as notify, patch.object(cs, "start_review") as sr:
            cr = cs.create_change_request(source="web", actor=ALICE, title="Tag prod EC2", description="add Env=prod to i-0abc",
                                          account_name="dev", targets=["i-0abc"], justification="compliance")
        assert cr["status"] == "draft" and cr["requested_by"] == "user:alice" and cr["requester_user_id"] == 1
        assert cr["target_hints"] == ["i-0abc"] and cr["target_resources"] == [] and cr["source"] == "web"
        assert cr["account_id"] is not None and cr["trace_id"].startswith("TRC-")
        assert len(_audits(db, "change.requested")) == 1
        ev = db.query(PipelineEvent).filter_by(change_request_id=cr["id"]).one()
        assert ev.event_type == "change_requested" and ev.stage == "intake"
        notify.assert_called_once()
        sr.assert_called_once_with(cr["id"], sync=False)

    def test_unknown_account_is_validation_error(self, db):
        from agenticops.services import change_service as cs
        with pytest.raises(cs.ChangeValidationError):
            cs.create_change_request(source="web", actor=ALICE, title="t", description="d", account_name="nope", start_review=False)

    def test_bad_source_and_type(self, db):
        from agenticops.services import change_service as cs
        with pytest.raises(cs.ChangeValidationError):
            cs.create_change_request(source="carrier-pigeon", actor=ALICE, title="t", description="d", start_review=False)
        with pytest.raises(cs.ChangeValidationError):
            cs.create_change_request(source="web", actor=ALICE, title="t", description="d", requested_change_type="urgent", start_review=False)

    def test_disabled_flag(self, db):
        from agenticops.config import settings
        from agenticops.services import change_service as cs
        with patch.object(settings, "change_management_enabled", False):
            with pytest.raises(cs.ChangeStateError):
                cs.create_change_request(source="web", actor=ALICE, title="t", description="d", start_review=False)

    def test_authz_denied_maps_to_forbidden(self, db):
        from agenticops.config import settings
        from agenticops.services import change_service as cs
        im = Actor("im", "feishu:ou_1", permissions=())  # im subject: read only → change.request allowed
        cs.create_change_request(source="im", actor=im, title="t", description="d", start_review=False)
        nobody = Actor("user", "nobody", permissions=())
        with patch.object(settings, "rbac_enforce", True):
            with pytest.raises(cs.ChangeForbidden):
                cs.create_change_request(source="web", actor=nobody, title="t", description="d", start_review=False)


class TestReviewLifecycle:
    def _cr(self, db):
        from agenticops.services import change_service as cs
        with patch.object(cs, "notify_change_requested"):
            return cs.create_change_request(source="cli", actor=cli_actor(), title="t", description="d", start_review=False)

    def test_start_review_sync_calls_sre_and_transitions(self, db):
        from agenticops.services import change_service as cs
        cr = self._cr(db)
        seen = {}

        def fake_sre(change_request_id):
            seen["status_during"] = db.query(ChangeRequest.status).filter_by(id=change_request_id).scalar()
            # a well-behaved SRE submits a verdict; here we simulate it by moving to planned directly
            with cs._session() as s:
                row = s.get(ChangeRequest, change_request_id)
                cs.transition_change(row, "needs_clarification")
            return "reviewed"

        with patch("agenticops.agents.sre_agent.sre_agent_review_change", side_effect=fake_sre):
            out = cs.start_review(cr["id"], sync=True)
        assert out == "reviewed" and seen["status_during"] == "under_review"
        assert cs.get_change(cr["id"])["status"] == "needs_clarification"

    def test_review_without_verdict_rolls_back_to_draft(self, db):
        from agenticops.services import change_service as cs
        cr = self._cr(db)
        with patch("agenticops.agents.sre_agent.sre_agent_review_change", return_value="I forgot to submit"), \
             patch.object(cs, "notify_change_result") as notify:
            cs.start_review(cr["id"], sync=True)
        c = cs.get_change(cr["id"])
        assert c["status"] == "draft"
        assert any(e.event_type == "review_failed" for e in db.query(PipelineEvent).filter_by(change_request_id=cr["id"]))
        notify.assert_called_once()

    def test_review_exception_rolls_back_to_draft(self, db):
        from agenticops.services import change_service as cs
        cr = self._cr(db)
        with patch("agenticops.agents.sre_agent.sre_agent_review_change", side_effect=RuntimeError("bedrock down")), \
             patch.object(cs, "notify_change_result"):
            cs.start_review(cr["id"], sync=True)
        assert cs.get_change(cr["id"])["status"] == "draft"

    def test_watchdog_fires_when_still_under_review(self, db):
        from agenticops.services import change_service as cs
        cr = self._cr(db)
        with cs._session() as s:
            cs.transition_change(s.get(ChangeRequest, cr["id"]), "under_review")
        with patch.object(cs, "notify_change_result"):
            cs._watchdog_fire(cr["id"])
        assert cs.get_change(cr["id"])["status"] == "draft"

    def test_watchdog_noop_when_review_finished(self, db):
        from agenticops.services import change_service as cs
        cr = self._cr(db)
        with cs._session() as s:
            row = s.get(ChangeRequest, cr["id"])
            cs.transition_change(row, "under_review"); cs.transition_change(row, "planned")
        cs._watchdog_fire(cr["id"])
        assert cs.get_change(cr["id"])["status"] == "planned"

    def test_start_review_from_wrong_state_is_409(self, db):
        from agenticops.services import change_service as cs
        cr = self._cr(db)
        with cs._session() as s:
            row = s.get(ChangeRequest, cr["id"])
            cs.transition_change(row, "under_review"); cs.transition_change(row, "planned")
        with pytest.raises(cs.ChangeStateError):
            cs.start_review(cr["id"], sync=True)

    def test_async_start_review_spawns_thread(self, db):
        from agenticops.services import change_service as cs
        cr = self._cr(db)
        with patch.object(cs.threading, "Thread") as thread, patch.object(cs.threading, "Timer") as timer:
            cs.start_review(cr["id"], sync=False)
        assert thread.called and timer.called
        assert cs.get_change(cr["id"])["status"] == "under_review"

    def test_restart_review_requires_draft(self, db):
        from agenticops.services import change_service as cs
        cr = self._cr(db)
        with patch.object(cs, "start_review") as sr:
            cs.restart_review(cr["id"], actor=cli_actor())
        sr.assert_called_once_with(cr["id"], sync=False)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_change_service.py -q`
Expected: FAIL — `ModuleNotFoundError: agenticops.services.change_service`

- [ ] **Step 3: 配置项**

`config.py`（`policy_file` Field 之后）：

```python
    # ── Change Management (MVP-2.6.0) ────────────────────────────────
    change_management_enabled: bool = Field(
        default=True,
        description="Enable the ITSM change flow: change tools on the main agent, /api/changes, CLI /change (AIOPS_CHANGE_MANAGEMENT_ENABLED)",
    )
    change_auto_approve_standard: bool = Field(
        default=False,
        description="Let a policy 'auto_approve' decision approve a change WITHOUT a human. Both the yaml rule and this flag must agree (AIOPS_CHANGE_AUTO_APPROVE_STANDARD)",
    )
    change_review_timeout_seconds: int = Field(
        default=600,
        description="SRE change-review watchdog; on timeout the request returns to draft with a review_failed event (AIOPS_CHANGE_REVIEW_TIMEOUT_SECONDS)",
    )
```

`settings.yaml`（`policy_file` 之后）：

```yaml
change_management_enabled: true
change_auto_approve_standard: false   # standard changes still wait for a human until you flip this
change_review_timeout_seconds: 600
```

CLAUDE.md 配置表三行（同描述）。

- [ ] **Step 4: `services/change_service.py`（本 Task 的部分；后续 Task 追加函数）**

```python
"""Change Management service — the ONLY owner of ChangeRequest state and transactions (MVP-2.6.0).

Every write path (chat, web, CLI, agent tools) lands here:
  authz.check → validate_change_transition → audit_logs (same transaction) → pipeline_events → notify.
Terminal states are written only by on_execution_result() / resolve_review().
All public functions accept and return plain dicts (snapshots) so callers on other threads
never touch detached ORM rows.
"""

from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator, Optional

from agenticops.auth import authz
from agenticops.auth.actor import Actor, agent_actor
from agenticops.audit.service import Actions, AuditService, EntityTypes
from agenticops.config import generate_trace_id, get_trace_id, set_trace_id, settings
from agenticops.models import (
    CHANGE_TERMINAL_STATUSES, ChangeRequest, CloudAccount, FixPlan, InvalidStatusTransition,
    get_db_session, transition_change, transition_plan,
)
from agenticops.services.notification_service import (
    notify_change_pending_approval, notify_change_requested, notify_change_result,
)
from agenticops.services.pipeline_events import log_event

logger = logging.getLogger(__name__)

CHANGE_SOURCES = {"chat", "web", "cli", "im", "webhook", "api"}
REQUESTED_CHANGE_TYPES = {"normal", "emergency"}
REVIEW_VERDICTS = ("approved_for_planning", "needs_clarification", "rejected")
CHANGE_ACTION_TYPES = ("tag", "scale", "config", "network", "iam", "delete", "other")


# ── Errors (mapped to HTTP by the router) ─────────────────────────────

class ChangeError(Exception):
    status_code = 400


class ChangeNotFound(ChangeError):
    status_code = 404


class ChangeStateError(ChangeError):
    status_code = 409


class ChangeValidationError(ChangeError):
    status_code = 422


class ChangeForbidden(ChangeError):
    status_code = 403


# ── Helpers ───────────────────────────────────────────────────────────

@contextmanager
def _session() -> Iterator[Any]:
    with get_db_session() as s:
        yield s


def _check(actor: Actor, permission: str, subject: Any = None) -> None:
    try:
        authz.check(actor, permission, subject=subject)
    except authz.AuthzDenied as e:
        raise ChangeForbidden(str(e)) from e


def _require_enabled() -> None:
    if not settings.change_management_enabled:
        raise ChangeStateError("Change management is disabled (change_management_enabled=false)")


def _load(session, cr_id: int) -> ChangeRequest:
    cr = session.get(ChangeRequest, cr_id)
    if cr is None:
        raise ChangeNotFound(f"ChangeRequest #{cr_id} not found")
    return cr


def _transition(cr: ChangeRequest, new_status: str) -> None:
    try:
        transition_change(cr, new_status)
    except InvalidStatusTransition as e:
        raise ChangeStateError(str(e)) from e


def _audit(session, action: str, cr: ChangeRequest, actor: Actor, *, details: Optional[dict] = None,
           old_status: Optional[str] = None, new_status: Optional[str] = None) -> None:
    AuditService.log(
        action, EntityTypes.CHANGE_REQUEST, str(cr.id), entity_name=cr.title, actor=actor.key,
        user_id=actor.user_id, details=details or {},
        old_values={"status": old_status} if old_status else None,
        new_values={"status": new_status} if new_status else None, session=session,
    )


def _event(cr_id: int, event_type: str, stage: str, status: str = "completed", *, detail: Optional[dict] = None,
           actor: str = "system", trace_id: Optional[str] = None) -> None:
    log_event(None, event_type, stage, status, detail=detail, actor=actor, trace_id=trace_id, change_request_id=cr_id)


def to_dict(cr: ChangeRequest) -> dict:
    def _iso(v):
        return v.isoformat() if isinstance(v, datetime) else v
    return {
        "id": cr.id, "title": cr.title, "description": cr.description, "justification": cr.justification,
        "source": cr.source, "requested_by": cr.requested_by, "requester_user_id": cr.requester_user_id,
        "requested_at": _iso(cr.requested_at), "account_id": cr.account_id,
        "target_hints": list(cr.target_hints or []), "target_resources": list(cr.target_resources or []),
        "requested_change_type": cr.requested_change_type, "effective_change_type": cr.effective_change_type,
        "risk_level": cr.risk_level, "action_type": cr.action_type, "status": cr.status,
        "review_verdict": cr.review_verdict, "review_reasons": list(cr.review_reasons or []),
        "reviewed_by": cr.reviewed_by, "reviewed_at": _iso(cr.reviewed_at),
        "policy_rule": cr.policy_rule, "policy_action": cr.policy_action,
        "approved_by": cr.approved_by, "approver_user_id": cr.approver_user_id, "approved_at": _iso(cr.approved_at),
        "approval_reason": cr.approval_reason, "rejected_by": cr.rejected_by, "rejected_at": _iso(cr.rejected_at),
        "rejection_reason": cr.rejection_reason, "closed_at": _iso(cr.closed_at), "trace_id": cr.trace_id,
        "chat_session_id": cr.chat_session_id, "created_at": _iso(cr.created_at), "updated_at": _iso(cr.updated_at),
    }


def get_change(cr_id: int) -> dict:
    with _session() as s:
        return to_dict(_load(s, cr_id))


def list_changes(*, status: Optional[str] = None, account_id: Optional[int] = None, requested_by: Optional[str] = None,
                 since: Optional[datetime] = None, limit: int = 50, offset: int = 0) -> list[dict]:
    with _session() as s:
        q = s.query(ChangeRequest).order_by(ChangeRequest.created_at.desc())
        if status:
            q = q.filter(ChangeRequest.status == status)
        if account_id is not None:
            q = q.filter(ChangeRequest.account_id == account_id)
        if requested_by:
            q = q.filter(ChangeRequest.requested_by == requested_by)
        if since is not None:
            q = q.filter(ChangeRequest.created_at >= since)
        return [to_dict(c) for c in q.offset(offset).limit(limit).all()]


def active_plan_for(session, cr_id: int) -> Optional[FixPlan]:
    """Latest non-terminal change plan for a request (None when there is none)."""
    from agenticops.models import FIXPLAN_TERMINAL_STATUSES
    return (
        session.query(FixPlan)
        .filter(FixPlan.change_request_id == cr_id, FixPlan.plan_kind == "change",
                FixPlan.status.notin_(FIXPLAN_TERMINAL_STATUSES))
        .order_by(FixPlan.created_at.desc())
        .first()
    )


# ── Intake ────────────────────────────────────────────────────────────

def create_change_request(
    *, source: str, actor: Actor, title: str, description: str, account_name: Optional[str] = None,
    targets: Optional[list[str]] = None, requested_change_type: str = "normal", justification: str = "",
    chat_session_id: Optional[str] = None, start_review: bool = True,
) -> dict:
    """Unified intake for chat / web / cli / im / (P2 webhook). Returns the CR snapshot."""
    _require_enabled()
    _check(actor, "change.request")
    if source not in CHANGE_SOURCES:
        raise ChangeValidationError(f"invalid source {source!r}; expected one of {sorted(CHANGE_SOURCES)}")
    if requested_change_type not in REQUESTED_CHANGE_TYPES:
        raise ChangeValidationError(f"invalid requested_change_type {requested_change_type!r}; expected normal|emergency")
    title = (title or "").strip()
    description = (description or "").strip()
    if not title or not description:
        raise ChangeValidationError("title and description are required")
    hints = [str(t).strip() for t in (targets or []) if str(t).strip()]

    trace_id = get_trace_id() or generate_trace_id()
    with _session() as s:
        account_id = None
        if account_name:
            acct = s.query(CloudAccount).filter_by(name=account_name, is_enabled=True).first()
            if acct is None:
                raise ChangeValidationError(f"account {account_name!r} not found or disabled")
            account_id = acct.id
        cr = ChangeRequest(
            title=title[:300], description=description, justification=justification or "", source=source,
            requested_by=actor.key, requester_user_id=actor.user_id, account_id=account_id, target_hints=hints,
            target_resources=[], requested_change_type=requested_change_type, status="draft", trace_id=trace_id,
            chat_session_id=chat_session_id,
        )
        s.add(cr)
        s.flush()
        _audit(s, Actions.CHANGE_REQUESTED, cr, actor,
               details={"source": source, "requested_change_type": requested_change_type, "targets": hints},
               new_status="draft")
        snap = to_dict(cr)
    _event(snap["id"], "change_requested", "intake", detail={"source": source, "targets": hints}, actor=actor.key, trace_id=trace_id)
    try:
        notify_change_requested(snap)
    except Exception:
        logger.debug("notify_change_requested failed", exc_info=True)
    if start_review:
        globals()["start_review"](snap["id"], sync=False)
    return snap


# ── Review lifecycle ──────────────────────────────────────────────────

def start_review(cr_id: int, *, sync: bool) -> Optional[str]:
    """draft|needs_clarification → under_review, then run the SRE change review.

    sync=True  : run in this thread and return the SRE's text (Main agent's review_change tool).
    sync=False : daemon thread + watchdog Timer(change_review_timeout_seconds) → returns None.
    """
    with _session() as s:
        cr = _load(s, cr_id)
        old = cr.status
        _transition(cr, "under_review")
        trace_id = cr.trace_id
        _audit(s, Actions.CHANGE_REVIEWED, cr, agent_actor("sre"), details={"phase": "started"},
               old_status=old, new_status="under_review")
    _event(cr_id, "change_review_started", "review", "started", actor="agent:sre", trace_id=trace_id)
    if sync:
        return _run_review(cr_id, trace_id)
    threading.Thread(target=_run_review, args=(cr_id, trace_id), daemon=True, name=f"change-review-{cr_id}").start()
    t = threading.Timer(settings.change_review_timeout_seconds, _watchdog_fire, args=(cr_id,))
    t.daemon = True
    t.start()
    return None


def restart_review(cr_id: int, *, actor: Actor) -> dict:
    """Human (re)start of a review for a draft (Main forgot to call review_change, or the watchdog rolled back)."""
    _check(actor, "change.request")
    with _session() as s:
        cr = _load(s, cr_id)
        if cr.status != "draft":
            raise ChangeStateError(f"ChangeRequest #{cr_id} is '{cr.status}', only drafts can be (re)submitted for review")
    start_review(cr_id, sync=False)
    return get_change(cr_id)


def _run_review(cr_id: int, trace_id: Optional[str]) -> Optional[str]:
    """Thread body: set context, run the SRE Mode C agent, enforce 'a review must end with a verdict'."""
    from agenticops.run_context import RunContext, set_run_context
    if trace_id:
        set_trace_id(trace_id)
    set_run_context(RunContext(actor="agent:sre", trace_id=trace_id, agent_name="sre", change_request_id=cr_id))
    result: Optional[str] = None
    try:
        from agenticops.agents.sre_agent import sre_agent_review_change
        result = str(sre_agent_review_change(cr_id))
    except Exception as e:
        logger.exception("Change review crashed for CR #%d", cr_id)
        _review_failed(cr_id, f"review crashed: {e}")
        return result
    try:
        status = get_change(cr_id)["status"]
    except ChangeNotFound:
        return result
    if status == "under_review":
        _review_failed(cr_id, "review ended without a verdict (submit_change_review was not called)")
    return result


def _watchdog_fire(cr_id: int) -> None:
    try:
        if get_change(cr_id)["status"] == "under_review":
            _review_failed(cr_id, f"review timed out after {settings.change_review_timeout_seconds}s")
    except ChangeNotFound:
        pass
    except Exception:
        logger.debug("change review watchdog failed for CR #%d", cr_id, exc_info=True)


def _review_failed(cr_id: int, error: str) -> None:
    """under_review → draft (never stuck), review_failed event, notification."""
    with _session() as s:
        cr = _load(s, cr_id)
        if cr.status != "under_review":
            return
        _transition(cr, "draft")
        cr.review_reasons = [error[:500]]
        _audit(s, Actions.CHANGE_REVIEWED, cr, agent_actor("sre"), details={"phase": "failed", "error": error[:500]},
               old_status="under_review", new_status="draft")
        snap = to_dict(cr)
    _event(cr_id, "review_failed", "review", "failed", detail={"error": error[:500]}, actor="agent:sre", trace_id=snap["trace_id"])
    try:
        notify_change_result(snap, "review_failed")
    except Exception:
        logger.debug("notify_change_result failed", exc_info=True)
```

（`notify_change_*` 三个函数在 Task 9 才实现——为了本 Task 可测，先在 `notification_service.py` 加三个**空实现桩**：`def notify_change_requested(cr: dict) -> None: return None` 等三行，Task 9 替换为真实实现。`transition_change` 通过 `cs.transition_change` 被测试引用——它是从 `agenticops.models` import 进来的名字，无需再包一层。）

- [ ] **Step 5: 跑测试确认通过**

Run: `python -m pytest tests/test_change_service.py -q`
Expected: 14 PASS

- [ ] **Step 6: Commit**

```bash
git add src/agenticops/services/change_service.py src/agenticops/services/notification_service.py src/agenticops/config.py config/settings.yaml CLAUDE.md tests/test_change_service.py
git commit -m "feat(change): change_service core — intake, review lifecycle with watchdog, snapshots, errors"
```

---

### Task 4: grounding（`ground_targets` / `attach_target`）、`evaluate_policy`、`submit_review`（含审批路由）

**Files:**
- Modify: `src/agenticops/services/change_service.py`（追加一节 `# ── Review: grounding, policy, verdict ──`）
- Test: `tests/test_change_service_review.py`

**Interfaces:**
- Produces: `ground_targets(cr_id) -> dict`（`{"grounded": [...], "unresolved": [...]}`，并把 grounded 项写入 `target_resources`）；`attach_target(cr_id, resource_id, resource_type, *, actor, region="", hint="") -> dict`（代码执行只读 describe；成功写入并返回 target 项，失败抛 `ChangeValidationError`）；`DESCRIBE_BY_TYPE: dict[str, str]`；`evaluate_policy(cr_id, risk_level, action_type) -> PolicyDecision`（并写 `policy_decision` 事件）；`submit_review(cr_id, *, verdict, risk_level=None, action_type=None, reasons=(), actor) -> dict`。
- 契约：`approved_for_planning` 需要 ① `target_resources` 非空且没有未解析 hint ② 存在 draft 的 change 计划 ③ 计划 `rollback_plan` 非空且 `post_checks` 非空，否则 `ChangeStateError`；策略 `block` → 强制 rejected；`auto_approve ∧ settings.change_auto_approve_standard` → 调 `approve(..., actor=agent:auto-pipeline)` + `request_execution`（Task 5 实现；本 Task 用 `globals()[...]` 延迟引用，测试里 patch）。否则计划 → `pending_approval`、`notify_change_pending_approval`。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_change_service_review.py
from unittest.mock import patch

import pytest

from agenticops.auth.actor import Actor, agent_actor, cli_actor
from agenticops.models import Base, ChangeRequest, CloudAccount, CloudResource, FixPlan, PipelineEvent, get_session


@pytest.fixture
def db(tmp_path):
    import agenticops.models as models_mod
    import agenticops.audit.models  # noqa: F401
    from agenticops.config import settings
    models_mod._engine = None
    settings.database_url = f"sqlite:///{tmp_path}/rev.db"
    Base.metadata.create_all(models_mod.get_engine())
    s = get_session()
    acct = CloudAccount(name="dev", provider="aws", is_enabled=True, credentials={"account_id": "111111111111"}, regions=["ap-southeast-1"])
    s.add(acct); s.flush()
    s.add(CloudResource(account_id=acct.id, provider="aws", region="ap-southeast-1", resource_type="EC2Instance",
                        resource_id="i-0abc", name="web-1", tags={"Name": "web-1"}))
    s.add(CloudResource(account_id=acct.id, provider="aws", region="ap-southeast-1", resource_type="SecurityGroup",
                        resource_id="sg-111", name="web-sg"))
    s.commit()
    yield s
    s.close()
    models_mod._engine = None


def _cr(db, targets=("i-0abc",), change_type="normal"):
    from agenticops.services import change_service as cs
    with patch.object(cs, "notify_change_requested"):
        cr = cs.create_change_request(source="cli", actor=cli_actor(), title="tag", description="add Env=prod",
                                      account_name="dev", targets=list(targets), requested_change_type=change_type,
                                      start_review=False)
    with cs._session() as s:
        cs.transition_change(s.get(ChangeRequest, cr["id"]), "under_review")
    return cr["id"]


def _draft_plan(db, cr_id, rollback=None, post_checks=None):
    plan = FixPlan(plan_kind="change", change_request_id=cr_id, risk_level="L1", title="p", summary="s",
                   steps=[{"action": "tag", "command": "aws ec2 create-tags ..."}],
                   rollback_plan=rollback if rollback is not None else {"steps": [{"command": "aws ec2 delete-tags ..."}]},
                   post_checks=post_checks if post_checks is not None else [{"check": "tag present", "command": "aws ec2 describe-tags ..."}],
                   status="draft")
    db.add(plan); db.commit()
    return plan


class TestGrounding:
    def test_ground_matches_inventory_by_id_and_name(self, db):
        from agenticops.services import change_service as cs
        cr_id = _cr(db, targets=("i-0abc", "web-sg", "i-missing"))
        out = cs.ground_targets(cr_id)
        assert {g["resource_id"] for g in out["grounded"]} == {"i-0abc", "sg-111"}
        assert out["unresolved"] == ["i-missing"]
        c = cs.get_change(cr_id)
        assert len(c["target_resources"]) == 2 and c["target_resources"][0]["evidence"] == "inventory"

    def test_attach_target_runs_code_describe(self, db):
        from agenticops.services import change_service as cs
        cr_id = _cr(db, targets=("i-0def",))
        with patch("agenticops.tools.aws_cli_tool._execute_aws_cli", return_value='{"Reservations": [1]}') as ex:
            out = cs.attach_target(cr_id, "i-0def", "ec2:instance", actor=agent_actor("sre"))
        assert ex.call_args.args[0].startswith("aws ec2 describe-instances --instance-ids i-0def")
        assert ex.call_args.args[1] == "dev"
        assert out["resource_id"] == "i-0def" and out["evidence"]["command"].startswith("aws ec2 describe-instances")
        assert cs.ground_targets(cr_id)["unresolved"] == []

    def test_attach_target_not_found_is_rejected(self, db):
        from agenticops.services import change_service as cs
        cr_id = _cr(db, targets=("i-0def",))
        with patch("agenticops.tools.aws_cli_tool._execute_aws_cli", return_value="Error (exit code 254): InvalidInstanceID.NotFound"):
            with pytest.raises(cs.ChangeValidationError):
                cs.attach_target(cr_id, "i-0def", "ec2:instance", actor=agent_actor("sre"))
        assert cs.get_change(cr_id)["target_resources"] == []

    def test_attach_target_unknown_type_uses_arn_or_fails(self, db):
        from agenticops.services import change_service as cs
        cr_id = _cr(db, targets=())
        with pytest.raises(cs.ChangeValidationError):
            cs.attach_target(cr_id, "thing-1", "made:up", actor=agent_actor("sre"))
        with patch("agenticops.tools.aws_cli_tool._execute_aws_cli", return_value='{"ResourceTagMappingList":[{}]}') as ex:
            cs.attach_target(cr_id, "arn:aws:sqs:ap-southeast-1:111111111111:q1", "sqs:queue", actor=agent_actor("sre"))
        assert "resourcegroupstaggingapi get-resources" in ex.call_args.args[0]


class TestPolicy:
    def test_evaluate_policy_uses_change_kind_and_logs_event(self, db):
        from agenticops.services import change_service as cs
        cr_id = _cr(db)
        cs.ground_targets(cr_id)
        d = cs.evaluate_policy(cr_id, "L1", "tag")
        assert d.action == "auto_approve" and d.itsm_change_type == "standard"
        assert any(e.event_type == "policy_decision" for e in db.query(PipelineEvent).filter_by(change_request_id=cr_id))

    def test_emergency_flag_is_passed(self, db):
        from agenticops.services import change_service as cs
        cr_id = _cr(db, change_type="emergency")
        with patch("agenticops.services.policy_engine.PolicyEngine.evaluate") as ev:
            ev.return_value.to_dict.return_value = {}
            ev.return_value.action = "require_human"; ev.return_value.rule_name = "x"; ev.return_value.itsm_change_type = "normal"
            cs.evaluate_policy(cr_id, "L2", "network")
        assert ev.call_args.kwargs["emergency"] is True and ev.call_args.kwargs["plan_kind"] == "change"


class TestSubmitReview:
    def test_requires_grounded_targets_and_plan(self, db):
        from agenticops.services import change_service as cs
        cr_id = _cr(db)
        with pytest.raises(cs.ChangeStateError):  # nothing grounded, no plan
            cs.submit_review(cr_id, verdict="approved_for_planning", risk_level="L1", action_type="tag", reasons=["ok"], actor=agent_actor("sre"))
        cs.ground_targets(cr_id)
        with pytest.raises(cs.ChangeStateError):  # no plan yet
            cs.submit_review(cr_id, verdict="approved_for_planning", risk_level="L1", action_type="tag", reasons=["ok"], actor=agent_actor("sre"))
        _draft_plan(db, cr_id, rollback={})
        with pytest.raises(cs.ChangeStateError):  # rollback missing
            cs.submit_review(cr_id, verdict="approved_for_planning", risk_level="L1", action_type="tag", reasons=["ok"], actor=agent_actor("sre"))

    def test_planned_waits_for_human_by_default(self, db):
        from agenticops.services import change_service as cs
        cr_id = _cr(db)
        cs.ground_targets(cr_id)
        plan = _draft_plan(db, cr_id)
        with patch.object(cs, "notify_change_pending_approval") as notify:
            out = cs.submit_review(cr_id, verdict="approved_for_planning", risk_level="L1", action_type="tag",
                                   reasons=["single instance tag"], actor=agent_actor("sre"))
        assert out["status"] == "planned" and out["effective_change_type"] == "standard"
        assert out["policy_rule"] == "change-standard-low-risk" and out["policy_action"] == "auto_approve"
        db.refresh(plan)
        assert plan.status == "pending_approval"
        notify.assert_called_once()

    def test_auto_approve_when_flag_and_rule_agree(self, db):
        from agenticops.config import settings
        from agenticops.services import change_service as cs
        cr_id = _cr(db)
        cs.ground_targets(cr_id)
        _draft_plan(db, cr_id)
        with patch.object(settings, "change_auto_approve_standard", True), \
             patch.object(cs, "approve") as approve, patch.object(cs, "request_execution") as execute:
            cs.submit_review(cr_id, verdict="approved_for_planning", risk_level="L1", action_type="tag", reasons=["ok"], actor=agent_actor("sre"))
        approve.assert_called_once()
        assert approve.call_args.kwargs["actor"].key == "agent:auto-pipeline"
        assert "change-standard-low-risk" in approve.call_args.kwargs["reason"]
        execute.assert_called_once()

    def test_block_forces_rejected(self, db):
        from agenticops.services import change_service as cs
        cr_id = _cr(db)
        cs.ground_targets(cr_id)
        _draft_plan(db, cr_id)
        from agenticops.services.policy_engine import PolicyDecision
        with patch.object(cs, "evaluate_policy", return_value=PolicyDecision(action="block", rule_name="freeze-window-block", reasons=["freeze"])), \
             patch.object(cs, "notify_change_result") as notify:
            out = cs.submit_review(cr_id, verdict="approved_for_planning", risk_level="L1", action_type="tag", reasons=["ok"], actor=agent_actor("sre"))
        assert out["status"] == "rejected" and out["policy_rule"] == "freeze-window-block"
        assert "freeze" in " ".join(out["review_reasons"])
        notify.assert_called_once()

    def test_needs_clarification_and_rejected_verdicts(self, db):
        from agenticops.services import change_service as cs
        cr_id = _cr(db, targets=("i-missing",))
        with patch.object(cs, "notify_change_result"):
            out = cs.submit_review(cr_id, verdict="needs_clarification", reasons=["i-missing not found"], actor=agent_actor("sre"))
        assert out["status"] == "needs_clarification" and out["review_reasons"] == ["i-missing not found"]
        cr2 = _cr(db)
        with patch.object(cs, "notify_change_result"):
            out2 = cs.submit_review(cr2, verdict="rejected", reasons=["out of scope"], actor=agent_actor("sre"))
        assert out2["status"] == "rejected" and out2["rejected_by"] == "agent:sre"

    def test_bad_verdict_or_risk(self, db):
        from agenticops.services import change_service as cs
        cr_id = _cr(db)
        with pytest.raises(cs.ChangeValidationError):
            cs.submit_review(cr_id, verdict="maybe", reasons=[], actor=agent_actor("sre"))
        with pytest.raises(cs.ChangeValidationError):
            cs.submit_review(cr_id, verdict="approved_for_planning", risk_level="L9", action_type="tag", reasons=[], actor=agent_actor("sre"))
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_change_service_review.py -q`
Expected: FAIL — `AttributeError: module ... has no attribute 'ground_targets'`

- [ ] **Step 3: 实现（追加到 `change_service.py`）**

```python
# ── Review: grounding, policy, verdict ────────────────────────────────

DESCRIBE_BY_TYPE: dict[str, str] = {
    "ec2:instance": "aws ec2 describe-instances --instance-ids {rid}",
    "ec2:security-group": "aws ec2 describe-security-groups --group-ids {rid}",
    "ec2:subnet": "aws ec2 describe-subnets --subnet-ids {rid}",
    "ec2:vpc": "aws ec2 describe-vpcs --vpc-ids {rid}",
    "ec2:volume": "aws ec2 describe-volumes --volume-ids {rid}",
    "rds:db": "aws rds describe-db-instances --db-instance-identifier {rid}",
    "eks:cluster": "aws eks describe-cluster --name {rid}",
    "s3:bucket": "aws s3api head-bucket --bucket {rid}",
    "lambda:function": "aws lambda get-function --function-name {rid}",
    "autoscaling:group": "aws autoscaling describe-auto-scaling-groups --auto-scaling-group-names {rid}",
    "elbv2:load-balancer": "aws elbv2 describe-load-balancers --load-balancer-arns {rid}",
}
_ARN_DESCRIBE = "aws resourcegroupstaggingapi get-resources --resource-arn-list {rid}"


def _account_name(session, cr: ChangeRequest) -> str:
    if not cr.account_id:
        return ""
    return session.query(CloudAccount.name).filter_by(id=cr.account_id).scalar() or ""


def _hint_matches(hint: str, r: CloudResource) -> bool:
    h = hint.lower()
    rid = (r.resource_id or "").lower()
    if h == rid or (h.startswith("arn:") and rid and (h.endswith("/" + rid) or h.endswith(":" + rid))):
        return True
    if (r.name or "").lower() == h:
        return True
    tags = r.tags or {}
    return str(tags.get("Name", "")).lower() == h


def ground_targets(cr_id: int) -> dict:
    """Deterministic: match target_hints against the inventory (account-scoped); write matches."""
    with _session() as s:
        cr = _load(s, cr_id)
        q = s.query(CloudResource)
        if cr.account_id:
            q = q.filter(CloudResource.account_id == cr.account_id)
        rows = q.all()
        existing = {t.get("resource_id") for t in (cr.target_resources or [])}
        grounded, unresolved = [], []
        for hint in cr.target_hints or []:
            match = next((r for r in rows if _hint_matches(hint, r)), None)
            if match is None:
                if not any(hint.lower() == str(t.get("resource_id", "")).lower() for t in (cr.target_resources or [])):
                    unresolved.append(hint)
                continue
            item = {"resource_id": match.resource_id, "resource_type": match.resource_type, "db_id": match.id,
                    "region": match.region, "evidence": "inventory", "hint": hint}
            grounded.append(item)
            if match.resource_id not in existing:
                cr.target_resources = list(cr.target_resources or []) + [item]
                existing.add(match.resource_id)
        cr.updated_at = datetime.now(timezone.utc)
        return {"grounded": grounded, "unresolved": unresolved, "target_resources": list(cr.target_resources or [])}


def attach_target(cr_id: int, resource_id: str, resource_type: str, *, actor: Actor, region: str = "",
                  hint: str = "") -> dict:
    """Attach a target NOT in the inventory — only after a CODE-executed read-only describe succeeds.
    `hint` names the requester's original wording this target resolves (so submit_review stops treating
    that hint as unresolved); defaults to the resource_id itself."""
    from agenticops.tools.aws_cli_tool import _execute_aws_cli
    resource_id = (resource_id or "").strip()
    if not resource_id:
        raise ChangeValidationError("resource_id is required")
    template = _ARN_DESCRIBE if resource_id.startswith("arn:") else DESCRIBE_BY_TYPE.get(resource_type)
    if template is None:
        raise ChangeValidationError(
            f"unknown resource_type {resource_type!r}; use one of {sorted(DESCRIBE_BY_TYPE)} or pass the resource ARN"
        )
    with _session() as s:
        cr = _load(s, cr_id)
        account = _account_name(s, cr)
    command = template.format(rid=resource_id) + (f" --region {region}" if region else "")
    result = _execute_aws_cli(command, account)
    if not result or result.startswith("Error") or result == "(no output)":
        raise ChangeValidationError(f"target {resource_id!r} could not be verified: {(result or '')[:200]}")
    item = {"resource_id": resource_id, "resource_type": resource_type, "db_id": None, "region": region or None,
            "evidence": {"command": command, "excerpt": result[:300]}, "hint": (hint or resource_id)}
    with _session() as s:
        cr = _load(s, cr_id)
        if not any(t.get("resource_id") == resource_id for t in (cr.target_resources or [])):
            cr.target_resources = list(cr.target_resources or []) + [item]
        if resource_id not in (cr.target_hints or []):
            cr.target_hints = list(cr.target_hints or []) + [resource_id]
        cr.updated_at = datetime.now(timezone.utc)
        _audit(s, Actions.CHANGE_REVIEWED, cr, actor, details={"phase": "target_attached", "resource_id": resource_id,
                                                              "resource_type": resource_type, "command": command})
    return item


def evaluate_policy(cr_id: int, risk_level: str, action_type: Optional[str]):
    """Deterministic policy decision for a change (plan_kind=change, emergency, freeze, blast radius)."""
    from agenticops.services.policy_engine import estimate_blast_radius, get_policy_engine
    with _session() as s:
        cr = _load(s, cr_id)
        provider = native_account = None
        if cr.account_id:
            acct = s.get(CloudAccount, cr.account_id)
            if acct:
                provider = acct.provider
                native_account = (acct.credentials or {}).get("account_id") or None
        targets = list(cr.target_resources or [])
        emergency = cr.requested_change_type == "emergency"
        trace_id = cr.trace_id
    first = targets[0]["resource_id"] if targets else None
    decision = get_policy_engine().evaluate(
        risk_level=risk_level, provider=provider, resource_id=first,
        blast_radius=estimate_blast_radius(first, native_account), plan_kind="change",
        emergency=emergency, action_type=action_type,
    )
    _event(cr_id, "policy_decision", "approval", decision.action,
           detail={"risk_level": risk_level, "action_type": action_type, "policy_decision": decision.to_dict()},
           actor="policy-engine", trace_id=trace_id)
    return decision


def _effective_change_type(decision, requested: str) -> str:
    if requested == "emergency":
        return "emergency"
    if decision.itsm_change_type in ("standard", "normal", "emergency"):
        return decision.itsm_change_type
    return "standard" if decision.action == "auto_approve" else "normal"


def submit_review(cr_id: int, *, verdict: str, risk_level: Optional[str] = None, action_type: Optional[str] = None,
                  reasons: Optional[list[str]] = None, actor: Actor) -> dict:
    """SRE verdict → code decides state. Policy is re-evaluated here; the LLM's reading is advisory."""
    _check(actor, "change.review")
    if verdict not in REVIEW_VERDICTS:
        raise ChangeValidationError(f"verdict must be one of {REVIEW_VERDICTS}")
    reasons = [str(r)[:500] for r in (reasons or [])][:20]
    if verdict == "approved_for_planning":
        if risk_level not in ("L0", "L1", "L2", "L3"):
            raise ChangeValidationError("risk_level must be L0-L3 for approved_for_planning")
        if action_type not in CHANGE_ACTION_TYPES:
            raise ChangeValidationError(f"action_type must be one of {CHANGE_ACTION_TYPES}")

    with _session() as s:
        cr = _load(s, cr_id)
        if cr.status != "under_review":
            raise ChangeStateError(f"ChangeRequest #{cr_id} is '{cr.status}', not under_review")
        cr.reviewed_by = actor.key
        cr.reviewed_at = datetime.now(timezone.utc)
        cr.review_verdict = verdict
        cr.review_reasons = reasons
        if verdict == "needs_clarification":
            _transition(cr, "needs_clarification")
            _audit(s, Actions.CHANGE_REVIEWED, cr, actor, details={"verdict": verdict, "reasons": reasons},
                   old_status="under_review", new_status="needs_clarification")
            snap = to_dict(cr)
            outcome = "needs_clarification"
        elif verdict == "rejected":
            _transition(cr, "rejected")
            cr.rejected_by, cr.rejected_at = actor.key, datetime.now(timezone.utc)
            cr.rejection_reason = "; ".join(reasons) or "rejected by review"
            _audit(s, Actions.CHANGE_REJECTED, cr, actor, details={"verdict": verdict, "reasons": reasons},
                   old_status="under_review", new_status="rejected")
            snap = to_dict(cr)
            outcome = "rejected"
        else:
            unresolved = [h for h in (cr.target_hints or [])
                          if not any(str(t.get("hint", "")).lower() == h.lower() or str(t.get("resource_id", "")).lower() == h.lower()
                                     for t in (cr.target_resources or []))]
            if not cr.target_resources or unresolved:
                raise ChangeStateError(f"all targets must be grounded before planning; unresolved: {unresolved or 'none grounded'}")
            plan = active_plan_for(s, cr_id)
            if plan is None or plan.status != "draft":
                raise ChangeStateError("a draft change plan (save_fix_plan plan_kind=change) is required before submitting the verdict")
            if not plan.rollback_plan or not plan.post_checks:
                raise ChangeStateError("the change plan must have a non-empty rollback_plan and non-empty post_checks")
            plan_id = plan.id
            plan_dict = {"id": plan.id, "title": plan.title, "risk_level": risk_level, "summary": plan.summary}
            cr.risk_level = risk_level
            cr.action_type = action_type

    if verdict != "approved_for_planning":
        _event(cr_id, "change_reviewed", "review", outcome, detail={"verdict": verdict, "reasons": reasons}, actor=actor.key, trace_id=snap["trace_id"])
        try:
            notify_change_result(snap, outcome)
        except Exception:
            logger.debug("notify_change_result failed", exc_info=True)
        return snap

    decision = evaluate_policy(cr_id, risk_level, action_type)
    with _session() as s:
        cr = _load(s, cr_id)
        plan = s.get(FixPlan, plan_id)
        plan.risk_level = risk_level
        cr.policy_rule = decision.rule_name
        cr.policy_action = decision.action
        cr.effective_change_type = _effective_change_type(decision, cr.requested_change_type)
        cr.review_reasons = reasons + [f"policy:{decision.rule_name}:{decision.action}"] + list(decision.reasons)[:5]
        if decision.action == "block":
            _transition(cr, "rejected")
            transition_plan(plan, "rejected")
            plan.rejected_by, plan.rejected_at, plan.rejection_reason = "policy-engine", datetime.now(timezone.utc), decision.rule_name
            cr.rejected_by, cr.rejected_at = "policy-engine", datetime.now(timezone.utc)
            cr.rejection_reason = f"blocked by policy rule {decision.rule_name}: " + "; ".join(decision.reasons)
            _audit(s, Actions.CHANGE_REJECTED, cr, actor, details={"policy_decision": decision.to_dict()},
                   old_status="under_review", new_status="rejected")
            snap = to_dict(cr)
            outcome = "rejected"
        else:
            _transition(cr, "planned")
            transition_plan(plan, "pending_approval")
            _audit(s, Actions.CHANGE_REVIEWED, cr, actor,
                   details={"verdict": verdict, "risk_level": risk_level, "action_type": action_type,
                            "reasons": reasons, "policy_decision": decision.to_dict(), "plan_id": plan_id},
                   old_status="under_review", new_status="planned")
            snap = to_dict(cr)
            outcome = "planned"
    _event(cr_id, "change_reviewed", "review", outcome,
           detail={"verdict": verdict, "risk_level": risk_level, "action_type": action_type, "plan_id": plan_id,
                   "policy_decision": decision.to_dict()}, actor=actor.key, trace_id=snap["trace_id"])

    if outcome == "rejected":
        try:
            notify_change_result(snap, "rejected")
        except Exception:
            logger.debug("notify_change_result failed", exc_info=True)
        return snap

    if decision.action == "auto_approve" and settings.change_auto_approve_standard:
        auto = agent_actor("auto-pipeline")
        globals()["approve"](cr_id, actor=auto, reason=f"policy rule {decision.rule_name} (standard change, auto-approved)")
        globals()["request_execution"](cr_id, actor=auto)
        return get_change(cr_id)

    try:
        notify_change_pending_approval(snap, plan_dict)
    except Exception:
        logger.debug("notify_change_pending_approval failed", exc_info=True)
    return snap
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_change_service_review.py tests/test_change_service.py -q`
Expected: PASS（`approve` / `request_execution` 在测试里被 patch；Task 5 实现真身）

- [ ] **Step 5: Commit**

```bash
git add src/agenticops/services/change_service.py tests/test_change_service_review.py
git commit -m "feat(change): grounding (inventory + code-executed describe), policy evaluation, review verdict routing"
```

---

### Task 5: 审批 / 拒绝 / 取消 / 补充 / 执行入队 / 人工裁定 / 终态映射器

**Files:**
- Modify: `src/agenticops/services/change_service.py`（追加 `# ── Approval & execution ──` 一节）
- Test: `tests/test_change_service_execution.py`

**Interfaces:**
- Produces: `approve(cr_id, *, actor, reason) -> dict`；`reject(cr_id, *, actor, reason) -> dict`；`cancel(cr_id, *, actor, reason) -> dict`；`clarify(cr_id, *, actor, message) -> dict`（追加到 description 并 `start_review(sync=False)`）；`request_execution(cr_id, *, actor) -> dict`（返回 `{"execution_id", "fix_plan_id", "change": snap}`）；`resolve_review(cr_id, *, actor, outcome, reason) -> dict`；`on_execution_result(fix_plan_id, execution_status, *, post_check_results=None, error="") -> Optional[dict]`（非 change 计划返回 None）；`change_timeline(cr_id) -> list[dict]`（events ∪ audits 按时间合并）。
- 终态映射：`succeeded ∧ len(post_checks)>0 ∧ len(post_check_results) ≥ len(post_checks) ∧ 全部 pass` → completed；`succeeded` 但结果缺失/不全/有 fail → needs_review；`failed` → failed；`rolled_back` → rolled_back；`aborted` → failed(reason=aborted)。post_check_result 项判 pass：`item.get("status") in ("pass","passed","ok","succeeded",True)` 或 `item.get("passed") is True`。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_change_service_execution.py
from unittest.mock import patch

import pytest

from agenticops.auth.actor import Actor, agent_actor, cli_actor
from agenticops.models import Base, ChangeRequest, CloudAccount, CloudResource, FixExecution, FixPlan, get_session

ALICE = Actor("user", "alice", user_id=1, permissions=("read", "write"))
BOB = Actor("user", "bob", user_id=2, permissions=("read", "write"))


@pytest.fixture
def db(tmp_path):
    import agenticops.models as models_mod
    import agenticops.audit.models  # noqa: F401
    from agenticops.config import settings
    models_mod._engine = None
    settings.database_url = f"sqlite:///{tmp_path}/exec.db"
    Base.metadata.create_all(models_mod.get_engine())
    s = get_session()
    acct = CloudAccount(name="dev", provider="aws", is_enabled=True, credentials={}, regions=["ap-southeast-1"])
    s.add(acct); s.flush()
    s.add(CloudResource(account_id=acct.id, provider="aws", region="ap-southeast-1", resource_type="EC2Instance", resource_id="i-0abc", name="web"))
    s.commit()
    yield s
    s.close()
    models_mod._engine = None


def _planned(db, requester=ALICE):
    """A CR in 'planned' with a pending_approval change plan (the state after a positive review)."""
    from agenticops.services import change_service as cs
    with patch.object(cs, "notify_change_requested"):
        cr = cs.create_change_request(source="web", actor=requester, title="tag", description="add Env=prod",
                                      account_name="dev", targets=["i-0abc"], start_review=False)
    with cs._session() as s:
        cs.transition_change(s.get(ChangeRequest, cr["id"]), "under_review")
    cs.ground_targets(cr["id"])
    plan = FixPlan(plan_kind="change", change_request_id=cr["id"], risk_level="L1", title="p", summary="s",
                   steps=[{"action": "tag", "command": "aws ec2 create-tags"}], rollback_plan={"steps": ["aws ec2 delete-tags"]},
                   post_checks=[{"check": "tag present", "command": "aws ec2 describe-tags"}], status="draft")
    db.add(plan); db.commit()
    with patch.object(cs, "notify_change_pending_approval"):
        cs.submit_review(cr["id"], verdict="approved_for_planning", risk_level="L1", action_type="tag", reasons=["ok"], actor=agent_actor("sre"))
    return cr["id"], plan.id


def _audits(db, action):
    from agenticops.audit.models import AuditLog
    return db.query(AuditLog).filter_by(action=action).all()


class TestApproveRejectCancel:
    def test_approve_binds_actor_and_reason(self, db):
        from agenticops.services import change_service as cs
        cr_id, plan_id = _planned(db)
        out = cs.approve(cr_id, actor=BOB, reason="reviewed, low risk")
        assert out["status"] == "approved" and out["approved_by"] == "user:bob" and out["approval_reason"] == "reviewed, low risk"
        db.expire_all()
        assert db.get(FixPlan, plan_id).status == "approved" and db.get(FixPlan, plan_id).approved_by == "user:bob"
        assert len(_audits(db, "change.approved")) == 1

    def test_approve_requires_reason(self, db):
        from agenticops.services import change_service as cs
        cr_id, _ = _planned(db)
        with pytest.raises(cs.ChangeValidationError):
            cs.approve(cr_id, actor=BOB, reason="  ")

    def test_sod_enforced_when_rbac_enforce(self, db):
        from agenticops.config import settings
        from agenticops.services import change_service as cs
        cr_id, _ = _planned(db, requester=ALICE)
        with patch.object(settings, "rbac_enforce", True):
            with pytest.raises(cs.ChangeForbidden):
                cs.approve(cr_id, actor=ALICE, reason="self")
        assert len(_audits(db, "authz.denied")) == 1
        with patch.object(settings, "rbac_enforce", False):
            out = cs.approve(cr_id, actor=ALICE, reason="self, shadow mode")  # allowed, audited as shadow
        assert out["status"] == "approved" and len(_audits(db, "authz.denied_shadow")) == 1

    def test_approve_wrong_state_409(self, db):
        from agenticops.services import change_service as cs
        cr_id, _ = _planned(db)
        cs.approve(cr_id, actor=BOB, reason="ok")
        with pytest.raises(cs.ChangeStateError):
            cs.approve(cr_id, actor=BOB, reason="again")

    def test_reject_and_cancel(self, db):
        from agenticops.services import change_service as cs
        cr_id, plan_id = _planned(db)
        with patch.object(cs, "notify_change_result") as notify:
            out = cs.reject(cr_id, actor=BOB, reason="not now")
        assert out["status"] == "rejected" and out["rejected_by"] == "user:bob" and out["rejection_reason"] == "not now"
        db.expire_all()
        assert db.get(FixPlan, plan_id).status == "rejected"
        notify.assert_called_once()
        cr2, plan2 = _planned(db)
        cs.approve(cr2, actor=BOB, reason="ok")
        out2 = cs.cancel(cr2, actor=ALICE, reason="changed my mind")
        assert out2["status"] == "cancelled"
        db.expire_all()
        assert db.get(FixPlan, plan2).status == "rejected"  # withdrawn
        assert len(_audits(db, "change.cancelled")) == 1

    def test_clarify_appends_and_restarts_review(self, db):
        from agenticops.services import change_service as cs
        with patch.object(cs, "notify_change_requested"):
            cr = cs.create_change_request(source="web", actor=ALICE, title="t", description="vague", start_review=False)
        with cs._session() as s:
            row = s.get(ChangeRequest, cr["id"])
            cs.transition_change(row, "under_review"); cs.transition_change(row, "needs_clarification")
        with patch.object(cs, "start_review") as sr:
            out = cs.clarify(cr["id"], actor=ALICE, message="the instance is i-0abc")
        assert "i-0abc" in out["description"] and "Clarification" in out["description"]
        sr.assert_called_once_with(cr["id"], sync=False)
        assert len(_audits(db, "change.clarified")) == 1


class TestExecution:
    def test_request_execution_enqueues_and_transitions(self, db):
        from agenticops.config import settings
        from agenticops.services import change_service as cs
        cr_id, plan_id = _planned(db)
        cs.approve(cr_id, actor=BOB, reason="ok")
        with patch.object(settings, "executor_enabled", True):
            out = cs.request_execution(cr_id, actor=BOB)
        ex = db.get(FixExecution, out["execution_id"])
        assert ex.status == "pending" and ex.fix_plan_id == plan_id and ex.executed_by == "user:bob"
        db.expire_all()
        assert db.get(FixPlan, plan_id).status == "executing" and out["change"]["status"] == "executing"
        assert len(_audits(db, "change.execution_started")) == 1

    def test_request_execution_requires_approved(self, db):
        from agenticops.services import change_service as cs
        cr_id, _ = _planned(db)
        with pytest.raises(cs.ChangeStateError):
            cs.request_execution(cr_id, actor=BOB)

    def test_request_execution_executor_disabled(self, db):
        from agenticops.config import settings
        from agenticops.services import change_service as cs
        cr_id, _ = _planned(db)
        cs.approve(cr_id, actor=BOB, reason="ok")
        with patch.object(settings, "executor_enabled", False):
            with pytest.raises(cs.ChangeStateError):
                cs.request_execution(cr_id, actor=BOB)


def _executing(db):
    from agenticops.config import settings
    from agenticops.services import change_service as cs
    cr_id, plan_id = _planned(db)
    cs.approve(cr_id, actor=BOB, reason="ok")
    with patch.object(settings, "executor_enabled", True):
        cs.request_execution(cr_id, actor=BOB)
    return cr_id, plan_id


class TestTerminalMapper:
    @pytest.mark.parametrize("status,results,expected", [
        ("succeeded", [{"check": "tag present", "status": "pass"}], "completed"),
        ("succeeded", [], "needs_review"),
        ("succeeded", [{"check": "tag present", "status": "fail"}], "needs_review"),
        ("failed", [], "failed"),
        ("rolled_back", [], "rolled_back"),
        ("aborted", [], "failed"),
    ])
    def test_mapping(self, db, status, results, expected):
        from agenticops.services import change_service as cs
        cr_id, plan_id = _executing(db)
        with patch.object(cs, "notify_change_result") as notify:
            out = cs.on_execution_result(plan_id, status, post_check_results=results)
        assert out["status"] == expected
        notify.assert_called_once()
        assert notify.call_args.args[1] == expected
        if expected in ("completed", "failed", "rolled_back"):
            assert out["closed_at"] is not None

    def test_non_change_plan_returns_none(self, db):
        from agenticops.models import HealthIssue, RCAResult
        from agenticops.services import change_service as cs
        issue = HealthIssue(title="t", description="d", severity="low", source="t", status="fix_approved", resource_id="r")
        db.add(issue); db.flush()
        rca = RCAResult(health_issue_id=issue.id, root_cause="x", confidence=0.9); db.add(rca); db.flush()
        plan = FixPlan(health_issue_id=issue.id, rca_result_id=rca.id, risk_level="L1", title="p", summary="s", status="executing")
        db.add(plan); db.commit()
        assert cs.on_execution_result(plan.id, "succeeded") is None

    def test_resolve_review_by_human(self, db):
        from agenticops.services import change_service as cs
        cr_id, plan_id = _executing(db)
        with patch.object(cs, "notify_change_result"):
            cs.on_execution_result(plan_id, "succeeded", post_check_results=[])
        out = cs.resolve_review(cr_id, actor=BOB, outcome="completed", reason="verified manually in console")
        assert out["status"] == "completed" and out["closed_at"] is not None
        assert _audits(db, "change.completed")[-1].details["resolved_by_human"] is True
        with pytest.raises(cs.ChangeValidationError):
            cs.resolve_review(cr_id, actor=BOB, outcome="maybe", reason="x")


def test_change_timeline_merges_events_and_audits(db):
    from agenticops.services import change_service as cs
    cr_id, _ = _planned(db)
    tl = cs.change_timeline(cr_id)
    kinds = {e["kind"] for e in tl}
    assert kinds == {"event", "audit"}
    assert tl == sorted(tl, key=lambda e: e["ts"])
    assert any(e["type"] == "change.requested" for e in tl) and any(e["type"] == "change_requested" for e in tl)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_change_service_execution.py -q`
Expected: FAIL — `AttributeError: ... 'approve'`

- [ ] **Step 3: 实现（追加到 `change_service.py`）**

```python
# ── Approval & execution ──────────────────────────────────────────────

def _require_reason(reason: Optional[str]) -> str:
    reason = (reason or "").strip()
    if not reason:
        raise ChangeValidationError("a reason is required")
    return reason[:2000]


def approve(cr_id: int, *, actor: Actor, reason: str) -> dict:
    reason = _require_reason(reason)
    with _session() as s:
        cr = _load(s, cr_id)
        _check(actor, "change.approve", subject=cr)
        if cr.status != "planned":
            raise ChangeStateError(f"ChangeRequest #{cr_id} is '{cr.status}', only planned requests can be approved")
        plan = active_plan_for(s, cr_id)
        if plan is None:
            raise ChangeStateError("no active change plan to approve")
        # optimistic lock — another approver may have raced us
        from sqlalchemy import update
        res = s.execute(update(ChangeRequest).where(ChangeRequest.id == cr_id, ChangeRequest.status == "planned")
                        .values(status="approved"))
        if res.rowcount == 0:
            raise ChangeStateError(f"ChangeRequest #{cr_id} changed state concurrently")
        # the ORM row still holds 'planned' in memory; the validator performs the audited transition
        _transition(cr, "approved")
        now = datetime.now(timezone.utc)
        cr.approved_by, cr.approver_user_id, cr.approved_at, cr.approval_reason = actor.key, actor.user_id, now, reason
        try:
            transition_plan(plan, "approved")
        except InvalidStatusTransition as e:
            raise ChangeStateError(str(e)) from e
        plan.approved_by, plan.approved_at = actor.key, now
        _audit(s, Actions.CHANGE_APPROVED, cr, actor,
               details={"reason": reason, "risk_level": cr.risk_level, "policy_rule": cr.policy_rule, "plan_id": plan.id},
               old_status="planned", new_status="approved")
        AuditService.log(Actions.PLAN_APPROVED, EntityTypes.FIX_PLAN, str(plan.id), actor=actor.key, user_id=actor.user_id,
                         details={"reason": reason, "plan_kind": "change", "change_request_id": cr_id},
                         old_values={"status": "pending_approval"}, new_values={"status": "approved"}, session=s)
        snap = to_dict(cr)
    _event(cr_id, "change_approved", "approval", detail={"reason": reason, "approved_by": actor.key}, actor=actor.key, trace_id=snap["trace_id"])
    return snap


def reject(cr_id: int, *, actor: Actor, reason: str) -> dict:
    reason = _require_reason(reason)
    with _session() as s:
        cr = _load(s, cr_id)
        _check(actor, "change.reject", subject=cr)
        old = cr.status
        if old not in ("planned",):
            raise ChangeStateError(f"ChangeRequest #{cr_id} is '{old}', only planned requests can be rejected (use cancel otherwise)")
        _transition(cr, "rejected")
        cr.rejected_by, cr.rejected_at, cr.rejection_reason = actor.key, datetime.now(timezone.utc), reason
        plan = active_plan_for(s, cr_id)
        if plan is not None:
            transition_plan(plan, "rejected")
            plan.rejected_by, plan.rejected_at, plan.rejection_reason = actor.key, datetime.now(timezone.utc), reason
        _audit(s, Actions.CHANGE_REJECTED, cr, actor, details={"reason": reason}, old_status=old, new_status="rejected")
        snap = to_dict(cr)
    _event(cr_id, "change_rejected", "approval", "rejected", detail={"reason": reason}, actor=actor.key, trace_id=snap["trace_id"])
    try:
        notify_change_result(snap, "rejected")
    except Exception:
        logger.debug("notify_change_result failed", exc_info=True)
    return snap


def cancel(cr_id: int, *, actor: Actor, reason: str) -> dict:
    reason = _require_reason(reason)
    with _session() as s:
        cr = _load(s, cr_id)
        _check(actor, "change.cancel", subject=cr)
        old = cr.status
        _transition(cr, "cancelled")  # validator allows draft / needs_clarification / planned / approved
        cr.rejected_by, cr.rejected_at, cr.rejection_reason = actor.key, datetime.now(timezone.utc), reason
        plan = active_plan_for(s, cr_id)
        if plan is not None and plan.status in ("draft", "pending_approval", "approved"):
            transition_plan(plan, "rejected")
            plan.rejected_by, plan.rejected_at, plan.rejection_reason = actor.key, datetime.now(timezone.utc), f"withdrawn: {reason}"
        _audit(s, Actions.CHANGE_CANCELLED, cr, actor, details={"reason": reason}, old_status=old, new_status="cancelled")
        snap = to_dict(cr)
    _event(cr_id, "change_cancelled", "approval", "cancelled", detail={"reason": reason}, actor=actor.key, trace_id=snap["trace_id"])
    return snap


def clarify(cr_id: int, *, actor: Actor, message: str) -> dict:
    message = (message or "").strip()
    if not message:
        raise ChangeValidationError("message is required")
    with _session() as s:
        cr = _load(s, cr_id)
        _check(actor, "change.request", subject=cr)
        if cr.status != "needs_clarification":
            raise ChangeStateError(f"ChangeRequest #{cr_id} is '{cr.status}', not awaiting clarification")
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        cr.description = f"{cr.description}\n\n--- Clarification ({stamp}, {actor.key}) ---\n{message[:4000]}"
        _audit(s, Actions.CHANGE_CLARIFIED, cr, actor, details={"message": message[:500]})
        snap = to_dict(cr)
    _event(cr_id, "change_clarified", "review", detail={"message": message[:500]}, actor=actor.key, trace_id=snap["trace_id"])
    start_review(cr_id, sync=False)
    return get_change(cr_id)


def request_execution(cr_id: int, *, actor: Actor) -> dict:
    """approved → executing; enqueue a FixExecution for the ExecutorService (the ONLY execution route for changes)."""
    from agenticops.models import FixExecution
    if not settings.executor_enabled:
        raise ChangeStateError("Executor is disabled (executor_enabled=false)")
    with _session() as s:
        cr = _load(s, cr_id)
        _check(actor, "change.execute", subject=cr)
        if cr.status != "approved":
            raise ChangeStateError(f"ChangeRequest #{cr_id} is '{cr.status}', only approved requests can be executed")
        plan = active_plan_for(s, cr_id)
        if plan is None or plan.status != "approved":
            raise ChangeStateError("no approved change plan to execute")
        from sqlalchemy import update
        res = s.execute(update(ChangeRequest).where(ChangeRequest.id == cr_id, ChangeRequest.status == "approved")
                        .values(status="executing"))
        if res.rowcount == 0:
            raise ChangeStateError(f"ChangeRequest #{cr_id} changed state concurrently")
        _transition(cr, "executing")
        transition_plan(plan, "executing")
        execution = FixExecution(fix_plan_id=plan.id, health_issue_id=None, status="pending", executed_by=actor.key)
        s.add(execution)
        s.flush()
        _audit(s, Actions.CHANGE_EXECUTION_STARTED, cr, actor, details={"plan_id": plan.id, "execution_id": execution.id},
               old_status="approved", new_status="executing")
        snap, plan_id, execution_id = to_dict(cr), plan.id, execution.id
    _event(cr_id, "execution_started", "execution", "started", detail={"plan_id": plan_id, "execution_id": execution_id, "executor": "agent:executor"},
           actor=actor.key, trace_id=snap["trace_id"])
    return {"execution_id": execution_id, "fix_plan_id": plan_id, "change": snap}


_PASS_VALUES = {"pass", "passed", "ok", "succeeded", "success", "true"}


def _post_checks_passed(post_checks: list, results: Optional[list]) -> Optional[bool]:
    """True = all pass, False = a failure, None = results missing/incomplete (→ needs_review)."""
    if not post_checks:
        return None
    results = results or []
    if len(results) < len(post_checks):
        return None
    for item in results:
        if isinstance(item, dict):
            status = item.get("status", item.get("result", item.get("passed")))
        else:
            status = item
        if str(status).lower() not in _PASS_VALUES:
            return False
    return True


def on_execution_result(fix_plan_id: int, execution_status: str, *, post_check_results: Optional[list] = None,
                        error: str = "") -> Optional[dict]:
    """The ONLY writer of completed / needs_review / failed / rolled_back. Deterministic; no LLM input."""
    with _session() as s:
        plan = s.get(FixPlan, fix_plan_id)
        if plan is None or plan.plan_kind != "change" or not plan.change_request_id:
            return None
        cr = _load(s, plan.change_request_id)
        if cr.status != "executing":
            logger.warning("on_execution_result: CR #%d is '%s', ignoring result %s", cr.id, cr.status, execution_status)
            return to_dict(cr)
        if execution_status == "succeeded":
            verdict = _post_checks_passed(list(plan.post_checks or []), post_check_results)
            new_status = "completed" if verdict is True else "needs_review"
            reason = "all post-checks passed" if verdict is True else (
                "post-check failed" if verdict is False else "post-check results missing or incomplete")
        elif execution_status == "rolled_back":
            new_status, reason = "rolled_back", error or "execution rolled back"
        else:  # failed | aborted | anything else
            new_status, reason = "failed", error or f"execution {execution_status}"
        _transition(cr, new_status)
        from agenticops.run_context import get_run_context
        actor_key = get_run_context().actor if get_run_context().actor != "system" else "agent:executor"
        action = {"completed": Actions.CHANGE_COMPLETED, "needs_review": Actions.CHANGE_NEEDS_REVIEW,
                  "failed": Actions.CHANGE_FAILED, "rolled_back": Actions.CHANGE_ROLLED_BACK}[new_status]
        AuditService.log(action, EntityTypes.CHANGE_REQUEST, str(cr.id), entity_name=cr.title, actor=actor_key,
                         details={"execution_status": execution_status, "reason": reason, "plan_id": fix_plan_id,
                                  "post_check_results": (post_check_results or [])[:20]},
                         old_values={"status": "executing"}, new_values={"status": new_status}, session=s)
        snap = to_dict(cr)
    _event(snap["id"], "execution_completed", "execution", new_status,
           detail={"plan_id": fix_plan_id, "execution_status": execution_status, "reason": reason}, actor=actor_key, trace_id=snap["trace_id"])
    try:
        notify_change_result(snap, new_status)
    except Exception:
        logger.debug("notify_change_result failed", exc_info=True)
    return snap


def resolve_review(cr_id: int, *, actor: Actor, outcome: str, reason: str) -> dict:
    """Human verdict on a needs_review change. A redo is a NEW change request — no re-run edge."""
    reason = _require_reason(reason)
    if outcome not in ("completed", "failed"):
        raise ChangeValidationError("outcome must be completed or failed")
    with _session() as s:
        cr = _load(s, cr_id)
        _check(actor, "change.approve", subject=cr)
        if cr.status != "needs_review":
            raise ChangeStateError(f"ChangeRequest #{cr_id} is '{cr.status}', not needs_review")
        _transition(cr, outcome)
        action = Actions.CHANGE_COMPLETED if outcome == "completed" else Actions.CHANGE_FAILED
        _audit(s, action, cr, actor, details={"reason": reason, "resolved_by_human": True},
               old_status="needs_review", new_status=outcome)
        snap = to_dict(cr)
    _event(cr_id, "change_review_resolved", "execution", outcome, detail={"reason": reason}, actor=actor.key, trace_id=snap["trace_id"])
    try:
        notify_change_result(snap, outcome)
    except Exception:
        logger.debug("notify_change_result failed", exc_info=True)
    return snap


def change_timeline(cr_id: int) -> list[dict]:
    """pipeline events ∪ audit_logs for one change, sorted by time; unified shape."""
    from agenticops.audit.models import AuditLog
    from agenticops.services.pipeline_events import get_timeline
    entries = [
        {"ts": e["created_at"], "kind": "event", "type": e["event_type"], "actor": e["actor"], "status": e["status"],
         "detail": e["detail"], "stage": e["stage"]}
        for e in get_timeline(change_request_id=cr_id)
    ]
    with _session() as s:
        for a in s.query(AuditLog).filter_by(entity_type=EntityTypes.CHANGE_REQUEST, entity_id=str(cr_id)).all():
            entries.append({"ts": a.timestamp.isoformat() if a.timestamp else None, "kind": "audit", "type": a.action,
                            "actor": a.actor or a.user_email or "system",
                            "status": (a.new_values or {}).get("status"), "detail": a.details, "stage": "audit"})
    return sorted(entries, key=lambda e: e["ts"] or "")
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_change_service_execution.py tests/test_change_service_review.py tests/test_change_service.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/agenticops/services/change_service.py tests/test_change_service_execution.py
git commit -m "feat(change): approve/reject/cancel/clarify, queued execution, deterministic terminal mapper, timeline"
```

---

### Task 6: `save_fix_plan` 支持 change 计划；`save_execution_result` / Executor 崩溃超时 接映射器；Executor 按 CR 账户解析 CLI

**Files:**
- Modify: `src/agenticops/tools/metadata_tools.py`（`save_fix_plan` :812-976、`get_approved_fix_plan` :1092-1136、`save_execution_result` :1138-1262、`mark_fix_executed` / `mark_fix_failed` 开头）
- Modify: `src/agenticops/services/executor_service.py`（`_mark_crashed` :189-202、`_mark_timed_out` :204-216）
- Modify: `src/agenticops/agents/executor_agent.py:186-199`
- Test: `tests/test_save_fix_plan_change.py`

**Interfaces:**
- Produces: `save_fix_plan(health_issue_id: int = 0, rca_result_id: int = 0, risk_level, title, summary, steps="[]", rollback_plan="{}", estimated_impact="", pre_checks="[]", post_checks="[]", plan_kind: str = "fix", change_request_id: int = 0)`；`plan_kind="change"` 时：`change_request_id` 必填且 CR 须为 under_review，忽略 issue/rca，**rollback_plan 与 post_checks 非空**否则返回错误文本，dedup 按 `change_request_id`（LOCKED 拒绝 / draft 就地更新 / 无则新建），不触发 `trigger_auto_approve`、不改 issue、不发 fix 通知（审批路由由 `submit_change_review` 负责），事件 `fix_plan_created|updated` 记到 CR。`get_approved_fix_plan` JSON 增 `plan_kind`、`change_request_id`。`save_execution_result(health_issue_id: Optional[int] = None, ...)` 对 change 计划：不动 issue、不发 fix 通知、事件按 CR、调用 `change_service.on_execution_result(plan.id, status, post_check_results=..., error=...)`。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_save_fix_plan_change.py
import json
from unittest.mock import patch

import pytest

from agenticops.auth.actor import Actor
from agenticops.models import Base, ChangeRequest, CloudAccount, FixExecution, FixPlan, PipelineEvent, get_session


@pytest.fixture
def db(tmp_path):
    import agenticops.models as models_mod
    import agenticops.audit.models  # noqa: F401
    from agenticops.config import settings
    models_mod._engine = None
    settings.database_url = f"sqlite:///{tmp_path}/sfp.db"
    Base.metadata.create_all(models_mod.get_engine())
    s = get_session()
    s.add(CloudAccount(name="dev", provider="aws", is_enabled=True, credentials={}, regions=[])); s.commit()
    yield s
    s.close()
    models_mod._engine = None


def _cr_under_review(db):
    from agenticops.services import change_service as cs
    with patch.object(cs, "notify_change_requested"):
        cr = cs.create_change_request(source="web", actor=Actor("user", "a", 1, ("read", "write")), title="t",
                                      description="d", account_name="dev", start_review=False)
    with cs._session() as s:
        cs.transition_change(s.get(ChangeRequest, cr["id"]), "under_review")
    return cr["id"]


GOOD = dict(risk_level="L1", title="tag", summary="s", steps=json.dumps([{"action": "tag", "command": "aws ec2 create-tags"}]),
            rollback_plan=json.dumps({"steps": ["aws ec2 delete-tags"]}), post_checks=json.dumps([{"check": "present", "command": "aws ec2 describe-tags"}]))


def test_change_plan_created_and_dedup_updates_draft(db):
    from agenticops.tools.metadata_tools import save_fix_plan
    cr_id = _cr_under_review(db)
    out = save_fix_plan(plan_kind="change", change_request_id=cr_id, **GOOD)
    assert "saved" in out and "ChangeRequest" in out
    plan = db.query(FixPlan).one()
    assert plan.plan_kind == "change" and plan.change_request_id == cr_id and plan.health_issue_id is None and plan.status == "draft"
    out2 = save_fix_plan(plan_kind="change", change_request_id=cr_id, **{**GOOD, "title": "tag v2"})
    assert "UPDATED" in out2 and db.query(FixPlan).count() == 1
    ev = [e.event_type for e in db.query(PipelineEvent).filter_by(change_request_id=cr_id)]
    assert "fix_plan_created" in ev and "fix_plan_updated" in ev


def test_change_plan_requires_rollback_and_post_checks(db):
    from agenticops.tools.metadata_tools import save_fix_plan
    cr_id = _cr_under_review(db)
    out = save_fix_plan(plan_kind="change", change_request_id=cr_id, **{**GOOD, "rollback_plan": "{}"})
    assert "rollback_plan" in out and db.query(FixPlan).count() == 0
    out = save_fix_plan(plan_kind="change", change_request_id=cr_id, **{**GOOD, "post_checks": "[]"})
    assert "post_checks" in out and db.query(FixPlan).count() == 0


def test_change_plan_requires_under_review(db):
    from agenticops.tools.metadata_tools import save_fix_plan
    from agenticops.services import change_service as cs
    with patch.object(cs, "notify_change_requested"):
        cr = cs.create_change_request(source="web", actor=Actor("user", "a", 1, ("read", "write")), title="t", description="d", start_review=False)
    out = save_fix_plan(plan_kind="change", change_request_id=cr["id"], **GOOD)
    assert "under_review" in out and db.query(FixPlan).count() == 0


def test_change_plan_does_not_trigger_fix_auto_approve(db):
    from agenticops.tools.metadata_tools import save_fix_plan
    cr_id = _cr_under_review(db)
    with patch("agenticops.services.pipeline_service.trigger_auto_approve") as auto, \
         patch("agenticops.services.notification_service.notify_fix_planned") as notify:
        save_fix_plan(plan_kind="change", change_request_id=cr_id, **GOOD)
    assert not auto.called and not notify.called


def test_fix_plan_path_unchanged(db):
    from agenticops.models import HealthIssue, RCAResult
    from agenticops.tools.metadata_tools import save_fix_plan
    issue = HealthIssue(title="t", description="d", severity="low", source="t", status="root_cause_identified", resource_id="r")
    db.add(issue); db.flush()
    rca = RCAResult(health_issue_id=issue.id, root_cause="x", confidence=0.9); db.add(rca); db.commit()
    with patch("agenticops.services.pipeline_service.trigger_auto_approve") as auto:
        out = save_fix_plan(health_issue_id=issue.id, rca_result_id=rca.id, **GOOD)
    assert "saved" in out and auto.called
    assert db.query(FixPlan).one().plan_kind == "fix"


def test_get_approved_fix_plan_reports_kind_and_accepts_executing(db):
    from agenticops.tools.metadata_tools import get_approved_fix_plan
    cr_id = _cr_under_review(db)
    plan = FixPlan(plan_kind="change", change_request_id=cr_id, risk_level="L1", title="p", summary="s", status="approved",
                   rollback_plan={"x": 1}, post_checks=[{"check": "c"}])
    db.add(plan); db.commit()
    data = json.loads(get_approved_fix_plan(plan.id))
    assert data["plan_kind"] == "change" and data["change_request_id"] == cr_id and data["health_issue_id"] is None
    plan.status = "executing"; db.commit()
    assert json.loads(get_approved_fix_plan(plan.id))["status"] == "executing"  # queued route: already claimed
    plan.status = "draft"; db.commit()
    assert get_approved_fix_plan(plan.id).startswith("REJECTED")


def test_save_execution_result_for_change_calls_mapper(db):
    from agenticops.tools.metadata_tools import save_execution_result
    cr_id = _cr_under_review(db)
    with get_session() as s:
        pass
    plan = FixPlan(plan_kind="change", change_request_id=cr_id, risk_level="L1", title="p", summary="s", status="executing",
                   rollback_plan={"x": 1}, post_checks=[{"check": "c"}])
    db.add(plan); db.commit()
    with patch("agenticops.services.change_service.on_execution_result", return_value={"status": "completed"}) as mapper, \
         patch("agenticops.services.notification_service.notify_execution_result") as fix_notify:
        out = save_execution_result(fix_plan_id=plan.id, health_issue_id=None, status="succeeded",
                                    post_check_results=json.dumps([{"check": "c", "status": "pass"}]))
    assert "FixExecution #" in out
    mapper.assert_called_once()
    assert mapper.call_args.args == (plan.id, "succeeded")
    assert mapper.call_args.kwargs["post_check_results"] == [{"check": "c", "status": "pass"}]
    assert not fix_notify.called
    db.expire_all()
    assert db.get(FixPlan, plan.id).status == "executed"
    ev = db.query(PipelineEvent).filter_by(change_request_id=cr_id, event_type="execution_completed").count()
    assert ev == 1


def test_executor_service_crash_calls_mapper(db):
    from agenticops.services.executor_service import ExecutorService
    cr_id = _cr_under_review(db)
    plan = FixPlan(plan_kind="change", change_request_id=cr_id, risk_level="L1", title="p", summary="s", status="executing",
                   rollback_plan={"x": 1}, post_checks=[{"check": "c"}])
    db.add(plan); db.flush()
    ex = FixExecution(fix_plan_id=plan.id, status="running", executed_by="u"); db.add(ex); db.commit()
    with patch("agenticops.services.change_service.on_execution_result") as mapper:
        ExecutorService()._mark_crashed(ex.id, plan.id, "boom")
    mapper.assert_called_once_with(plan.id, "failed", error="Agent crashed: boom")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_save_fix_plan_change.py -q`
Expected: FAIL — `TypeError: save_fix_plan() got an unexpected keyword argument 'plan_kind'`

- [ ] **Step 3: `save_fix_plan`**

签名改为（docstring 加两个 Args 说明与一句 "For change requests pass plan_kind='change' and change_request_id (health_issue_id/rca_result_id are ignored). Change plans MUST include a non-empty rollback_plan and post_checks."）：

```python
@tool
def save_fix_plan(
    health_issue_id: int = 0,
    rca_result_id: int = 0,
    risk_level: str = "L1",
    title: str = "",
    summary: str = "",
    steps: str = "[]",
    rollback_plan: str = "{}",
    estimated_impact: str = "",
    pre_checks: str = "[]",
    post_checks: str = "[]",
    plan_kind: str = "fix",
    change_request_id: int = 0,
) -> str:
```

JSON 解析之后、`session = get_session()` 之前加分支：

```python
    if plan_kind not in ("fix", "change"):
        return "Invalid plan_kind. Must be 'fix' or 'change'."
    if plan_kind == "change":
        return _save_change_plan(change_request_id, risk_level, title, summary, steps_parsed, rollback_parsed,
                                 estimated_impact, pre_parsed, post_parsed)
    if not health_issue_id or not rca_result_id:
        return "health_issue_id and rca_result_id are required for plan_kind='fix'."
```

新增模块级函数（放在 `save_fix_plan` 之后）：

```python
def _save_change_plan(change_request_id, risk_level, title, summary, steps, rollback, impact, pre, post) -> str:
    """Change plans: no issue/RCA, dedup per change request, rollback + post_checks mandatory,
    NO auto-approve here (submit_change_review routes approval)."""
    from agenticops.models import (
        FIXPLAN_LOCKED_STATUSES, FIXPLAN_REPLACEABLE_STATUSES, FIXPLAN_TERMINAL_STATUSES, ChangeRequest,
    )
    if not change_request_id:
        return "change_request_id is required for plan_kind='change'."
    if not rollback or (isinstance(rollback, dict) and not any(v for v in rollback.values())):
        return "Change plans require a non-empty rollback_plan (how to undo the change)."
    if not post:
        return "Change plans require non-empty post_checks (commands that PROVE the change took effect)."
    session = get_session()
    try:
        cr = session.get(ChangeRequest, change_request_id)
        if cr is None:
            return f"ChangeRequest #{change_request_id} not found."
        if cr.status != "under_review":
            return f"ChangeRequest #{change_request_id} is '{cr.status}', not under_review — a plan can only be saved during review."
        existing = (
            session.query(FixPlan)
            .filter_by(change_request_id=change_request_id, plan_kind="change")
            .filter(FixPlan.status.notin_(FIXPLAN_TERMINAL_STATUSES))
            .order_by(FixPlan.created_at.desc())
            .first()
        )
        if existing and existing.status in FIXPLAN_LOCKED_STATUSES:
            return f"ChangeRequest #{change_request_id} already has plan #{existing.id} in '{existing.status}'."
        is_update = bool(existing and existing.status in FIXPLAN_REPLACEABLE_STATUSES)
        if is_update:
            plan = existing
            plan.risk_level, plan.title, plan.summary = risk_level, title, summary
            plan.steps, plan.rollback_plan, plan.estimated_impact = steps, rollback, impact
            plan.pre_checks, plan.post_checks = pre, post
            plan.updated_at = datetime.now(timezone.utc)
            event_type = "fix_plan_updated"
        else:
            plan = FixPlan(plan_kind="change", change_request_id=change_request_id, risk_level=risk_level, title=title,
                           summary=summary, steps=steps, rollback_plan=rollback, estimated_impact=impact,
                           pre_checks=pre, post_checks=post, status="draft")
            session.add(plan)
            event_type = "fix_plan_created"
        session.commit()
        try:
            from agenticops.services.pipeline_events import log_event
            log_event(None, event_type, "planning", detail={"plan_id": plan.id, "risk_level": risk_level, "plan_kind": "change"},
                      actor="agent:sre", change_request_id=change_request_id)
        except Exception:
            pass
        action = "UPDATED" if is_update else "saved"
        return (f"Change plan #{plan.id} {action} for ChangeRequest #{change_request_id} (risk {risk_level}). "
                f"Now call submit_change_review to deliver your verdict.")
    except Exception as e:
        session.rollback()
        return f"Error saving change plan: {e}"
    finally:
        session.close()
```

- [ ] **Step 4: `get_approved_fix_plan` / `save_execution_result` / `mark_fix_*`**

`get_approved_fix_plan` 的 JSON 加 `"plan_kind": plan.plan_kind, "change_request_id": plan.change_request_id`（放在 `health_issue_id` 之后）。**同时把门的判断从 `plan.status != "approved"` 改为 `plan.status not in ("approved", "executing")`**——队列路线（`POST /execute`、CLI `/execute`、`change_service.request_execution`）在入队时已把计划标为 `executing`，而 `executing` 只能从 `approved` 经校验器到达，所以安全等价；这是修一个既有 bug（今天队列路线里 Executor 第一步就会被自己的门拒绝），不是放松门。REJECTED 文案改为 "status is '{status}', not approved/executing"。

`save_execution_result`：签名 `health_issue_id: Optional[int] = None`（`from typing import Optional` 若缺）；在守卫之后取 `is_change = plan.plan_kind == "change"`；`FixExecution(..., health_issue_id=health_issue_id if not is_change else None)`；auto-resolve 块加 `and not is_change`；事件块改为：

```python
        try:
            from agenticops.services.pipeline_events import log_event
            detail = {"plan_id": fix_plan_id, "duration_ms": duration_ms, "auto_resolved": auto_resolved}
            if is_change:
                log_event(None, "execution_completed", "execution", status, detail=detail, duration_ms=duration_ms,
                          change_request_id=plan.change_request_id)
            else:
                log_event(health_issue_id, "execution_completed", "execution", status, detail=detail, duration_ms=duration_ms)
        except Exception:
            pass
```

通知块：`if is_change:` → `from agenticops.services.change_service import on_execution_result; on_execution_result(fix_plan_id, status, post_check_results=_parse_json(post_check_results, []), error=error_message)`（用局部变量 `plan_id_val = plan.id` 在 commit 前捕获）；`else:` 原有 `notify_execution_result` + `notify_im_origin`。`trigger_post_resolution` 只在 `auto_resolved`（fix）时。返回文案在 change 时不提 HealthIssue。

`mark_fix_executed` / `mark_fix_failed` 开头加：`if not health_issue_id: return "This is a change plan (no HealthIssue); nothing to mark — the change request state is derived from save_execution_result."`（签名 `health_issue_id: Optional[int]`）。

- [ ] **Step 5: `executor_service` 崩溃/超时 + `executor_agent` 账户**

`_mark_crashed`：在 `transition_plan(plan, "failed")` 成功后、`session.commit()` 前记录 `is_change = plan.plan_kind == "change"`；commit 后 `if is_change: from agenticops.services.change_service import on_execution_result; on_execution_result(fix_plan_id, "failed", error=f"Agent crashed: {error[:500]}")`。`_mark_timed_out`：读 `execution.fix_plan_id` → plan；同样 `transition_plan(plan, "failed")`（原来这里不改 plan——补上）并对 change 调 `on_execution_result(plan_id, "failed", error=f"Execution timed out after {settings.executor_total_timeout}s")`。`tests/test_executor_service.py::test_mark_timed_out_updates_db` 的 mock plan 需要 `status="executing"`、`plan_kind="fix"`。

`executor_agent.py:186-199` 的账户解析改为：

```python
        cli_tool = None
        try:
            with get_db_session() as db:
                plan_for_acct = db.query(FixPlan).filter_by(id=fix_plan_id).first()
                account_id = None
                if plan_for_acct and plan_for_acct.health_issue_id:
                    issue = db.query(HealthIssue).filter_by(id=plan_for_acct.health_issue_id).first()
                    account_id = issue.account_id if issue else None
                elif plan_for_acct and plan_for_acct.change_request_id:
                    from agenticops.models import ChangeRequest
                    cr = db.get(ChangeRequest, plan_for_acct.change_request_id)
                    account_id = cr.account_id if cr else None
                if account_id:
                    cli_tool = get_cli_tool_for_issue(account_id)
        except Exception:
            pass
```

- [ ] **Step 6: 跑测试 + 回归 + Commit**

```bash
python -m pytest tests/test_save_fix_plan_change.py tests/test_sre_agent.py tests/test_fix_plan_consolidation.py tests/test_auto_fix_pipeline.py tests/test_executor_service.py tests/test_l4_e2e.py -q
python -m pytest tests/ -q --deselect tests/test_web_tools.py > /tmp/pytest-b6.log 2>&1; tail -5 /tmp/pytest-b6.log
git add src/agenticops/tools/metadata_tools.py src/agenticops/services/executor_service.py src/agenticops/agents/executor_agent.py tests/test_save_fix_plan_change.py tests/test_executor_service.py
git commit -m "feat(plans): change plans via save_fix_plan; execution results feed the change terminal mapper"
```

---

### Task 7: Agent 工具包 `tools/change_tools.py`（8 个薄包装）

**Files:**
- Create: `src/agenticops/tools/change_tools.py`
- Test: `tests/test_change_tools.py`

**Interfaces:**
- Produces（全部 `@tool`，返回文本/JSON 文本，**永不向 agent 抛异常**——`ChangeError` 转成可读文本）：
  - `request_change(title: str, description: str, account: str = "", targets: str = "", change_type: str = "normal", justification: str = "") -> str`（Main；`targets` 逗号分隔；source 由 Run Context actor 推导：user/web→`chat`、cli→`cli`、im→`im`、其他→`api`；返回含 `C#N`）
  - `get_change_request(change_request_id: int) -> str`（Main/SRE；JSON，含 `plan` 摘要）
  - `list_change_requests(status: str = "", limit: int = 20) -> str`（Main）
  - `execute_change(change_request_id: int) -> str`（Main；`request_execution`）
  - `ground_change_targets(change_request_id: int) -> str`（SRE；JSON）
  - `attach_change_target(change_request_id: int, resource_id: str, resource_type: str, region: str = "", hint: str = "") -> str`（SRE）
  - `evaluate_change_policy(change_request_id: int, risk_level: str, action_type: str) -> str`（SRE；JSON）
  - `submit_change_review(change_request_id: int, verdict: str, risk_level: str = "", action_type: str = "", reasons: str = "") -> str`（SRE；`reasons` 以 `;` 或换行分隔）
  - `_actor_from_context() -> Actor`（内部：Run Context actor，无上下文时 `agent:main`）

- [ ] **Step 1: 写失败测试**

```python
# tests/test_change_tools.py
import json
from unittest.mock import patch

import pytest

from agenticops.models import Base, ChangeRequest, CloudAccount, CloudResource, get_session
from agenticops.run_context import run_context


@pytest.fixture
def db(tmp_path):
    import agenticops.models as models_mod
    import agenticops.audit.models  # noqa: F401
    from agenticops.config import settings
    models_mod._engine = None
    settings.database_url = f"sqlite:///{tmp_path}/tools.db"
    Base.metadata.create_all(models_mod.get_engine())
    s = get_session()
    acct = CloudAccount(name="dev", provider="aws", is_enabled=True, credentials={}, regions=[]); s.add(acct); s.flush()
    s.add(CloudResource(account_id=acct.id, provider="aws", region="ap-southeast-1", resource_type="EC2Instance", resource_id="i-0abc", name="web"))
    s.commit()
    yield s
    s.close()
    models_mod._engine = None


def test_request_change_uses_context_actor_and_source(db):
    from agenticops.tools.change_tools import request_change
    with run_context(actor="user:alice", actor_user_id=1, chat_session_id="sess-1"), \
         patch("agenticops.services.change_service.start_review") as sr, \
         patch("agenticops.services.change_service.notify_change_requested"):
        out = request_change(title="Tag web", description="add Env=prod", account="dev", targets="i-0abc, i-0def")
    assert out.startswith("Change request C#")
    cr = db.query(ChangeRequest).one()
    assert cr.requested_by == "user:alice" and cr.source == "chat" and cr.chat_session_id == "sess-1"
    assert cr.target_hints == ["i-0abc", "i-0def"] and cr.status == "draft"
    sr.assert_not_called()  # in chat, Main calls review_change (sync) next — no async review here


def test_request_change_cli_source_and_errors(db):
    from agenticops.tools.change_tools import request_change
    with run_context(actor="cli:malibo"), patch("agenticops.services.change_service.start_review"), \
         patch("agenticops.services.change_service.notify_change_requested"):
        request_change(title="t", description="d")
        out = request_change(title="t", description="d", account="nope")
    assert db.query(ChangeRequest).one().source == "cli"
    assert "not found" in out  # ChangeValidationError rendered as text, not raised


def test_sre_tools_roundtrip(db):
    from agenticops.services import change_service as cs
    from agenticops.tools.change_tools import (
        attach_change_target, evaluate_change_policy, get_change_request, ground_change_targets, submit_change_review,
    )
    from agenticops.tools.metadata_tools import save_fix_plan
    with patch.object(cs, "notify_change_requested"):
        cr = cs.create_change_request(source="cli", actor=cs.Actor("cli", "m"), title="t", description="d",
                                      account_name="dev", targets=["i-0abc", "i-0def"], start_review=False)
    with cs._session() as s:
        cs.transition_change(s.get(ChangeRequest, cr["id"]), "under_review")
    with run_context(actor="agent:sre", change_request_id=cr["id"]):
        g = json.loads(ground_change_targets(cr["id"]))
        assert g["unresolved"] == ["i-0def"]
        with patch("agenticops.tools.aws_cli_tool._execute_aws_cli", return_value='{"Reservations":[{}]}'):
            assert "attached" in attach_change_target(cr["id"], "i-0def", "ec2:instance")
        d = json.loads(evaluate_change_policy(cr["id"], "L1", "tag"))
        assert d["action"] == "auto_approve"
        save_fix_plan(plan_kind="change", change_request_id=cr["id"], risk_level="L1", title="p", summary="s",
                      steps=json.dumps([{"action": "tag", "command": "aws ec2 create-tags"}]),
                      rollback_plan=json.dumps({"steps": ["aws ec2 delete-tags"]}),
                      post_checks=json.dumps([{"check": "present", "command": "aws ec2 describe-tags"}]))
        with patch.object(cs, "notify_change_pending_approval"):
            out = submit_change_review(cr["id"], "approved_for_planning", "L1", "tag", "single tag; low risk")
    assert "planned" in out
    data = json.loads(get_change_request(cr["id"]))
    assert data["status"] == "planned" and data["plan"]["status"] == "pending_approval" and data["review_reasons"][0] == "single tag"


def test_submit_review_error_is_text(db):
    from agenticops.tools.change_tools import submit_change_review
    out = submit_change_review(9999, "approved_for_planning", "L1", "tag", "x")
    assert "not found" in out


def test_execute_change_and_list(db):
    from agenticops.config import settings
    from agenticops.services import change_service as cs
    from agenticops.tools.change_tools import execute_change, list_change_requests
    with patch.object(cs, "request_execution", return_value={"execution_id": 7, "fix_plan_id": 3, "change": {"id": 1, "status": "executing"}}) as re:
        with run_context(actor="user:bob"):
            out = execute_change(1)
    assert "execution #7" in out.lower() and re.call_args.kwargs["actor"].key == "user:bob"
    with patch.object(cs, "notify_change_requested"):
        cs.create_change_request(source="cli", actor=cs.Actor("cli", "m"), title="t", description="d", start_review=False)
    rows = json.loads(list_change_requests())
    assert len(rows) == 1 and rows[0]["status"] == "draft"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_change_tools.py -q`
Expected: FAIL — `ModuleNotFoundError: agenticops.tools.change_tools`

- [ ] **Step 3: 实现**

```python
# src/agenticops/tools/change_tools.py
"""Change Management agent tools (MVP-2.6.0) — thin @tool wrappers over services.change_service.

Main agent: request_change, get_change_request, list_change_requests, execute_change.
SRE agent (Mode C): get_change_request, ground_change_targets, attach_change_target,
                    evaluate_change_policy, submit_change_review.
Every wrapper turns ChangeError into readable text — an agent must never see a traceback,
and none of these tools can write a terminal state (that is change_service.on_execution_result).
"""

from __future__ import annotations

import json
import logging

from strands import tool

from agenticops.auth.actor import Actor, parse_actor
from agenticops.config import settings
from agenticops.run_context import get_run_context
from agenticops.services import change_service as cs

logger = logging.getLogger(__name__)

_SOURCE_BY_KIND = {"user": "chat", "web": "chat", "cli": "cli", "im": "im", "webhook": "webhook"}


def _actor_from_context() -> Actor:
    ctx = get_run_context()
    if ctx.actor == "system":
        return Actor("agent", "main")
    a = parse_actor(ctx.actor)
    return Actor(a.kind, a.id, ctx.actor_user_id, a.permissions)


def _plan_summary(cr_id: int) -> dict | None:
    with cs._session() as s:
        plan = cs.active_plan_for(s, cr_id)
        if plan is None:
            from agenticops.models import FixPlan
            plan = (s.query(FixPlan).filter_by(change_request_id=cr_id, plan_kind="change")
                    .order_by(FixPlan.created_at.desc()).first())
        if plan is None:
            return None
        return {"id": plan.id, "status": plan.status, "risk_level": plan.risk_level, "title": plan.title,
                "steps": len(plan.steps or []), "has_rollback": bool(plan.rollback_plan),
                "post_checks": len(plan.post_checks or [])}


@tool
def request_change(title: str, description: str, account: str = "", targets: str = "",
                   change_type: str = "normal", justification: str = "") -> str:
    """Open a CHANGE REQUEST (ITSM change) for a modification the user asks for — tagging, scaling,
    configuration, network or IAM changes that are NOT fixing an incident.

    USE FOR: "add tag", "change/modify/update <resource>", "scale", "变更", "change request", "CR",
    or any write intent without a HealthIssue. NOT FOR: incident fixes (sre_agent with an issue id).
    After this, call review_change(change_request_id) so the SRE reviews it in the same turn.

    Args:
        title: Short title (<= 300 chars).
        description: What to change and why, in the user's words (include resource ids / names).
        account: Registered account name; omit for single-account deployments.
        targets: Comma-separated resource ids / ARNs / names the change touches.
        change_type: normal (default) or emergency.
        justification: Business reason, if the user gave one.

    Returns:
        Confirmation with the change reference C#N, or the reason it could not be opened.
    """
    actor = _actor_from_context()
    ctx = get_run_context()
    hints = [t.strip() for t in (targets or "").split(",") if t.strip()]
    try:
        cr = cs.create_change_request(
            source=_SOURCE_BY_KIND.get(actor.kind, "api"), actor=actor, title=title, description=description,
            account_name=account or None, targets=hints, requested_change_type=(change_type or "normal").lower(),
            justification=justification or "", chat_session_id=ctx.chat_session_id, start_review=False,
        )
    except cs.ChangeError as e:
        return f"Change request could not be opened: {e}"
    # The review is NOT started here: in chat the Main agent calls review_change (sync) right after this,
    # which would otherwise race an async review. Web/CLI intakes start their own review.
    return (f"Change request C#{cr['id']} opened ({cr['requested_change_type']}, requested by {cr['requested_by']}, "
            f"targets: {', '.join(hints) or 'none given'}). Next: call review_change({cr['id']}) to run the SRE review.")


@tool
def get_change_request(change_request_id: int) -> str:
    """Get a change request (C#N) with its current plan summary. Args: change_request_id: The C# number."""
    try:
        data = cs.get_change(change_request_id)
    except cs.ChangeError as e:
        return str(e)
    data["plan"] = _plan_summary(change_request_id)
    return json.dumps(data, default=str)[:6000]


@tool
def list_change_requests(status: str = "", limit: int = 20) -> str:
    """List change requests, newest first. Args: status: optional filter (draft, under_review, planned, approved, executing, needs_review, completed, failed, rolled_back, rejected, cancelled). limit: max rows."""
    rows = cs.list_changes(status=status or None, limit=max(1, min(int(limit or 20), 100)))
    slim = [{k: r[k] for k in ("id", "title", "status", "risk_level", "effective_change_type", "requested_by", "created_at")} for r in rows]
    return json.dumps(slim, default=str)[:6000]


@tool
def execute_change(change_request_id: int) -> str:
    """Queue execution of an APPROVED change request (C#N). Confirm with the user first.
    SAFETY: only approved changes run; the Executor works from the approved plan. Args: change_request_id: The C# number."""
    try:
        out = cs.request_execution(change_request_id, actor=_actor_from_context())
    except cs.ChangeError as e:
        return f"Cannot execute C#{change_request_id}: {e}"
    return (f"Execution #{out['execution_id']} queued for change C#{change_request_id} (plan #{out['fix_plan_id']}). "
            f"The Executor picks it up within {settings.executor_poll_interval}s.")


@tool
def ground_change_targets(change_request_id: int) -> str:
    """SRE Mode C step 2: match the request's target hints against the inventory. Returns grounded targets
    and the UNRESOLVED hints — verify those with read-only describe calls, then attach_change_target them,
    or return verdict needs_clarification. Args: change_request_id: The C# number."""
    try:
        return json.dumps(cs.ground_targets(change_request_id), default=str)[:6000]
    except cs.ChangeError as e:
        return str(e)


@tool
def attach_change_target(change_request_id: int, resource_id: str, resource_type: str, region: str = "", hint: str = "") -> str:
    """SRE Mode C: attach a target that is NOT in the inventory. The platform itself runs a read-only
    describe for it (fail-closed: not found = not attached). resource_type is one of ec2:instance,
    ec2:security-group, ec2:subnet, ec2:vpc, ec2:volume, rds:db, eks:cluster, s3:bucket, lambda:function,
    autoscaling:group, elbv2:load-balancer — or pass the resource ARN as resource_id with any type.

    Args:
        change_request_id: The C# number.
        resource_id: Resource id or ARN.
        resource_type: Type key from the list above.
        region: Region for the describe call (omit for the account default).
        hint: The requester's original wording this target resolves (e.g. a name); defaults to resource_id."""
    try:
        item = cs.attach_target(change_request_id, resource_id, resource_type, actor=_actor_from_context(), region=region, hint=hint)
    except cs.ChangeError as e:
        return f"Target not attached: {e}"
    return f"Target {item['resource_id']} ({item['resource_type']}) attached to C#{change_request_id} (verified by: {item['evidence']['command']})."


@tool
def evaluate_change_policy(change_request_id: int, risk_level: str, action_type: str) -> str:
    """SRE Mode C step 4: deterministic policy decision (config/policies.yaml) for this change at the
    given risk (L0-L3) and action_type (tag|scale|config|network|iam|delete|other). 'block' means you
    must return verdict rejected. Args: change_request_id, risk_level, action_type."""
    try:
        d = cs.evaluate_policy(change_request_id, risk_level.upper(), action_type.lower())
    except cs.ChangeError as e:
        return str(e)
    return json.dumps(d.to_dict())


@tool
def submit_change_review(change_request_id: int, verdict: str, risk_level: str = "", action_type: str = "",
                         reasons: str = "") -> str:
    """SRE Mode C final step: deliver your verdict. verdict is approved_for_planning (requires the change
    plan you saved with save_fix_plan(plan_kind='change'), plus risk_level and action_type),
    needs_clarification (targets could not be verified / request ambiguous) or rejected.

    Args:
        change_request_id: The C# number.
        verdict: approved_for_planning | needs_clarification | rejected.
        risk_level: L0-L3 (required for approved_for_planning).
        action_type: tag | scale | config | network | iam | delete | other (required for approved_for_planning).
        reasons: Your reasons, separated by ';' or newlines."""
    parts = [p.strip() for p in (reasons or "").replace("\n", ";").split(";") if p.strip()]
    try:
        out = cs.submit_review(change_request_id, verdict=verdict.strip().lower(),
                               risk_level=(risk_level or "").upper() or None, action_type=(action_type or "").lower() or None,
                               reasons=parts, actor=_actor_from_context())
    except cs.ChangeError as e:
        return f"Verdict not accepted: {e}"
    return (f"Verdict recorded for C#{change_request_id}: status is now '{out['status']}'"
            + (f", effective change type {out['effective_change_type']}, policy {out['policy_rule']}→{out['policy_action']}"
               if out.get("policy_rule") else "") + ".")
```

- [ ] **Step 4: 跑测试 + Commit**

```bash
python -m pytest tests/test_change_tools.py -q
git add src/agenticops/tools/change_tools.py tests/test_change_tools.py
git commit -m "feat(tools): change management agent tools (request/review/execute wrappers over change_service)"
```

---

### Task 8: SRE Mode C（变更审核协议）+ `sre_agent_review_change` + `review_change` 工具

**Files:**
- Modify: `src/agenticops/agents/sre_agent.py`（提示词 :77-83 开头三行、MODE B 之后插入 MODE C；`_create_sre_agent` 工具列表 :220-274；新增两个函数）
- Modify: `tests/test_prompt_budget.py`（`BASE_PROMPT_GOLDENS["sre"]` 按实际值重设；`TestRoutingDocstrings.CASES` 加 `review_change`）
- Test: `tests/test_sre_change_review.py`

**Interfaces:**
- Produces: `sre_agent_review_change(change_request_id: int) -> str`（构建 SRE agent（CLI 工具按 CR 账户解析）并以 Mode C 调用提示运行；不做状态迁移——那是 `change_service.start_review`）；`@tool review_change(change_request_id: int) -> str`（Main 用：`change_service.start_review(cr_id, sync=True)`，`ChangeError` → 文本）。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_sre_change_review.py
from unittest.mock import MagicMock, patch


def test_prompt_has_mode_c_and_stays_english():
    from agenticops.agents.sre_agent import SRE_SYSTEM_PROMPT
    assert "MODE C" in SRE_SYSTEM_PROMPT and "CHANGE REVIEW PROTOCOL" in SRE_SYSTEM_PROMPT
    for kw in ("ground_change_targets", "attach_change_target", "evaluate_change_policy", "submit_change_review",
               "plan_kind='change'", "needs_clarification", "rollback"):
        assert kw in SRE_SYSTEM_PROMPT
    assert "THREE modes" in SRE_SYSTEM_PROMPT


def test_sre_tool_list_includes_change_tools():
    from agenticops.agents import sre_agent as mod
    captured = {}

    class FakeAgent:
        def __init__(self, **kw):
            captured["tools"] = kw["tools"]

    with patch.object(mod, "Agent", FakeAgent), patch.object(mod, "BedrockModel", MagicMock()), \
         patch("agenticops.config.get_agent_model_config", return_value=("m", 100)), \
         patch("agenticops.config.get_agent_conversation_manager", return_value=None), \
         patch("agenticops.config.get_agent_context_manager", return_value=None), \
         patch("agenticops.config.get_bedrock_boto_session", return_value=None), \
         patch("agenticops.agents.preamble.bedrock_model_kwargs", return_value={}), \
         patch.object(mod, "build_system_prompt", return_value="p"):
        mod._create_sre_agent()
    names = {getattr(t, "__name__", None) or getattr(t, "tool_name", None) or str(t) for t in captured["tools"]}
    for n in ("ground_change_targets", "attach_change_target", "evaluate_change_policy", "submit_change_review", "get_change_request"):
        assert any(n in str(x) for x in names), n


def test_sre_agent_review_change_invokes_agent_with_mode_c_prompt():
    from agenticops.agents import sre_agent as mod
    fake_agent = MagicMock()
    with patch.object(mod, "_create_sre_agent", return_value=fake_agent) as create, \
         patch("agenticops.agents.preamble.invoke_with_retry", return_value="verdict delivered") as invoke, \
         patch("agenticops.services.change_service.get_change", return_value={"id": 5, "account_id": None}):
        out = mod.sre_agent_review_change(5)
    assert out == "verdict delivered"
    prompt = invoke.call_args.args[1]
    assert "ChangeRequest #5" in prompt and "MODE C" in prompt
    create.assert_called_once()


def test_review_change_tool_wraps_start_review():
    from agenticops.agents.sre_agent import review_change
    with patch("agenticops.services.change_service.start_review", return_value="reviewed text") as sr:
        assert review_change(7) == "reviewed text"
    sr.assert_called_once_with(7, sync=True)
    from agenticops.services import change_service as cs
    with patch("agenticops.services.change_service.start_review", side_effect=cs.ChangeStateError("is 'planned'")):
        assert "planned" in review_change(7)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_sre_change_review.py -q`
Expected: FAIL — `assert "MODE C" in SRE_SYSTEM_PROMPT`

- [ ] **Step 3: 提示词**

`SRE_SYSTEM_PROMPT` 开头改为：

```
You are the SRE Agent for AgenticOps.
You have THREE modes of operation:
  A) Fix Plan generation — structured plans from RCA results.
  B) General AWS investigation — answer any question about AWS resources and
     infrastructure using your tools and the AWS CLI.
  C) Change review — review a human's CHANGE REQUEST (C#N) for legitimacy and
     produce the change plan the Executor will run after approval.
You are READ-ONLY — you NEVER execute fixes or modify AWS resources.
```

在 `MODE B` 段落结束（`4. RESPOND: ...` 行）之后、`RULES & GUARDRAILS` 之前插入：

```
MODE C — CHANGE REVIEW PROTOCOL (ChangeRequest C#N; you decide legitimacy, the platform decides state):
1. READ: get_change_request(N) — intent, targets (target_hints), account, requested type (normal|emergency).
2. GROUND: ground_change_targets(N). For every UNRESOLVED hint run a read-only describe yourself; if
   the resource exists call attach_change_target(N, resource_id, resource_type, region) — the platform
   re-verifies it. If any target cannot be verified, STOP and submit verdict needs_clarification listing
   the unresolved targets. Never invent ids.
3. ASSESS: risk L0-L3 with the Mode A rubric (a tag update is L1; SG rules / resize are L2; restart,
   failover, data migration, node drain are L3) and action_type tag|scale|config|network|iam|delete|other.
4. POLICY: evaluate_change_policy(N, risk, action_type). Action 'block' → verdict rejected (quote the rule).
5. PLAN: save_fix_plan(plan_kind='change', change_request_id=N, risk_level, title, summary, steps,
   pre_checks, post_checks, rollback_plan, estimated_impact). MANDATORY: post_checks that PROVE the change
   took effect (e.g. describe-tags shows the tag) and a rollback_plan that undoes it exactly.
   Steps are exact CLI commands with real ids — the Executor runs them verbatim after approval.
6. VERDICT: submit_change_review(N, verdict, risk_level, action_type, reasons). Verdicts:
   approved_for_planning | needs_clarification | rejected. The platform (not you) routes approval,
   applies the policy and writes every state — you only recommend.
```

（约 1,500 字符；SRE 基线金标从 9,700 上调到实际长度——运行 `python -c "from agenticops.agents.sre_agent import SRE_SYSTEM_PROMPT as p; print(len(p))"` 后把 `BASE_PROMPT_GOLDENS["sre"]` 设为该值四舍五入到百位。）

- [ ] **Step 4: 工具与入口**

import：`from agenticops.tools.change_tools import (get_change_request, ground_change_targets, attach_change_target, evaluate_change_policy, submit_change_review)`。`_create_sre_agent` 的 `_tools` 在 `save_fix_plan,` 之后加五个工具（注释 `# Change review (Mode C)`）。

新增（`sre_agent` 之后）：

```python
def sre_agent_review_change(change_request_id: int) -> str:
    """Run the SRE agent in Mode C for one change request (called by change_service.start_review).

    State transitions, watchdog and 'a review must end with a verdict' are enforced by change_service —
    this function only builds the agent (CLI tool resolved from the request's account) and runs it.
    """
    from agenticops.agents.preamble import infer_parent_agent, invoke_with_retry
    from agenticops.services import change_service as cs
    from agenticops.services.agent_log_service import track_agent

    cli_tool = None
    try:
        cr = cs.get_change(change_request_id)
        if cr.get("account_id"):
            cli_tool = get_cli_tool_for_issue(cr["account_id"])
    except Exception:
        pass
    agent = _create_sre_agent(cli_tool=cli_tool)
    with track_agent("sre", "change_review", f"change_request_id={change_request_id}", parent_agent=infer_parent_agent()) as tracker:
        result = invoke_with_retry(
            agent,
            f"Review ChangeRequest #{change_request_id}. Follow MODE C — CHANGE REVIEW PROTOCOL exactly: "
            f"read, ground every target (fail closed), assess risk and action_type, evaluate policy, save the change plan "
            f"with plan_kind='change' (post_checks + rollback_plan mandatory), then submit_change_review with your verdict.",
        )
        tracker.set_result(result)
    return str(result)


@tool
def review_change(change_request_id: int) -> str:
    """Review a CHANGE REQUEST (C#N) — legitimacy, risk, policy and the change plan.

    USE FOR: right after request_change, or "review change", "review CR", "change request" + C#N.
    READ-ONLY: never executes — the SRE grounds targets, classifies risk, evaluates policy and saves
    the plan; approval is a separate human step (Web Plans & Changes, or /approve C<N> in the CLI).
    NOT FOR: incident fix plans (sre_agent) or executing (execute_change).

    Args:
        change_request_id: The C# number returned by request_change.

    Returns:
        The SRE's review summary (verdict, risk, plan) or why the review could not start.
    """
    from agenticops.services import change_service as cs
    try:
        return cs.start_review(change_request_id, sync=True) or "Review finished."
    except cs.ChangeError as e:
        return f"Change review not started: {e}"
```

`tests/test_prompt_budget.py` 的 `CASES` 加 `"review_change": ("agenticops.agents.sre_agent", ["change request", "READ-ONLY", "C#"])`。

- [ ] **Step 5: 跑测试 + Commit**

```bash
python -m pytest tests/test_sre_change_review.py tests/test_prompt_budget.py tests/test_sre_agent.py -q
git add src/agenticops/agents/sre_agent.py tests/test_sre_change_review.py tests/test_prompt_budget.py
git commit -m "feat(sre): Mode C change review protocol, sre_agent_review_change, review_change tool"
```

---

### Task 9: Main agent 变更路由（规则 5.7、工具注入、`C#N`）+ 通知三点 + `C#N` 引用解析

**Files:**
- Modify: `src/agenticops/agents/main_agent.py`（imports、`MAIN_SYSTEM_PROMPT` 三处、`_build_agent` 工具列表）
- Modify: `src/agenticops/services/notification_service.py`（替换 Task 3 的三个桩）
- Modify: `src/agenticops/chat/preprocessor.py`（`CHANGE_REF_PATTERN`、`_resolve_change_ref`、`resolve_references`）、`src/agenticops/chat/reference_resolver.py`（`fetch_change`）
- Modify: `tests/test_prompt_budget.py`（`BASE_PROMPT_GOLDENS["main"]` 重设）
- Test: `tests/test_main_change_routing.py`

**Interfaces:**
- Produces: `main_agent.change_management_tools() -> list`（受 `settings.change_management_enabled` 门控：`[request_change, review_change, get_change_request, list_change_requests, execute_change]` 或 `[]`）；`notify_change_requested(cr: dict)`, `notify_change_pending_approval(cr: dict, plan: dict)`, `notify_change_result(cr: dict, outcome: str)`；`preprocessor.CHANGE_REF_PATTERN = r"\bC#(\d+)\b"`、`reference_resolver.fetch_change(cr_id) -> Optional[dict]`。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_main_change_routing.py
from unittest.mock import patch


def test_main_prompt_routes_changes():
    from agenticops.agents.main_agent import MAIN_SYSTEM_PROMPT as p
    assert "5.7." in p and "request_change" in p and "review_change" in p
    assert "C#N" in p and "[CHANGE REQUEST]" in p
    assert "change_required" in p  # rule 10 addendum


def test_change_tools_gated_by_setting():
    from agenticops.config import settings
    from agenticops.agents.main_agent import change_management_tools
    with patch.object(settings, "change_management_enabled", True):
        names = [getattr(t, "tool_name", None) or getattr(t, "__name__", str(t)) for t in change_management_tools()]
    assert any("request_change" in n for n in names) and any("review_change" in n for n in names)
    with patch.object(settings, "change_management_enabled", False):
        assert change_management_tools() == []


def test_change_ref_resolution(tmp_path):
    import agenticops.models as models_mod
    from agenticops.config import settings
    from agenticops.models import Base, ChangeRequest, get_session
    models_mod._engine = None
    settings.database_url = f"sqlite:///{tmp_path}/ref.db"
    Base.metadata.create_all(models_mod.get_engine())
    s = get_session()
    s.add(ChangeRequest(title="Tag web", description="add Env=prod", requested_by="cli:m", status="planned", risk_level="L1"))
    s.commit(); s.close()
    from agenticops.chat.preprocessor import resolve_references
    text, warnings = resolve_references("please approve C#1 and look at C#99")
    assert '<referenced_change id="1">' in text and "Tag web" in text and "planned" in text
    assert warnings == ["ChangeRequest C#99 not found"]
    models_mod._engine = None


def test_notifications_format_and_severity():
    from agenticops.services import notification_service as ns
    cr = {"id": 3, "title": "Tag web", "requested_by": "user:alice", "risk_level": "L1", "requested_change_type": "normal",
          "effective_change_type": "standard", "account_id": 1, "target_resources": [{"resource_id": "i-0abc"}]}
    with patch.object(ns, "notify_event") as ne:
        ns.notify_change_requested(cr)
        ns.notify_change_pending_approval(cr, {"id": 9, "title": "p", "risk_level": "L1", "summary": "s"})
        ns.notify_change_result(cr, "completed")
        ns.notify_change_result({**cr, "risk_level": "L3"}, "failed")
    calls = ne.call_args_list
    assert calls[0].args[0] == "change_requested" and "Change #3" in calls[0].args[1] and calls[0].args[3] == "low"
    assert calls[1].args[0] == "change_pending_approval" and "/app/changes/3" in calls[1].args[2] and calls[1].args[3] == "low"
    assert calls[2].args[0] == "change_result" and "COMPLETED" in calls[2].args[1] and calls[2].args[3] == "low"
    assert calls[3].args[3] == "high"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_main_change_routing.py -q`
Expected: FAIL — `ImportError: cannot import name 'change_management_tools'`

- [ ] **Step 3: Main agent**

import：`from agenticops.agents.sre_agent import sre_agent, sre_query, review_change` 与 `from agenticops.tools.change_tools import request_change, get_change_request, list_change_requests, execute_change`。新增模块函数：

```python
def change_management_tools() -> list:
    """Change Management tools for the main agent — absent entirely when the feature is off
    (an agent must never see a tool it cannot use)."""
    if not settings.change_management_enabled:
        return []
    return [request_change, review_change, get_change_request, list_change_requests, execute_change]
```

`_build_agent` 的 `tools=[...]` 里在 `reporter_agent,` 之后加 `*change_management_tools(),`。

提示词：SPECIALIZED AGENTS 段加一行
```
- review_change: Reviews a CHANGE REQUEST (C#N) — grounds targets, classifies risk, evaluates policy, saves the change plan. Call with change_request_id. READ-ONLY.
```
METADATA TOOLS 段加
```
- request_change / get_change_request / list_change_requests / execute_change: Change Management (ITSM) — open, inspect, list and queue execution of change requests (C#N).
```
ROUTING RULES 在 5.6 之后加：
```
5.7. CHANGE MANAGEMENT — a modification with NO HealthIssue behind it (add/remove tags, scale, change
     configuration or parameters, security-group / IAM edits), or the user says "change request" / "CR" /
     "变更", or the message starts with "[CHANGE REQUEST]" → call request_change(title, description,
     account, targets, change_type), then IMMEDIATELY review_change(change_request_id). Present the
     verdict, risk, plan summary and the reference C#N, and tell the user where to approve
     (Web: Plans & Changes; CLI: /approve C<N>). NEVER route such intents to sre_query for writes.
     "approve/execute change C#N" → approval is a human action in Web/CLI; execute_change only after the
     user confirms an APPROVED change.
```
规则 10 末尾加一句：
```
   If sre_query reports a write command refused as change_required, do not retry it — offer to open a
   change request (rule 5.7).
```
OUTPUT FORMATTING 的引用行改为 `When referencing issues, use I#N ... resources, R#N ... change requests, C#N (e.g., C#7).`。重设 `BASE_PROMPT_GOLDENS["main"]` 为实际长度（四舍五入到百位）。

- [ ] **Step 4: 通知（替换 Task 3 的桩）**

```python
# ── Change Management (MVP-2.6.0) ─────────────────────────────────────

def _change_severity(risk_level, outcome: str | None = None) -> str:
    if outcome in ("failed", "rolled_back", "review_failed"):
        return "high"
    return {"L0": "low", "L1": "low", "L2": "medium", "L3": "high"}.get(risk_level or "", "medium")


def _change_link(cr_id: int) -> str:
    return f"{settings.web_base_url.rstrip('/')}/app/changes/{cr_id}"


def notify_change_requested(cr: dict) -> None:
    """Notify: a change request was opened (sent immediately — changes are not batched)."""
    targets = ", ".join(t.get("resource_id", "") for t in cr.get("target_resources") or []) or "(to be grounded)"
    notify_event(
        "change_requested",
        f"[CHANGE] Change #{cr['id']} requested: {cr['title']}",
        (f"Change request #{cr['id']} opened by {cr['requested_by']} ({cr.get('requested_change_type', 'normal')}).\n\n"
         f"Title: {cr['title']}\nTargets: {targets}\n{_change_link(cr['id'])}"),
        _change_severity(cr.get("risk_level")),
    )


def notify_change_pending_approval(cr: dict, plan: dict) -> None:
    """Notify: reviewed and planned — a human approver is needed (deep link included)."""
    notify_event(
        "change_pending_approval",
        f"[CHANGE] Change #{cr['id']} awaits approval ({cr.get('risk_level') or '?'}, {cr.get('effective_change_type') or 'normal'})",
        (f"Change request #{cr['id']} '{cr['title']}' was reviewed by the SRE agent and needs approval.\n\n"
         f"Plan #{plan.get('id')}: {plan.get('title')}\nRisk: {cr.get('risk_level')}\n"
         f"Requested by: {cr['requested_by']}\n\nApprove or reject: {_change_link(cr['id'])}"),
        _change_severity(cr.get("risk_level")),
    )


def notify_change_result(cr: dict, outcome: str) -> None:
    """Notify: terminal or attention-needing outcome (completed / failed / rolled_back / needs_review /
    rejected / needs_clarification / review_failed)."""
    notify_event(
        "change_result",
        f"[CHANGE] Change #{cr['id']} {outcome.upper()}: {cr['title']}",
        (f"Change request #{cr['id']} is now {outcome}.\n\nRequested by: {cr['requested_by']}\n"
         f"Risk: {cr.get('risk_level') or '?'}\n{_change_link(cr['id'])}"),
        _change_severity(cr.get("risk_level"), outcome),
    )
```

- [ ] **Step 5: `C#N` 引用**

`reference_resolver.py` 加：

```python
def fetch_change(cr_id: int) -> Optional[dict]:
    """Return a ChangeRequest as a dict, or None if not found."""
    from agenticops.models import ChangeRequest
    with get_db_session() as session:
        cr = session.get(ChangeRequest, cr_id)
        if not cr:
            return None
        return {"id": cr.id, "title": cr.title, "status": cr.status, "risk_level": cr.risk_level,
                "requested_by": cr.requested_by, "requested_change_type": cr.requested_change_type,
                "targets": [t.get("resource_id") for t in (cr.target_resources or [])],
                "description": (cr.description or "")[:500]}
```

`preprocessor.py`：`CHANGE_REF_PATTERN = re.compile(r"\bC#(\d+)\b")`；

```python
def _resolve_change_ref(cr_id: int) -> str | None:
    from agenticops.chat.reference_resolver import fetch_change
    d = fetch_change(cr_id)
    if not d:
        return None
    return (
        f'<referenced_change id="{d["id"]}">\n'
        f"Title: {d['title']}\nStatus: {d['status']}\nRisk: {d['risk_level'] or 'unassessed'}\n"
        f"Type: {d['requested_change_type']}\nRequested by: {d['requested_by']}\n"
        f"Targets: {', '.join(t for t in d['targets'] if t) or 'none grounded yet'}\n"
        f"Description: {d['description']}\n</referenced_change>"
    )
```

`resolve_references` 在 R# 循环后加 C# 循环（warning 文案 `f"ChangeRequest C#{cr_id} not found"`）；模块 docstring 加 `- C#N reference resolution (ChangeRequest by ID)`。

- [ ] **Step 6: 跑测试 + Commit**

```bash
python -m pytest tests/test_main_change_routing.py tests/test_prompt_budget.py tests/test_notification_service.py -q
python -m pytest tests/ -q --deselect tests/test_web_tools.py > /tmp/pytest-b9.log 2>&1; tail -5 /tmp/pytest-b9.log
git add src/agenticops/agents/main_agent.py src/agenticops/services/notification_service.py src/agenticops/chat/preprocessor.py src/agenticops/chat/reference_resolver.py tests/test_main_change_routing.py tests/test_prompt_budget.py
git commit -m "feat(main): change-intent routing (rule 5.7), gated change tools, C#N references, change notifications"
```

---

### Task 10: CLI 斜杠命令 — `/change`、`/changes`、`/reject`，`/approve` `/execute` 支持 `C<id>`

**Files:**
- Modify: `src/agenticops/cli/main.py`（新增 `_slash_change`、`_slash_changes`、`_slash_reject`；扩展 `_slash_approve` :2261、`_slash_execute` :2317；`SLASH_COMMANDS` :3393；`/help` 文案）
- Test: `tests/test_cli_change_commands.py`

**Interfaces:**
- Produces: `/change <描述> [--account NAME] [--emergency]`（资源 id/ARN 自动抽取为 targets；建单 → **同步**跑 SRE 审核并展示结论）；`/changes [status]`；`/approve C<id> [理由...]`（理由缺失则 `Prompt.ask`）；`/reject C<id> <理由>`；`/execute C<id>`（Confirm 后入队）。`_extract_target_hints(text) -> list[str]`；`_parse_change_ref(token) -> Optional[int]`（`C12`/`c12`/`C#12` → 12，纯数字 → None）。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_cli_change_commands.py
from unittest.mock import patch

import pytest

from agenticops.models import Base, CloudAccount, get_session


@pytest.fixture
def db(tmp_path):
    import agenticops.models as models_mod
    import agenticops.audit.models  # noqa: F401
    from agenticops.config import settings
    models_mod._engine = None
    settings.database_url = f"sqlite:///{tmp_path}/cli.db"
    Base.metadata.create_all(models_mod.get_engine())
    s = get_session()
    s.add(CloudAccount(name="dev", provider="aws", is_enabled=True, credentials={}, regions=[])); s.commit()
    yield s
    s.close()
    models_mod._engine = None


def test_helpers():
    from agenticops.cli.main import _extract_target_hints, _parse_change_ref
    assert _extract_target_hints("tag i-0abc12345678 and sg-1234abcd plus arn:aws:s3:::b1") == ["i-0abc12345678", "sg-1234abcd", "arn:aws:s3:::b1"]
    assert _parse_change_ref("C12") == 12 and _parse_change_ref("c#7") == 7 and _parse_change_ref("12") is None


def test_slash_change_creates_and_reviews_sync(db):
    from agenticops.cli import main as cli
    with patch("agenticops.cli.main.init_db"), \
         patch("agenticops.services.change_service.start_review", return_value="SRE: planned, L1") as sr, \
         patch("agenticops.services.change_service.notify_change_requested"), \
         patch("getpass.getuser", return_value="malibo"):
        out = cli._slash_change(None, ["add", "tag", "Env=prod", "to", "i-0abc12345678", "--account", "dev"])
    assert "C#" in out and "SRE: planned, L1" in out
    from agenticops.models import ChangeRequest
    cr = db.query(ChangeRequest).one()
    assert cr.source == "cli" and cr.requested_by == "cli:malibo" and cr.target_hints == ["i-0abc12345678"] and cr.account_id is not None
    sr.assert_called_once_with(cr.id, sync=True)


def test_slash_change_disabled(db):
    from agenticops.cli import main as cli
    from agenticops.config import settings
    with patch.object(settings, "change_management_enabled", False), patch("agenticops.cli.main.init_db"):
        assert "disabled" in cli._slash_change(None, ["x"])


def test_slash_approve_reject_execute_changes(db):
    from agenticops.cli import main as cli
    from agenticops.services import change_service as cs
    with patch("agenticops.cli.main.init_db"), patch("getpass.getuser", return_value="malibo"):
        with patch.object(cs, "approve", return_value={"id": 4, "status": "approved"}) as ap:
            out = cli._slash_approve(None, ["C4", "looks", "good"])
        assert "approved" in out and ap.call_args.kwargs["reason"] == "looks good" and ap.call_args.kwargs["actor"].key == "cli:malibo"
        with patch.object(cs, "reject", return_value={"id": 4, "status": "rejected"}) as rj:
            out = cli._slash_reject(None, ["C4", "not", "now"])
        assert "rejected" in out and rj.call_args.kwargs["reason"] == "not now"
        assert "Usage" in cli._slash_reject(None, ["C4"])  # reason required
        with patch.object(cs, "get_change", return_value={"id": 4, "status": "approved", "title": "t", "risk_level": "L1"}), \
             patch.object(cs, "request_execution", return_value={"execution_id": 9, "fix_plan_id": 2, "change": {}}) as ex, \
             patch("rich.prompt.Confirm.ask", return_value=True):
            out = cli._slash_execute(None, ["C4"])
        assert "Execution #9" in out and ex.called
        with patch.object(cs, "approve", side_effect=cs.ChangeStateError("is 'approved'")):
            assert "approved" in cli._slash_approve(None, ["C4", "again"])


def test_slash_changes_lists(db):
    from agenticops.cli import main as cli
    from agenticops.services import change_service as cs
    rows = [{"id": 1, "title": "Tag web", "status": "planned", "risk_level": "L1", "effective_change_type": "standard",
             "requested_by": "cli:m", "updated_at": "2026-09-17T00:00:00"}]
    with patch("agenticops.cli.main.init_db"), patch.object(cs, "list_changes", return_value=rows) as lc:
        out = cli._slash_changes(None, ["planned"])
    assert "Tag web" in out or "C#1" in out
    assert lc.call_args.kwargs["status"] == "planned"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_cli_change_commands.py -q`
Expected: FAIL — `AttributeError: module 'agenticops.cli.main' has no attribute '_extract_target_hints'`

- [ ] **Step 3: 实现**

在 `_slash_approve` 之前加：

```python
_TARGET_HINT_RE = re.compile(r"\b(i-[0-9a-f]{8,17}|sg-[0-9a-f]{8,17}|subnet-[0-9a-f]{8,17}|vpc-[0-9a-f]{8,17}|vol-[0-9a-f]{8,17}|arn:aws[^\s,]+)")


def _extract_target_hints(text: str) -> list[str]:
    seen, out = set(), []
    for m in _TARGET_HINT_RE.finditer(text or ""):
        if m.group(1) not in seen:
            seen.add(m.group(1)); out.append(m.group(1))
    return out


def _parse_change_ref(token: str) -> Optional[int]:
    """'C12' / 'c12' / 'C#12' → 12; anything else (incl. plain digits = fix plan id) → None."""
    t = (token or "").strip().upper().replace("#", "")
    if len(t) > 1 and t[0] == "C" and t[1:].isdigit():
        return int(t[1:])
    return None


def _slash_change(ctx: ChatContext, args: list) -> str:
    """Handle /change <description> [--account NAME] [--emergency] — open a change request and review it now."""
    from agenticops.auth.actor import cli_actor
    from agenticops.services import change_service as cs

    if not settings.change_management_enabled:
        return "[yellow]Change management is disabled (change_management_enabled=false).[/yellow]"
    if not args:
        return "[yellow]Usage: /change <what to change and why> [--account NAME] [--emergency][/yellow]"
    words, account, emergency = list(args), "", False
    if "--account" in words:
        i = words.index("--account")
        account = words[i + 1] if i + 1 < len(words) else ""
        del words[i:i + 2]
    if "--emergency" in words:
        emergency = True
        words.remove("--emergency")
    text = " ".join(words).strip()
    if not text:
        return "[yellow]Usage: /change <what to change and why> [--account NAME] [--emergency][/yellow]"
    init_db()
    try:
        cr = cs.create_change_request(
            source="cli", actor=cli_actor(), title=text[:80], description=text, account_name=account or None,
            targets=_extract_target_hints(text), requested_change_type="emergency" if emergency else "normal",
            start_review=False,
        )
    except cs.ChangeError as e:
        return f"[red]{e}[/red]"
    display = ThinkingDisplay(console)
    with display.live_display():
        display.start(f"SRE reviewing change C#{cr['id']}")
        display.tool_call("review_change", f"change_request_id={cr['id']}")
        try:
            result = cs.start_review(cr["id"], sync=True)
        except cs.ChangeError as e:
            result = f"Review not started: {e}"
        display.complete("Review finished")
    final = cs.get_change(cr["id"])
    return (f"[green]✓ Change request C#{cr['id']} — status: {final['status']}"
            f"{' · risk ' + final['risk_level'] if final.get('risk_level') else ''}[/green]\n{result or ''}\n"
            f"[dim]Approve with: /approve C{cr['id']} <reason>   ·   Web: /app/changes/{cr['id']}[/dim]")


def _slash_changes(ctx: ChatContext, args: list) -> str:
    """Handle /changes [status] — list change requests."""
    from agenticops.services import change_service as cs
    init_db()
    status = args[0] if args else None
    rows = cs.list_changes(status=status, limit=50)
    if not rows:
        return "[dim]No change requests found.[/dim]"
    table = create_table("Change Requests")
    for col, w in (("C#", 6), ("Title", 40), ("Status", 20), ("Risk", 5), ("Type", 10), ("Requested by", 18), ("Updated", 20)):
        table.add_column(col, width=w) if w else table.add_column(col)
    for r in rows:
        table.add_row(f"C#{r['id']}", (r["title"] or "")[:40], r["status"].replace("_", " "), r.get("risk_level") or "-",
                      r.get("effective_change_type") or r.get("requested_change_type") or "-", r["requested_by"],
                      (r.get("updated_at") or r.get("created_at") or "")[:19])
    console.print(table)
    return ""


def _slash_reject(ctx: ChatContext, args: list) -> str:
    """Handle /reject C<id> <reason> — reject a planned change request."""
    from agenticops.auth.actor import cli_actor
    from agenticops.services import change_service as cs
    cr_id = _parse_change_ref(args[0]) if args else None
    reason = " ".join(args[1:]).strip() if len(args) > 1 else ""
    if cr_id is None or not reason:
        return "[yellow]Usage: /reject C<id> <reason>[/yellow]"
    init_db()
    try:
        out = cs.reject(cr_id, actor=cli_actor(), reason=reason)
    except cs.ChangeError as e:
        return f"[red]{e}[/red]"
    return f"[green]Change C#{cr_id} rejected ({out['status']}).[/green]"
```

`_slash_approve` 开头（解析 `plan_id` 之前）加分支：

```python
    cr_id = _parse_change_ref(args[0]) if args else None
    if cr_id is not None:
        from agenticops.auth.actor import cli_actor
        from agenticops.services import change_service as cs
        reason = " ".join(args[1:]).strip()
        if not reason:
            reason = Prompt.ask("Approval reason (required)").strip()
            if not reason:
                return "[red]A reason is required to approve a change.[/red]"
        init_db()
        try:
            out = cs.approve(cr_id, actor=cli_actor(), reason=reason)
        except cs.ChangeError as e:
            return f"[red]{e}[/red]"
        return f"[green]Change C#{cr_id} approved by {cli_actor().key} ({out['status']}). Execute with: /execute C{cr_id}[/green]"
```

`_slash_execute` 开头加：

```python
    cr_id = _parse_change_ref(args[0]) if args else None
    if cr_id is not None:
        from agenticops.auth.actor import cli_actor
        from agenticops.services import change_service as cs
        init_db()
        try:
            cr = cs.get_change(cr_id)
        except cs.ChangeError as e:
            return f"[red]{e}[/red]"
        console.print(f"[bold]Execute change C#{cr_id}?[/bold]\n  Title: {cr['title']}\n  Status: {cr['status']}\n  Risk: {cr.get('risk_level')}")
        if not Confirm.ask("Confirm execution?"):
            return "[dim]Execution cancelled.[/dim]"
        try:
            out = cs.request_execution(cr_id, actor=cli_actor())
        except cs.ChangeError as e:
            return f"[red]{e}[/red]"
        return f"[green]Execution #{out['execution_id']} queued for change C#{cr_id} (plan #{out['fix_plan_id']}).[/green]"
```

用法文案改为 `/approve <plan_id|C<id>> [reason...]`、`/execute <plan_id|C<id>>`。`SLASH_COMMANDS` 加 `"change": _slash_change, "changes": _slash_changes, "reject": _slash_reject`；`/help` 在 Fix plans 段后加 "Changes" 段三行。顶部确认 `import re` 与 `from typing import Optional`。

- [ ] **Step 4: 跑测试 + Commit**

```bash
python -m pytest tests/test_cli_change_commands.py tests/test_plan_approval_audit.py -q
git add src/agenticops/cli/main.py tests/test_cli_change_commands.py
git commit -m "feat(cli): /change /changes /reject; /approve and /execute accept C<id>"
```

---

### Task 11: Web API — schemas、`routers/changes.py`、`/api/command-audits`、注册

**Files:**
- Modify: `src/agenticops/web/schemas.py`（末尾追加 Change schemas + `CommandAuditResponse`）
- Create: `src/agenticops/web/routers/changes.py`
- Modify: `src/agenticops/web/routers/audit.py`（追加 `GET /api/command-audits`）
- Modify: `src/agenticops/web/app.py:316-319`（`include_router`）
- Test: `tests/test_changes_api.py`

**Interfaces:**
- Produces（URL 与形状是 Plan C 的契约）：
  - `POST /api/changes` 201 `ChangeRequestResponse`（body `ChangeRequestCreate`；后台审核）
  - `GET /api/changes?status&account_id&requested_by&period=7d|30d|90d&limit&offset` → `List[ChangeRequestResponse]`
  - `GET /api/changes/{id}` → `ChangeRequestDetail`（+ `plans: List[FixPlanResponse]`, `executions: List[FixExecutionResponse]`）
  - `POST /api/changes/{id}/approve|reject|cancel` body `ChangeReasonBody{reason}` → 200 `ChangeRequestResponse`
  - `POST /api/changes/{id}/clarify` body `ChangeClarifyBody{message}` → 202
  - `POST /api/changes/{id}/execute` → 202 `FixExecutionResponse`
  - `POST /api/changes/{id}/review` → 202（draft 重新发起审核）
  - `POST /api/changes/{id}/resolve-review` body `ChangeResolveReviewBody{outcome, reason}` → 200
  - `GET /api/changes/{id}/timeline` → `List[ChangeTimelineEntry]`
  - `GET /api/command-audits?actor&tool&outcome&fix_plan_id&change_request_id&period&limit&offset` → `List[CommandAuditResponse]`（authz `audit.read`）
  - 错误映射：`ChangeError.status_code` → HTTP；`change_management_enabled=false` → 404。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_changes_api.py
from unittest.mock import patch

import pytest
from starlette.testclient import TestClient

from agenticops.auth.actor import Actor
from agenticops.models import Base, ChangeRequest, CloudAccount, CloudResource, CommandAudit, FixPlan, get_session


@pytest.fixture
def client(tmp_path):
    import agenticops.models as models_mod
    import agenticops.audit.models  # noqa: F401
    from agenticops.config import settings
    from agenticops.web.app import app
    models_mod._engine = None
    settings.database_url = f"sqlite:///{tmp_path}/capi.db"
    Base.metadata.create_all(models_mod.get_engine())
    s = get_session()
    acct = CloudAccount(name="dev", provider="aws", is_enabled=True, credentials={}, regions=["ap-southeast-1"]); s.add(acct); s.flush()
    s.add(CloudResource(account_id=acct.id, provider="aws", region="ap-southeast-1", resource_type="EC2Instance", resource_id="i-0abc", name="web"))
    s.commit(); s.close()
    yield TestClient(app)
    models_mod._engine = None


def _planned():
    """Drive a CR to 'planned' through the service (SRE mocked away)."""
    from agenticops.services import change_service as cs
    with patch.object(cs, "notify_change_requested"):
        cr = cs.create_change_request(source="web", actor=Actor("user", "alice", 1, ("read", "write")), title="Tag web",
                                      description="add Env=prod", account_name="dev", targets=["i-0abc"], start_review=False)
    with cs._session() as s:
        cs.transition_change(s.get(ChangeRequest, cr["id"]), "under_review")
    cs.ground_targets(cr["id"])
    s = get_session()
    s.add(FixPlan(plan_kind="change", change_request_id=cr["id"], risk_level="L1", title="p", summary="s",
                  steps=[{"command": "aws ec2 create-tags"}], rollback_plan={"steps": ["aws ec2 delete-tags"]},
                  post_checks=[{"check": "present", "command": "aws ec2 describe-tags"}], status="draft"))
    s.commit(); s.close()
    with patch.object(cs, "notify_change_pending_approval"):
        cs.submit_review(cr["id"], verdict="approved_for_planning", risk_level="L1", action_type="tag", reasons=["ok"], actor=Actor("agent", "sre"))
    return cr["id"]


def test_create_lists_and_detail(client):
    with patch("agenticops.services.change_service.start_review") as sr, \
         patch("agenticops.services.change_service.notify_change_requested"):
        r = client.post("/api/changes", json={"title": "Tag web", "description": "add Env=prod", "account_name": "dev",
                                              "targets": ["i-0abc"], "requested_change_type": "normal"})
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "draft" and body["requested_by"] == "web:anonymous" and body["source"] == "web"
    sr.assert_called_once_with(body["id"], sync=False)
    assert client.get("/api/changes").json()[0]["id"] == body["id"]
    assert client.get("/api/changes?status=planned").json() == []
    d = client.get(f"/api/changes/{body['id']}").json()
    assert d["plans"] == [] and d["executions"] == [] and d["target_hints"] == ["i-0abc"]
    assert client.get("/api/changes/9999").status_code == 404


def test_validation_errors(client):
    assert client.post("/api/changes", json={"title": "", "description": "x"}).status_code == 422
    assert client.post("/api/changes", json={"title": "t", "description": "d", "requested_change_type": "urgent"}).status_code == 422
    with patch("agenticops.services.change_service.notify_change_requested"):
        r = client.post("/api/changes", json={"title": "t", "description": "d", "account_name": "nope"})
    assert r.status_code == 422 and "account" in r.json()["detail"]


def test_disabled_returns_404(client):
    from agenticops.config import settings
    with patch.object(settings, "change_management_enabled", False):
        assert client.get("/api/changes").status_code == 404


def test_approve_requires_reason_and_binds_identity(client):
    cr_id = _planned()
    assert client.post(f"/api/changes/{cr_id}/approve", json={}).status_code == 422
    r = client.post(f"/api/changes/{cr_id}/approve", json={"reason": "reviewed"})
    assert r.status_code == 200 and r.json()["status"] == "approved" and r.json()["approved_by"] == "web:anonymous"
    assert client.post(f"/api/changes/{cr_id}/approve", json={"reason": "again"}).status_code == 409


def test_sod_403_when_enforced(client):
    from agenticops.config import settings
    cr_id = _planned()
    # requester was user:alice; anonymous approver is a different actor → allowed even when enforced …
    # … so emulate the same actor via rbac by making the request come from web:anonymous
    from agenticops.services import change_service as cs
    with patch.object(cs, "notify_change_requested"):
        cr2 = cs.create_change_request(source="web", actor=Actor("web", "anonymous"), title="t", description="d", start_review=False)
    with cs._session() as s:
        row = s.get(ChangeRequest, cr2["id"]); cs.transition_change(row, "under_review"); cs.transition_change(row, "planned")
    with patch.object(settings, "rbac_enforce", True):
        r = client.post(f"/api/changes/{cr2['id']}/approve", json={"reason": "self"})
    assert r.status_code == 403


def test_reject_cancel_clarify_review(client):
    from agenticops.services import change_service as cs
    cr_id = _planned()
    with patch.object(cs, "notify_change_result"):
        r = client.post(f"/api/changes/{cr_id}/reject", json={"reason": "no"})
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    with patch.object(cs, "notify_change_requested"):
        cr = cs.create_change_request(source="web", actor=Actor("user", "a", 1, ("read", "write")), title="t", description="vague", start_review=False)
    assert client.post(f"/api/changes/{cr['id']}/cancel", json={"reason": "oops"}).status_code == 200
    with patch.object(cs, "notify_change_requested"):
        cr3 = cs.create_change_request(source="web", actor=Actor("user", "a", 1, ("read", "write")), title="t", description="vague", start_review=False)
    with patch("agenticops.services.change_service.start_review") as sr:
        assert client.post(f"/api/changes/{cr3['id']}/review").status_code == 202
    sr.assert_called_once()
    with cs._session() as s:
        row = s.get(ChangeRequest, cr3["id"]); cs.transition_change(row, "under_review"); cs.transition_change(row, "needs_clarification")
    with patch("agenticops.services.change_service.start_review") as sr2:
        r = client.post(f"/api/changes/{cr3['id']}/clarify", json={"message": "it is i-0abc"})
    assert r.status_code == 202 and sr2.called


def test_execute_and_timeline(client):
    from agenticops.config import settings
    cr_id = _planned()
    client.post(f"/api/changes/{cr_id}/approve", json={"reason": "ok"})
    with patch.object(settings, "executor_enabled", True):
        r = client.post(f"/api/changes/{cr_id}/execute")
    assert r.status_code == 202 and r.json()["status"] == "pending" and r.json()["executed_by"] == "web:anonymous"
    d = client.get(f"/api/changes/{cr_id}").json()
    assert d["status"] == "executing" and d["plans"][0]["plan_kind"] == "change" and len(d["executions"]) == 1
    tl = client.get(f"/api/changes/{cr_id}/timeline").json()
    assert {e["kind"] for e in tl} == {"event", "audit"} and any(e["type"] == "change.approved" for e in tl)


def test_resolve_review(client):
    from agenticops.config import settings
    from agenticops.services import change_service as cs
    cr_id = _planned()
    client.post(f"/api/changes/{cr_id}/approve", json={"reason": "ok"})
    with patch.object(settings, "executor_enabled", True):
        plan_id = client.post(f"/api/changes/{cr_id}/execute").json()["fix_plan_id"]
    with patch.object(cs, "notify_change_result"):
        cs.on_execution_result(plan_id, "succeeded", post_check_results=[])
    assert client.post(f"/api/changes/{cr_id}/resolve-review", json={"outcome": "maybe", "reason": "x"}).status_code == 422
    with patch.object(cs, "notify_change_result"):
        r = client.post(f"/api/changes/{cr_id}/resolve-review", json={"outcome": "completed", "reason": "checked in console"})
    assert r.status_code == 200 and r.json()["status"] == "completed"


def test_command_audits_endpoint(client):
    s = get_session()
    s.add(CommandAudit(actor="cli:m", tool="run_aws_cli", tier="write", command="aws ec2 create-tags", outcome="executed", change_request_id=3))
    s.add(CommandAudit(actor="cli:m", tool="run_on_host", tier="write", command="systemctl restart x", outcome="refused", reason="change_required"))
    s.commit(); s.close()
    r = client.get("/api/command-audits")
    assert r.status_code == 200 and len(r.json()) == 2
    assert len(client.get("/api/command-audits?outcome=refused").json()) == 1
    assert client.get("/api/command-audits?change_request_id=3").json()[0]["command"] == "aws ec2 create-tags"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_changes_api.py -q`
Expected: FAIL — 404 on `POST /api/changes`

- [ ] **Step 3: schemas（追加到 `schemas.py` 末尾）**

```python
# ============================================================================
# Change Management (MVP-2.6.0)
# ============================================================================


class ChangeRequestCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=300)
    description: str = Field(..., min_length=1)
    account_name: Optional[str] = None
    targets: List[str] = Field(default_factory=list)
    requested_change_type: str = Field("normal", pattern="^(normal|emergency)$")
    justification: str = ""


class ChangeRequestResponse(BaseModel):
    """Snapshot of a change request (from change_service.to_dict — timestamps are ISO strings)."""
    id: int
    title: str
    description: str
    justification: str = ""
    source: str
    requested_by: str
    requester_user_id: Optional[int] = None
    requested_at: Optional[str] = None
    account_id: Optional[int] = None
    target_hints: list = Field(default_factory=list)
    target_resources: list = Field(default_factory=list)
    requested_change_type: str = "normal"
    effective_change_type: Optional[str] = None
    risk_level: Optional[str] = None
    action_type: Optional[str] = None
    status: str
    review_verdict: Optional[str] = None
    review_reasons: list = Field(default_factory=list)
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[str] = None
    policy_rule: Optional[str] = None
    policy_action: Optional[str] = None
    approved_by: Optional[str] = None
    approver_user_id: Optional[int] = None
    approved_at: Optional[str] = None
    approval_reason: Optional[str] = None
    rejected_by: Optional[str] = None
    rejected_at: Optional[str] = None
    rejection_reason: Optional[str] = None
    closed_at: Optional[str] = None
    trace_id: Optional[str] = None
    chat_session_id: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class ChangeRequestDetail(ChangeRequestResponse):
    plans: List[FixPlanResponse] = Field(default_factory=list)
    executions: List[FixExecutionResponse] = Field(default_factory=list)


class ChangeReasonBody(BaseModel):
    reason: str = Field(..., min_length=1, max_length=2000)


class ChangeClarifyBody(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000)


class ChangeResolveReviewBody(BaseModel):
    outcome: str = Field(..., pattern="^(completed|failed)$")
    reason: str = Field(..., min_length=1, max_length=2000)


class ChangeTimelineEntry(BaseModel):
    ts: Optional[str] = None
    kind: str  # event | audit
    type: str
    actor: Optional[str] = None
    status: Optional[str] = None
    stage: Optional[str] = None
    detail: Optional[object] = None


class CommandAuditResponse(BaseModel):
    id: int
    created_at: datetime
    actor: str
    on_behalf_of: Optional[str] = None
    agent_name: Optional[str] = None
    tool: str
    tier: str
    account: str = ""
    region: str = ""
    target: str = ""
    command: str
    outcome: str
    reason: Optional[str] = None
    exit_code: Optional[int] = None
    output_excerpt: str = ""
    duration_ms: int = 0
    trace_id: Optional[str] = None
    fix_plan_id: Optional[int] = None
    change_request_id: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)
```

- [ ] **Step 4: `routers/changes.py`**

```python
"""Change Management API (MVP-2.6.0) — pure routing over services.change_service."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from agenticops.auth.actor import Actor
from agenticops.config import settings
from agenticops.models import FixExecution, FixPlan, get_db_session
from agenticops.services import change_service as cs
from agenticops.web.deps import current_actor
from agenticops.web.schemas import (
    ChangeClarifyBody, ChangeReasonBody, ChangeRequestCreate, ChangeRequestDetail, ChangeRequestResponse,
    ChangeResolveReviewBody, ChangeTimelineEntry, FixExecutionResponse, FixPlanResponse,
)

router = APIRouter(prefix="/api/changes", tags=["changes"])

_PERIOD = {"7d": timedelta(days=7), "30d": timedelta(days=30), "90d": timedelta(days=90)}


def _enabled() -> None:
    if not settings.change_management_enabled:
        raise HTTPException(status_code=404, detail="Change management is disabled (change_management_enabled=false)")


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except cs.ChangeError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))


@router.post("", response_model=ChangeRequestResponse, status_code=201)
async def api_create_change(data: ChangeRequestCreate, actor: Actor = Depends(current_actor)):
    """Open a change request; the SRE review starts in the background (poll GET /api/changes/{id})."""
    _enabled()
    source = "web" if actor.kind in ("user", "web") else "api"
    return _call(cs.create_change_request, source=source, actor=actor, title=data.title, description=data.description,
                 account_name=data.account_name, targets=data.targets, requested_change_type=data.requested_change_type,
                 justification=data.justification, start_review=True)


@router.get("", response_model=List[ChangeRequestResponse])
async def api_list_changes(
    status: Optional[str] = None, account_id: Optional[int] = None, requested_by: Optional[str] = None,
    period: Optional[str] = Query(None, pattern="^(7d|30d|90d)$"),
    limit: int = Query(default=50, le=500), offset: int = Query(default=0, ge=0),
):
    _enabled()
    since = datetime.now(timezone.utc) - _PERIOD[period] if period else None
    return cs.list_changes(status=status, account_id=account_id, requested_by=requested_by, since=since, limit=limit, offset=offset)


@router.get("/{cr_id}", response_model=ChangeRequestDetail)
async def api_get_change(cr_id: int):
    _enabled()
    snap = _call(cs.get_change, cr_id)
    with get_db_session() as session:
        plans = session.query(FixPlan).filter_by(change_request_id=cr_id).order_by(FixPlan.created_at.desc()).all()
        plan_ids = [p.id for p in plans]
        executions = (session.query(FixExecution).filter(FixExecution.fix_plan_id.in_(plan_ids))
                      .order_by(FixExecution.created_at.desc()).all()) if plan_ids else []
        snap["plans"] = [FixPlanResponse.model_validate(p) for p in plans]
        snap["executions"] = [FixExecutionResponse.model_validate(e) for e in executions]
    return snap


@router.post("/{cr_id}/approve", response_model=ChangeRequestResponse)
async def api_approve_change(cr_id: int, body: ChangeReasonBody, actor: Actor = Depends(current_actor)):
    _enabled()
    return _call(cs.approve, cr_id, actor=actor, reason=body.reason)


@router.post("/{cr_id}/reject", response_model=ChangeRequestResponse)
async def api_reject_change(cr_id: int, body: ChangeReasonBody, actor: Actor = Depends(current_actor)):
    _enabled()
    return _call(cs.reject, cr_id, actor=actor, reason=body.reason)


@router.post("/{cr_id}/cancel", response_model=ChangeRequestResponse)
async def api_cancel_change(cr_id: int, body: ChangeReasonBody, actor: Actor = Depends(current_actor)):
    _enabled()
    return _call(cs.cancel, cr_id, actor=actor, reason=body.reason)


@router.post("/{cr_id}/clarify", response_model=ChangeRequestResponse, status_code=202)
async def api_clarify_change(cr_id: int, body: ChangeClarifyBody, actor: Actor = Depends(current_actor)):
    _enabled()
    return _call(cs.clarify, cr_id, actor=actor, message=body.message)


@router.post("/{cr_id}/review", response_model=ChangeRequestResponse, status_code=202)
async def api_review_change(cr_id: int, actor: Actor = Depends(current_actor)):
    """(Re)start the SRE review of a draft — e.g. after a watchdog rollback."""
    _enabled()
    return _call(cs.restart_review, cr_id, actor=actor)


@router.post("/{cr_id}/execute", response_model=FixExecutionResponse, status_code=202)
async def api_execute_change(cr_id: int, actor: Actor = Depends(current_actor)):
    _enabled()
    out = _call(cs.request_execution, cr_id, actor=actor)
    with get_db_session() as session:
        return FixExecutionResponse.model_validate(session.get(FixExecution, out["execution_id"]))


@router.post("/{cr_id}/resolve-review", response_model=ChangeRequestResponse)
async def api_resolve_review(cr_id: int, body: ChangeResolveReviewBody, actor: Actor = Depends(current_actor)):
    _enabled()
    return _call(cs.resolve_review, cr_id, actor=actor, outcome=body.outcome, reason=body.reason)


@router.get("/{cr_id}/timeline", response_model=List[ChangeTimelineEntry])
async def api_change_timeline(cr_id: int):
    _enabled()
    _call(cs.get_change, cr_id)  # 404 guard
    return cs.change_timeline(cr_id)
```

`routers/audit.py` 追加：

```python
@router.get("/api/command-audits", response_model=List[CommandAuditResponse])
async def api_list_command_audits(
    actor: Optional[str] = None, tool: Optional[str] = None, outcome: Optional[str] = None,
    fix_plan_id: Optional[int] = None, change_request_id: Optional[int] = None,
    period: Optional[str] = Query(None, pattern="^(7d|30d|90d)$"),
    limit: int = Query(default=100, le=1000), offset: int = Query(default=0, ge=0),
    current: Actor = Depends(current_actor),
):
    """Tool-layer ledger of write-tier command attempts (needs audit.read; shadow mode allows)."""
    from agenticops.auth import authz
    try:
        authz.check(current, "audit.read")
    except authz.AuthzDenied as e:
        raise HTTPException(status_code=403, detail=str(e))
    from agenticops.models import CommandAudit, get_db_session
    with get_db_session() as session:
        q = session.query(CommandAudit).order_by(CommandAudit.created_at.desc())
        if actor:
            q = q.filter(CommandAudit.actor == actor)
        if tool:
            q = q.filter(CommandAudit.tool == tool)
        if outcome:
            q = q.filter(CommandAudit.outcome == outcome)
        if fix_plan_id is not None:
            q = q.filter(CommandAudit.fix_plan_id == fix_plan_id)
        if change_request_id is not None:
            q = q.filter(CommandAudit.change_request_id == change_request_id)
        if period:
            q = q.filter(CommandAudit.created_at >= datetime.now(timezone.utc) - {"7d": timedelta(days=7), "30d": timedelta(days=30), "90d": timedelta(days=90)}[period])
        return [CommandAuditResponse.model_validate(r) for r in q.offset(offset).limit(limit).all()]
```

（imports：`Depends`, `Actor`, `current_actor`, `CommandAuditResponse`。）同一文件里现有的 `api_list_audit_logs`、`api_get_entity_audit`、`api_get_audit_stats` 仍手工解析 Bearer 并要求 admin——认证关闭时它们永远 401，Settings→Audit 与 Plan C 的 Audit tab 都会打不开。改成与其余端点一致：签名加 `current: Actor = Depends(current_actor)`，删掉手工 Bearer 解析，用 `authz.check(current, "audit.read")`（认证开启时中间件已把用户放到 `request.state`，矩阵要求 admin；关闭时 anonymous 主体在影子模式下放行）。对应改 `tests/` 里针对 `/api/audit` 401 的既有断言（若有）为新语义。`app.py` 在 security router 之后：

```python
from agenticops.web.routers import changes as _changes_router
app.include_router(_changes_router.router)
```

- [ ] **Step 5: 全局搜索与 Settings 开关**

`web/routers/search.py`（`fix_plans` 段之后）加 `change_requests` 段：`db.query(ChangeRequest).filter(func.lower(ChangeRequest.title).like(search_term)).limit(limit)` → `SearchResultItem(id, title, subtitle=description[:100], entity_type="change_request", status, parent_id=None, created_at)`，并把 `"change_requests"` 加进默认 `search_types`。

`web/app.py` 的 `api_get_settings`（:559）返回体加 `"change_management_enabled"`, `"change_auto_approve_standard"`, `"rbac_enforce"`；`api_update_settings`（:628）新增 `CHANGE_KEYS = {"change_auto_approve_standard", "rbac_enforce"}`，并入 `ALL_KEYS`，布尔校验后 `setattr(settings, k, v)` **并** `save_to_yaml({k: v})`（与 `ACP_KEYS` 同样持久化——这两个是安全开关，不能重启即丢）。`rbac_enforce` 变更后无需重载矩阵（`check` 每次读 `settings`）。

- [ ] **Step 6: 跑测试 + Commit**

```bash
python -m pytest tests/test_changes_api.py tests/test_fix_plan_hardening_api.py tests/test_web_schemas.py -q
git add src/agenticops/web/schemas.py src/agenticops/web/routers/changes.py src/agenticops/web/routers/audit.py src/agenticops/web/routers/search.py src/agenticops/web/app.py tests/test_changes_api.py
git commit -m "feat(api): /api/changes lifecycle endpoints, change timeline, /api/command-audits, settings toggles, search"
```

---

### Task 12: 统计 — `services/plan_stats_service.py` + `GET /api/plans/stats`

**Files:**
- Create: `src/agenticops/services/plan_stats_service.py`, `src/agenticops/web/routers/plans.py`
- Modify: `src/agenticops/web/app.py`（`include_router`）
- Test: `tests/test_plan_stats.py`

**Interfaces:**
- Produces: `plan_stats(start: datetime, end: datetime, kind: str = "all", bucket: str = "day") -> dict`，返回 spec §5 的结构：
  ```
  { "period": {"start", "end", "bucket"}, "kind",
    "totals": {"by_kind_status": {"fix": {...}, "change": {...}}, "open": n},
    "approvals": {"auto": n, "human": n, "rejected": n, "authz_denied": n, "authz_denied_shadow": n},
    "lead_time": {"request_to_approve_p50_s", "request_to_approve_p90_s", "approve_to_start_p50_s", "exec_duration_p50_s"},
    "outcomes": {"success_rate", "rollbacks", "needs_review"},
    "breakdown": {"by_actor": {"requesters": [...], "approvers": [...], "executors": [...]}, "by_risk": {}, "by_change_type": {}, "by_action_type": {}, "by_account": {}},
    "series": [{"bucket", "created", "completed", "failed"}],
    "commands": {"by_outcome": {}, "by_tool": {}} }
  ```
  `GET /api/plans/stats?period=7d|30d|90d&kind=all|fix|change&bucket=day|week`。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_plan_stats.py
from datetime import datetime, timedelta, timezone

import pytest
from starlette.testclient import TestClient

from agenticops.models import Base, ChangeRequest, CommandAudit, FixExecution, FixPlan, HealthIssue, RCAResult, get_session


@pytest.fixture
def db(tmp_path):
    import agenticops.models as models_mod
    import agenticops.audit.models  # noqa: F401
    from agenticops.config import settings
    models_mod._engine = None
    settings.database_url = f"sqlite:///{tmp_path}/stats.db"
    Base.metadata.create_all(models_mod.get_engine())
    s = get_session()
    yield s
    s.close()
    models_mod._engine = None


def _seed(db):
    from agenticops.audit.models import AuditLog
    now = datetime.now(timezone.utc)
    issue = HealthIssue(title="t", description="d", severity="low", source="t", status="resolved", resource_id="r"); db.add(issue); db.flush()
    rca = RCAResult(health_issue_id=issue.id, root_cause="x", confidence=0.9); db.add(rca); db.flush()
    fp = FixPlan(health_issue_id=issue.id, rca_result_id=rca.id, risk_level="L1", title="fix", summary="s", status="executed",
                 approved_by="agent:auto-pipeline", approved_at=now - timedelta(hours=1), created_at=now - timedelta(hours=2))
    db.add(fp); db.flush()
    db.add(FixExecution(fix_plan_id=fp.id, health_issue_id=issue.id, status="succeeded", executed_by="agent:executor",
                        started_at=now - timedelta(minutes=50), completed_at=now - timedelta(minutes=45), duration_ms=300000))
    cr1 = ChangeRequest(title="tag", description="d", requested_by="user:alice", status="completed", risk_level="L1",
                        effective_change_type="standard", action_type="tag", account_id=None,
                        requested_at=now - timedelta(hours=3), approved_at=now - timedelta(hours=2), approved_by="user:bob",
                        created_at=now - timedelta(hours=3), closed_at=now - timedelta(hours=1))
    cr2 = ChangeRequest(title="sg", description="d", requested_by="user:alice", status="planned", risk_level="L2",
                        effective_change_type="normal", action_type="network", created_at=now - timedelta(minutes=30))
    cr3 = ChangeRequest(title="old", description="d", requested_by="user:carol", status="failed", risk_level="L1",
                        created_at=now - timedelta(days=40), closed_at=now - timedelta(days=40))
    db.add_all([cr1, cr2, cr3]); db.flush()
    cp = FixPlan(plan_kind="change", change_request_id=cr1.id, risk_level="L1", title="cp", summary="s", status="executed",
                 approved_by="user:bob", approved_at=now - timedelta(hours=2), created_at=now - timedelta(hours=3))
    db.add(cp); db.flush()
    db.add(FixExecution(fix_plan_id=cp.id, status="succeeded", executed_by="user:bob", started_at=now - timedelta(hours=1, minutes=50),
                        completed_at=now - timedelta(hours=1), duration_ms=120000))
    db.add(AuditLog(action="change.approved", entity_type="change_request", entity_id=str(cr1.id), actor="user:bob"))
    db.add(AuditLog(action="plan.approved", entity_type="fix_plan", entity_id=str(fp.id), actor="agent:auto-pipeline"))
    db.add(AuditLog(action="authz.denied_shadow", entity_type="changerequest", entity_id="1", actor="user:alice"))
    db.add(CommandAudit(actor="agent:executor", tool="run_aws_cli", tier="write", command="aws ec2 create-tags", outcome="executed", change_request_id=cr1.id))
    db.add(CommandAudit(actor="cli:m", tool="run_on_host", tier="write", command="systemctl restart x", outcome="refused", reason="change_required"))
    db.commit()


def test_plan_stats_shape_and_numbers(db):
    from agenticops.services.plan_stats_service import plan_stats
    _seed(db)
    end = datetime.now(timezone.utc); start = end - timedelta(days=30)
    st = plan_stats(start, end, kind="all", bucket="day")
    assert st["totals"]["by_kind_status"]["fix"]["executed"] == 1
    assert st["totals"]["by_kind_status"]["change"]["completed"] == 1 and st["totals"]["by_kind_status"]["change"]["planned"] == 1
    assert "failed" not in st["totals"]["by_kind_status"]["change"]  # cr3 is outside the window
    assert st["totals"]["open"] == 1
    assert st["approvals"]["auto"] == 1 and st["approvals"]["human"] == 1 and st["approvals"]["authz_denied_shadow"] == 1
    assert st["lead_time"]["request_to_approve_p50_s"] == pytest.approx(3600, rel=0.05)
    assert st["outcomes"]["success_rate"] == 1.0 and st["outcomes"]["rollbacks"] == 0
    assert st["breakdown"]["by_actor"]["requesters"][0] == {"actor": "user:alice", "count": 2}
    assert st["breakdown"]["by_risk"]["L1"] >= 2 and st["breakdown"]["by_action_type"]["tag"] == 1
    assert st["commands"]["by_outcome"] == {"executed": 1, "refused": 1} and st["commands"]["by_tool"]["run_on_host"] == 1
    assert any(row["created"] >= 1 for row in st["series"])


def test_kind_filter(db):
    from agenticops.services.plan_stats_service import plan_stats
    _seed(db)
    end = datetime.now(timezone.utc); start = end - timedelta(days=30)
    st = plan_stats(start, end, kind="change")
    assert "fix" not in st["totals"]["by_kind_status"]


def test_stats_endpoint(db):
    from agenticops.web.app import app
    _seed(db)
    c = TestClient(app)
    r = c.get("/api/plans/stats?period=7d&kind=all&bucket=day")
    assert r.status_code == 200 and r.json()["period"]["bucket"] == "day"
    assert c.get("/api/plans/stats?period=1y").status_code == 422
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_plan_stats.py -q`
Expected: FAIL — `ModuleNotFoundError: agenticops.services.plan_stats_service`

- [ ] **Step 3: 实现**

```python
# src/agenticops/services/plan_stats_service.py
"""Plans & Changes statistics (MVP-2.6.0) — real-time aggregation, no rollup tables.

Sources: fix_plans (both kinds), change_requests, fix_executions, audit_logs, command_audits.
Percentiles are computed in Python (tables are small at MVP scale); time buckets reuse the
portable helper from cost_service.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from typing import Optional

from sqlalchemy import func

from agenticops.services.cost_service import _bucket_expr


def _pct(values: list[float], p: float) -> Optional[float]:
    if not values:
        return None
    vals = sorted(values)
    k = max(0, min(len(vals) - 1, int(round((p / 100.0) * (len(vals) - 1)))))
    return round(vals[k], 1)


def _secs(a: Optional[datetime], b: Optional[datetime]) -> Optional[float]:
    if a is None or b is None:
        return None
    return (b - a).total_seconds()


def _top(counter: Counter, n: int = 5) -> list[dict]:
    return [{"actor": k, "count": v} for k, v in counter.most_common(n)]


def plan_stats(start: datetime, end: datetime, kind: str = "all", bucket: str = "day") -> dict:
    from agenticops.audit.models import AuditLog
    from agenticops.models import (
        CHANGE_TERMINAL_STATUSES, ChangeRequest, CommandAudit, FixExecution, FixPlan, get_db_session,
    )

    kinds = ("fix", "change") if kind == "all" else (kind,)
    bexpr_fmt = {"day": "day", "week": "day"}.get(bucket, "day")
    with get_db_session() as db:
        plans = db.query(FixPlan).filter(FixPlan.created_at >= start, FixPlan.created_at < end,
                                         FixPlan.plan_kind.in_(kinds)).all()
        changes = db.query(ChangeRequest).filter(ChangeRequest.created_at >= start, ChangeRequest.created_at < end).all() \
            if "change" in kinds else []
        plan_ids = [p.id for p in plans]
        execs = db.query(FixExecution).filter(FixExecution.fix_plan_id.in_(plan_ids)).all() if plan_ids else []
        audits = db.query(AuditLog).filter(AuditLog.timestamp >= start, AuditLog.timestamp < end,
                                           AuditLog.action.in_(["plan.approved", "change.approved", "plan.rejected",
                                                                "change.rejected", "authz.denied", "authz.denied_shadow"])).all()
        cmds = db.query(CommandAudit.outcome, CommandAudit.tool, func.count(CommandAudit.id)) \
            .filter(CommandAudit.created_at >= start, CommandAudit.created_at < end) \
            .group_by(CommandAudit.outcome, CommandAudit.tool).all()
        # series: created per bucket (plans of the selected kinds + change requests), completed/failed (changes + fix plans)
        bexpr = _bucket_expr(FixPlan.created_at, bexpr_fmt)
        created_rows = db.query(bexpr, func.count(FixPlan.id)).filter(
            FixPlan.created_at >= start, FixPlan.created_at < end, FixPlan.plan_kind.in_(kinds)).group_by(bexpr).all()

        by_kind_status: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for p in plans:
            if p.plan_kind == "fix":
                by_kind_status["fix"][p.status] += 1
        for c in changes:
            by_kind_status["change"][c.status] += 1
        open_count = sum(1 for p in plans if p.plan_kind == "fix" and p.status not in ("executed", "failed", "rejected")) \
            + sum(1 for c in changes if c.status not in CHANGE_TERMINAL_STATUSES)

        approvals = Counter()
        for a in audits:
            if a.action in ("plan.approved", "change.approved"):
                approvals["auto" if (a.actor or "").startswith("agent:") else "human"] += 1
            elif a.action in ("plan.rejected", "change.rejected"):
                approvals["rejected"] += 1
            elif a.action == "authz.denied":
                approvals["authz_denied"] += 1
            elif a.action == "authz.denied_shadow":
                approvals["authz_denied_shadow"] += 1

        req_to_approve = [s for s in (_secs(c.requested_at or c.created_at, c.approved_at) for c in changes) if s is not None]
        req_to_approve += [s for s in (_secs(p.created_at, p.approved_at) for p in plans if p.plan_kind == "fix") if s is not None]
        approve_to_start, exec_durations = [], []
        plan_by_id = {p.id: p for p in plans}
        for e in execs:
            p = plan_by_id.get(e.fix_plan_id)
            if p is not None:
                s = _secs(p.approved_at, e.started_at)
                if s is not None and s >= 0:
                    approve_to_start.append(s)
            if e.duration_ms:
                exec_durations.append(e.duration_ms / 1000.0)

        succeeded = sum(1 for e in execs if e.status == "succeeded")
        failed = sum(1 for e in execs if e.status in ("failed", "rolled_back"))
        rollbacks = sum(1 for e in execs if e.status == "rolled_back")
        needs_review = sum(1 for c in changes if c.status == "needs_review")
        success_rate = round(succeeded / (succeeded + failed), 3) if (succeeded + failed) else None

        requesters = Counter(c.requested_by for c in changes)
        approvers = Counter(x for x in ([c.approved_by for c in changes] + [p.approved_by for p in plans if p.plan_kind == "fix"]) if x)
        executors = Counter(e.executed_by for e in execs if e.executed_by)
        by_risk = Counter([p.risk_level for p in plans if p.plan_kind == "fix"] + [c.risk_level for c in changes if c.risk_level])
        by_change_type = Counter(c.effective_change_type or c.requested_change_type for c in changes)
        by_action_type = Counter(c.action_type for c in changes if c.action_type)
        by_account = Counter(str(c.account_id) for c in changes if c.account_id)

        created_by_bucket = {str(b): n for b, n in created_rows}
        done_by_bucket: dict[str, dict[str, int]] = defaultdict(lambda: {"completed": 0, "failed": 0})
        fmt = "%Y-%m-%d"
        for c in changes:
            if c.closed_at and c.status in ("completed",):
                done_by_bucket[c.closed_at.strftime(fmt)]["completed"] += 1
            elif c.closed_at and c.status in ("failed", "rolled_back"):
                done_by_bucket[c.closed_at.strftime(fmt)]["failed"] += 1
        for p in plans:
            if p.plan_kind == "fix" and p.updated_at and p.status in ("executed", "failed"):
                done_by_bucket[p.updated_at.strftime(fmt)]["completed" if p.status == "executed" else "failed"] += 1
        buckets = sorted(set(created_by_bucket) | set(done_by_bucket))
        series = [{"bucket": b, "created": created_by_bucket.get(b, 0), **done_by_bucket.get(b, {"completed": 0, "failed": 0})} for b in buckets]

        cmd_by_outcome, cmd_by_tool = Counter(), Counter()
        for outcome, tool, n in cmds:
            cmd_by_outcome[outcome] += n
            cmd_by_tool[tool] += n

    return {
        "period": {"start": start.isoformat(), "end": end.isoformat(), "bucket": bucket},
        "kind": kind,
        "totals": {"by_kind_status": {k: dict(v) for k, v in by_kind_status.items()}, "open": open_count},
        "approvals": {"auto": approvals["auto"], "human": approvals["human"], "rejected": approvals["rejected"],
                      "authz_denied": approvals["authz_denied"], "authz_denied_shadow": approvals["authz_denied_shadow"]},
        "lead_time": {"request_to_approve_p50_s": _pct(req_to_approve, 50), "request_to_approve_p90_s": _pct(req_to_approve, 90),
                      "approve_to_start_p50_s": _pct(approve_to_start, 50), "exec_duration_p50_s": _pct(exec_durations, 50)},
        "outcomes": {"success_rate": success_rate, "rollbacks": rollbacks, "needs_review": needs_review},
        "breakdown": {"by_actor": {"requesters": _top(requesters), "approvers": _top(approvers), "executors": _top(executors)},
                      "by_risk": dict(by_risk), "by_change_type": dict(by_change_type), "by_action_type": dict(by_action_type),
                      "by_account": dict(by_account)},
        "series": series,
        "commands": {"by_outcome": dict(cmd_by_outcome), "by_tool": dict(cmd_by_tool)},
    }
```

`routers/plans.py`：

```python
"""Plans & Changes statistics API (MVP-2.6.0)."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Query

router = APIRouter(tags=["plans"])

_PERIOD = {"7d": timedelta(days=7), "30d": timedelta(days=30), "90d": timedelta(days=90)}


@router.get("/api/plans/stats")
async def api_plan_stats(
    period: str = Query("30d", pattern="^(7d|30d|90d)$"),
    kind: str = Query("all", pattern="^(all|fix|change)$"),
    bucket: str = Query("day", pattern="^(day|week)$"),
):
    from agenticops.services.plan_stats_service import plan_stats
    end = datetime.now(timezone.utc)
    return plan_stats(end - _PERIOD[period], end, kind=kind, bucket=bucket)
```

`app.py` 注册 `from agenticops.web.routers import plans as _plans_router; app.include_router(_plans_router.router)`。

- [ ] **Step 4: 跑测试 + Commit**

```bash
python -m pytest tests/test_plan_stats.py -q
git add src/agenticops/services/plan_stats_service.py src/agenticops/web/routers/plans.py src/agenticops/web/app.py tests/test_plan_stats.py
git commit -m "feat(stats): plans & changes statistics service and GET /api/plans/stats"
```

---

### Task 13: Pipeline 端到端（mock SRE / Executor）+ 全量回归

**Files:**
- Test: `tests/test_change_pipeline.py`

**Interfaces:** 无新符号。这是 Plan B 的验收测试：request → review（假 SRE 用真实工具）→ planned → approve → execute（假 Executor 用真实 `save_execution_result`，经 `ExecutorService._run_executor`）→ completed；以及 auto-approve、needs_review、needs_clarification→clarify、policy block、看门狗回退五条支路。

- [ ] **Step 1: 写测试**

```python
# tests/test_change_pipeline.py
"""Change Management closed loop with mocked agents (SRE / Executor replaced by functions that call the REAL tools)."""
import json
from unittest.mock import patch

import pytest

from agenticops.auth.actor import Actor
from agenticops.models import Base, ChangeRequest, CloudAccount, CloudResource, FixExecution, FixPlan, PipelineEvent, get_session

ALICE = Actor("user", "alice", 1, ("read", "write"))
BOB = Actor("user", "bob", 2, ("read", "write"))


@pytest.fixture
def db(tmp_path):
    import agenticops.models as models_mod
    import agenticops.audit.models  # noqa: F401
    from agenticops.config import settings
    models_mod._engine = None
    settings.database_url = f"sqlite:///{tmp_path}/pipe.db"
    Base.metadata.create_all(models_mod.get_engine())
    s = get_session()
    acct = CloudAccount(name="dev", provider="aws", is_enabled=True, credentials={}, regions=["ap-southeast-1"]); s.add(acct); s.flush()
    s.add(CloudResource(account_id=acct.id, provider="aws", region="ap-southeast-1", resource_type="EC2Instance", resource_id="i-0abc", name="web"))
    s.commit()
    yield s
    s.close()
    models_mod._engine = None


def fake_sre_review(change_request_id: int) -> str:
    """What a well-behaved SRE Mode C run does, using the real tools."""
    from agenticops.tools.change_tools import evaluate_change_policy, ground_change_targets, submit_change_review
    from agenticops.tools.metadata_tools import save_fix_plan
    g = json.loads(ground_change_targets(change_request_id))
    if g["unresolved"]:
        return submit_change_review(change_request_id, "needs_clarification", reasons="unresolved: " + ", ".join(g["unresolved"]))
    evaluate_change_policy(change_request_id, "L1", "tag")
    save_fix_plan(plan_kind="change", change_request_id=change_request_id, risk_level="L1", title="Tag i-0abc", summary="add Env=prod",
                  steps=json.dumps([{"action": "tag", "command": "aws ec2 create-tags --resources i-0abc --tags Key=Env,Value=prod"}]),
                  rollback_plan=json.dumps({"steps": [{"command": "aws ec2 delete-tags --resources i-0abc --tags Key=Env"}]}),
                  post_checks=json.dumps([{"check": "tag present", "command": "aws ec2 describe-tags --filters Name=resource-id,Values=i-0abc"}]))
    return submit_change_review(change_request_id, "approved_for_planning", "L1", "tag", "single instance tag; reversible")


def make_fake_executor(post_results, status="succeeded"):
    def fake_executor(fix_plan_id: int) -> str:
        from agenticops.tools.metadata_tools import get_approved_fix_plan, save_execution_result
        plan = json.loads(get_approved_fix_plan(fix_plan_id))
        assert plan["plan_kind"] == "change"
        return save_execution_result(fix_plan_id=fix_plan_id, health_issue_id=None, status=status,
                                     step_results=json.dumps([{"step_index": 0, "command": plan["steps"][0]["command"], "status": "ok"}]),
                                     post_check_results=json.dumps(post_results))
    return fake_executor


def _run_executor_for(cr_id):
    from agenticops.services.executor_service import ExecutorService
    s = get_session()
    ex = s.query(FixExecution).join(FixPlan).filter(FixPlan.change_request_id == cr_id).order_by(FixExecution.id.desc()).first()
    ex_id, plan_id = ex.id, ex.fix_plan_id
    ex.status = "running"; s.commit(); s.close()
    ExecutorService()._run_executor(ex_id, plan_id)


@pytest.fixture
def quiet():
    with patch("agenticops.services.change_service.notify_change_requested"), \
         patch("agenticops.services.change_service.notify_change_pending_approval"), \
         patch("agenticops.services.change_service.notify_change_result"):
        yield


def test_main_path_request_review_approve_execute_complete(db, quiet):
    from agenticops.config import settings
    from agenticops.services import change_service as cs
    cr = cs.create_change_request(source="chat", actor=ALICE, title="Tag web", description="add Env=prod to i-0abc",
                                  account_name="dev", targets=["i-0abc"], start_review=False)
    with patch("agenticops.agents.sre_agent.sre_agent_review_change", side_effect=fake_sre_review):
        cs.start_review(cr["id"], sync=True)
    c = cs.get_change(cr["id"])
    assert c["status"] == "planned" and c["risk_level"] == "L1" and c["effective_change_type"] == "standard"
    # no write command may have executed before approval
    from agenticops.models import CommandAudit
    assert db.query(CommandAudit).filter_by(change_request_id=cr["id"], outcome="executed").count() == 0
    cs.approve(cr["id"], actor=BOB, reason="reviewed")
    with patch.object(settings, "executor_enabled", True):
        cs.request_execution(cr["id"], actor=BOB)
    with patch("agenticops.agents.executor_agent.executor_agent", side_effect=make_fake_executor([{"check": "tag present", "status": "pass"}])):
        _run_executor_for(cr["id"])
    final = cs.get_change(cr["id"])
    assert final["status"] == "completed" and final["closed_at"]
    from agenticops.audit.models import AuditLog
    actions = [a.action for a in db.query(AuditLog).filter_by(entity_type="change_request", entity_id=str(cr["id"]))]
    for expected in ("change.requested", "change.reviewed", "change.approved", "change.execution_started", "change.completed"):
        assert expected in actions
    events = [e.event_type for e in db.query(PipelineEvent).filter_by(change_request_id=cr["id"])]
    assert "policy_decision" in events and "execution_completed" in events


def test_auto_approve_branch(db, quiet):
    from agenticops.config import settings
    from agenticops.services import change_service as cs
    cr = cs.create_change_request(source="web", actor=ALICE, title="Tag", description="d", account_name="dev", targets=["i-0abc"], start_review=False)
    with patch.object(settings, "change_auto_approve_standard", True), patch.object(settings, "executor_enabled", True), \
         patch("agenticops.agents.sre_agent.sre_agent_review_change", side_effect=fake_sre_review):
        cs.start_review(cr["id"], sync=True)
    c = cs.get_change(cr["id"])
    assert c["status"] == "executing" and c["approved_by"] == "agent:auto-pipeline" and "change-standard-low-risk" in c["approval_reason"]
    assert db.query(FixExecution).count() == 1


def test_needs_review_when_post_checks_missing(db, quiet):
    from agenticops.config import settings
    from agenticops.services import change_service as cs
    cr = cs.create_change_request(source="web", actor=ALICE, title="Tag", description="d", account_name="dev", targets=["i-0abc"], start_review=False)
    with patch("agenticops.agents.sre_agent.sre_agent_review_change", side_effect=fake_sre_review):
        cs.start_review(cr["id"], sync=True)
    cs.approve(cr["id"], actor=BOB, reason="ok")
    with patch.object(settings, "executor_enabled", True):
        cs.request_execution(cr["id"], actor=BOB)
    with patch("agenticops.agents.executor_agent.executor_agent", side_effect=make_fake_executor([])):
        _run_executor_for(cr["id"])
    assert cs.get_change(cr["id"])["status"] == "needs_review"
    out = cs.resolve_review(cr["id"], actor=BOB, outcome="completed", reason="verified in console")
    assert out["status"] == "completed"


def test_needs_clarification_then_clarify(db, quiet):
    from agenticops.services import change_service as cs
    cr = cs.create_change_request(source="web", actor=ALICE, title="Tag", description="tag the web box", account_name="dev",
                                  targets=["web-box-typo"], start_review=False)
    with patch("agenticops.agents.sre_agent.sre_agent_review_change", side_effect=fake_sre_review):
        cs.start_review(cr["id"], sync=True)
    assert cs.get_change(cr["id"])["status"] == "needs_clarification"
    with cs._session() as s:
        row = s.get(ChangeRequest, cr["id"]); row.target_hints = ["i-0abc"]
    with patch("agenticops.services.change_service.start_review") as sr:
        cs.clarify(cr["id"], actor=ALICE, message="I meant i-0abc")
    sr.assert_called_once()


def test_policy_block_rejects(db, quiet):
    from agenticops.services import change_service as cs
    from agenticops.services.policy_engine import PolicyDecision
    cr = cs.create_change_request(source="web", actor=ALICE, title="Tag", description="d", account_name="dev", targets=["i-0abc"], start_review=False)
    with patch("agenticops.agents.sre_agent.sre_agent_review_change", side_effect=fake_sre_review), \
         patch.object(cs, "evaluate_policy", return_value=PolicyDecision(action="block", rule_name="freeze-window-block", reasons=["freeze"])):
        cs.start_review(cr["id"], sync=True)
    c = cs.get_change(cr["id"])
    assert c["status"] == "rejected" and c["policy_rule"] == "freeze-window-block"


def test_watchdog_rollback_when_sre_never_answers(db, quiet):
    from agenticops.services import change_service as cs
    cr = cs.create_change_request(source="web", actor=ALICE, title="Tag", description="d", account_name="dev", targets=["i-0abc"], start_review=False)
    with patch("agenticops.agents.sre_agent.sre_agent_review_change", return_value="…"):
        cs.start_review(cr["id"], sync=True)  # returned without a verdict → rolled back to draft
    assert cs.get_change(cr["id"])["status"] == "draft"
    with patch.object(cs.threading, "Thread"), patch.object(cs.threading, "Timer"):
        out = cs.restart_review(cr["id"], actor=ALICE)  # human can retry from the UI (thread not really started here)
    assert out["status"] == "under_review"
```

- [ ] **Step 2: 跑测试**

Run: `python -m pytest tests/test_change_pipeline.py -q`
Expected: 6 PASS。任何失败都指向前面 Task 的真实缺陷——修在对应模块，不改测试期望。

- [ ] **Step 3: 全量回归 + 提示词预算 + 服务启动冒烟**

```bash
python -m pytest tests/ -q > /tmp/pytest-planB.log 2>&1; tail -15 /tmp/pytest-planB.log
python -m pytest tests/test_prompt_budget.py -q
timeout 25 uvicorn agenticops.web.app:app --port 8099 > /tmp/planB-uvicorn.log 2>&1 || true
grep -E "Application startup complete|Traceback|Error" /tmp/planB-uvicorn.log | head
curl -s localhost:8099/api/changes >/dev/null 2>&1 || true
```
Expected: 只有 `test_web_tools` 的 DNS 假失败；启动无 Traceback。

- [ ] **Step 4: Commit + 执行记录**

```bash
git add tests/test_change_pipeline.py docs/superpowers/plans/2026-09-17-change-management-p1-b-backend.md
git commit -m "test(change): closed-loop pipeline with mocked SRE/Executor; Plan B execution record"
```

## 执行记录

（执行时追加：日期 · 全量测试结果 · 冒烟结果 · 提示词金标新值）
