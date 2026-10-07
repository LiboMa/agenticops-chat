# Issue / Change 统一工单模板（方案 A）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 问题和变更共用一套详情模板（一个状态行 + 阶段卡 + 右栏），两个列表共用一个表格组件，资源独立进侧栏、信号改为 `/app/signals`；打开任何一张工单，一屏内回答「在哪一步、为什么停在这里、下一步谁做什么」。

**Architecture:** 判断逻辑全部进 `lib/*.ts` 纯函数（`issuePhases` / `changePhases` / `activity` / `verdict` / `rcaQuality` / `workitemRoutes` …），由 vitest 覆盖；组件只接 props 渲染，页面负责取数和组装。后端只加一个只读设置字段。四期 A1→A4 依次做，每期结束全部门禁通过。

**Tech Stack:** React 18 + TypeScript、TanStack Query、react-router、Tailwind、d3-force（已有）、vitest；后端 FastAPI + pytest（仅 Task 1）。

**Spec:** `docs/superpowers/specs/2026-10-04-issue-change-workitem-template-design.md`（主人 2026-10-04 批准，「go ahead, achieve all」= A1–A4）。线框：`docs/design/2026-10-03-issue-change-ui-proposals.html` 的「方案 A」页（A-1…A-4）。

## Global Constraints

- **工作目录**：worktree `/Users/malibo/MyDev/AgenticOps/.worktrees/mvp-2.6.1`（分支 `MVP-2.6.1`）。**绝不改主仓 `/Users/malibo/MyDev/AgenticOps`**。前端目录 `src/agenticops/web/frontend`，下文 `FE=` 指它。
- **前端门禁（每个前端 Task 的最后一步都跑）**：`cd $FE && npx tsc --noEmit && npx vitest run src && npm run build`，然后**还原构建产物**：`cd /Users/malibo/MyDev/AgenticOps/.worktrees/mvp-2.6.1 && git checkout -- src/agenticops/web/frontend/dist src/agenticops/web/frontend/tsconfig.tsbuildinfo && git clean -fdq src/agenticops/web/frontend/dist`。
- **后端测试**：`cd /Users/malibo/MyDev/AgenticOps/.worktrees/mvp-2.6.1 && PYTHONPATH=src /Users/malibo/MyDev/AgenticOps/.venv/bin/python -m pytest <tests> -q`；全量重定向到文件：`... -m pytest tests/ -q -p no:cacheprovider > /tmp/pytest-wi.log 2>&1; tail -3 /tmp/pytest-wi.log`，跑完 `git checkout -- agent-memory skills`。基线 **6357 passed / 85 skipped**，另有 1 个已知本机 DNS 假失败 `test_web_tools::test_invalid_headers_json`。
- **不新增依赖**（npm 与 pip 都不加）；前端没有 Testing Library / jsdom，**不为它加**：测试只测纯函数（含视图模型 `issueDetailModel` / `changeDetailModel`）。
- **不新增端点**；唯一后端改动是 Task 1 的只读设置字段。
- **文案**：所有可见文字走 `useLocale().t(key)`，键同时加进 `src/locales/zh.json` 与 `src/locales/en.json`（`__tests__/locales.test.ts` 的 parity 测试必须过）；**数据本身（RCA 原文、命令、错误原文）不翻译**。占位符用 `{name}`，由调用方 `.replace("{name}", v)`（项目现有写法）。
- **弹层规则**：所有 overlay / 面板 / 对话框 `animate-[slideInRight_0.2s_ease-out]` 入场并能 ESC 关闭；复用 `components/plans/ReasonDialog`（已满足）与 `useConfirm`。
- **Git**：只 `git add` 明确路径；**永不** add `agent-memory/`、`skills/`、`RAW-Idea*`、`dist/`、`tsconfig.tsbuildinfo`、`data/`；不 amend / reset / rebase / bare stash；提交信息结尾 `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`；**只本地提交，不推送**。
- **TDD**：每个带纯函数的 Task 先写失败的测试、确认因「缺函数/断言不符」而失败，再实现；红绿可在同一提交（本计划约定一个 Task 一个提交，测试与实现同提交，除非 Task 另说）。

## 计划层面的裁定（与 spec 的差异，均不改变 spec 的结果）

- **R1**：spec §2 把 P14（问题侧「Execute」改名「重试执行」）列在 A1，P15（问题列表筛选压成一行）列在 A1。两者所在的代码（`IssueDetail.tsx` 的 FixPlanTab、`IssuesAndPlans.tsx` 的筛选行）分别在 A2 / A4 整体重写，在 A1 先改一遍是白做。→ P14 并入 Task 11，P15 并入 Task 14。同理 P2 中「IssueRow 的 STATUS_LABELS」并入 Task 14（IssueRow 被 WorkItemTable 取代），「IssueActionBar 的确认文案」不做（IssueActionBar 在 Task 11 删除）。
- **R2**：列表接口（`GET /api/anomalies` 的 `Anomaly`）不带 RCA 置信度和最新运行。spec 不新增端点/字段，所以列表的「等谁 / 下一步」用**同一个** `issuePhases`，但以「列表模式」调用（`rca: undefined`）：`root_cause_identified` 显示「等你：复核根因或生成方案」，`fix_executed` 显示「等你：验收或确认结果」。详情页给全输入，得到精确结果。spec §1 第 2 条「列表和详情同一函数」照旧成立。
- **R3**：列表行的现有快捷操作（悬停出现的 解决 / 确认 / 忽略 / 重新打开）与安全问题的「打开安全页」链接是现有行为，spec §7 漏列；WorkItemTable 提供可选的 `rowActions` 渲染位，问题列表保留它们。
- **R4**：文档在 Task 16 一次更新（四期都是本地提交、最后一起部署，分期写文档只会改四遍同一段）。

## Review Focus

1. **没有 RCA 的问题**（RCA 端点 404 / 返回空）：页面不崩，① 显示「进行中」或「未运行」，主按钮按 §4 表（无主按钮，「⋯」有「运行 RCA」）。→ Task 8 测试 `issuePhases` 的 `rca: null` 分支；Task 11 的 `issueDetailModel` 测试覆盖无 RCA 输入。
2. **同一问题多个方案**（v1 rejected、v2 pending_approval）：批准作用于最新的非终态方案，PlanView 显示它，旧版本列在「其它版本」。→ Task 8 测试 `currentFixPlan`。
3. **认证关闭时的修复批准**：现有 ReasonDialog 里的「claimed approver」输入框（`!isAuthenticated` 时）必须保留。→ Task 11 Step「保留行为清单」第 8 条，在 review 包里核对。
4. **未知 / 冲突的 URL**：`#foo` 未知锚点忽略；`?tab=` 与 `#` 同时存在时 `?tab=` 映射一次后被 `replace` 掉；旧 `?tab=issue`（2.6.1 之前）映射到 `#diagnose`。→ Task 8 测试 `workitemRoutes`。
5. **未知的时间线事件类型 / 畸形 detail**（字符串 JSON、数组、null）：`activity` 用通用句子，不抛错、不显示 `[object Object]`。→ Task 7 测试。

---

## File Structure

| 文件 | 职责 | Task |
|---|---|---|
| `src/agenticops/web/app.py`（GET /api/settings） | +`rca_min_confidence_for_autofix` 只读 | 1 |
| `$FE/src/hooks/useSettings.ts` | `AppSettings` +字段，`SettingsPatch` 排除它 | 1 |
| `$FE/src/lib/issueStatus.ts`（新） | `ISSUE_STATUSES` 常量 | 2 |
| `$FE/src/components/ui/IssueStatusBadge.tsx` | 文案走 locale | 2 |
| `$FE/src/lib/rcaQuality.ts`（新） | 置信度推导、闸门、质量徽章、未核实引用 | 3 |
| `$FE/src/lib/issueDetail.ts` | +`factRows`；`anchorBadge` 接受资源名 | 4 |
| `$FE/src/lib/localGraph.ts` | +`compactLocalGraph` | 5 |
| `$FE/src/components/graph/LocalGraph.tsx` | +`compact` 模式与「显示全部 N」 | 5 |
| `$FE/src/lib/changeStepper.ts`、`components/plans/ChangeStepper.tsx` | 终态在结局处收尾 | 6 |
| `$FE/src/lib/changeDetail.ts` | 终态 → 下一步「复制为新变更」 | 6 |
| `$FE/src/lib/activity.ts`（新）、`components/workitem/ActivityList.tsx`（新） | 可读时间线 | 7 |
| `$FE/src/lib/issuePhases.ts`（新）、`lib/workitemRoutes.ts`（新） | 问题阶段模型、旧链接映射 | 8 |
| `$FE/src/components/workitem/{StatusLine,PhaseCard,FactsRail}.tsx`（新）、`components/plans/PlanView.tsx`（新）、`lib/plans.ts` | 模板组件、共享方案视图 | 9 |
| `$FE/src/lib/verdict.ts`（新）、`components/issue/VerdictBlock.tsx`（新） | 「你的判断」 | 10 |
| `$FE/src/pages/IssueDetail.tsx`（重写）、`lib/issueDetailModel.ts`（新） | 问题详情套模板 | 11 |
| `$FE/src/lib/changePhases.ts`（新）、`lib/changeDetailModel.ts`（新） | 变更阶段模型 | 12 |
| `$FE/src/pages/ChangeDetail.tsx`（重写） | 变更详情套模板 | 13 |
| `$FE/src/components/ui/WorkItemTable.tsx`（新）、`lib/workItems.ts`（新）、`pages/IssuesAndPlans.tsx`、`components/plans/ChangePlansTab.tsx` | 统一列表 | 14 |
| `$FE/src/App.tsx`、`components/layout/NavItems.tsx`、`pages/Resources.tsx`（新）、`pages/Signals.tsx`（新） | 信息架构 | 15 |
| 删除未用组件；`CLAUDE.md`、`docs/WORKFLOW.md`、`docs/MVP-2.6.1-RELEASE.md`、README 双语（若涉及） | 收尾与文档 | 16 |

---

# A1 — 公共修复

### Task 1: 设置接口下发自动修复置信度阈值（只读）

**Files:**
- Modify: `src/agenticops/web/app.py`（`GET /api/settings` 的返回 dict，紧挨 `"policy_graph_impact_enforce"` 一行）
- Modify: `$FE/src/hooks/useSettings.ts`
- Test: `tests/test_changes_api.py`（紧挨 `test_settings_expose_graph_impact_enforce_read_only`）

**Interfaces:**
- Produces: `GET /api/settings` → `"rca_min_confidence_for_autofix": float`；前端 `AppSettings.rca_min_confidence_for_autofix: number`（只读，不进 `SettingsPatch`）。Task 3/8/11 读它。

- [ ] **Step 1: 写失败的测试**

```python
def test_settings_expose_rca_autofix_threshold_read_only(client, settings_io):
    """IssueDetail explains a paused auto-fix with the same threshold the post-RCA gate uses."""
    from agenticops.config import settings
    with patch.object(settings, "rca_min_confidence_for_autofix", 0.6):
        assert client.get("/api/settings").json()["rca_min_confidence_for_autofix"] == 0.6
        r = client.patch("/api/settings", json={"rca_min_confidence_for_autofix": 0.1})
        assert r.status_code == 400 and settings.rca_min_confidence_for_autofix == 0.6
    settings_io.assert_not_called()
```

- [ ] **Step 2: 跑测试确认失败**：`... -m pytest tests/test_changes_api.py -q -k rca_autofix_threshold` → FAIL（KeyError / assert）。
- [ ] **Step 3: 实现**：在 `GET /api/settings` 返回 dict 的 `"policy_graph_impact_enforce": ...,` 之后加

```python
        # Read-only: the post-RCA gate's threshold, so IssueDetail can say why auto-fix paused (2026-10-04 spec §8)
        "rca_min_confidence_for_autofix": settings.rca_min_confidence_for_autofix,
```

  PATCH 不改（它对白名单外的键返回 400，测试守住）。`useSettings.ts`：`AppSettings` 加 `rca_min_confidence_for_autofix: number; // read-only: the post-RCA auto-fix gate`；`SettingsPatch` 的 `Omit<…>` 联合加 `| "rca_min_confidence_for_autofix"`，并在其上方注释的只读字段清单里补上它。
- [ ] **Step 4: 跑测试确认通过**：同上 → PASS；再跑 `tests/test_changes_api.py` 整个文件 → 全过。
- [ ] **Step 5: 前端门禁**（tsc / vitest / build，见 Global Constraints）。
- [ ] **Step 6: Commit**：`git add src/agenticops/web/app.py src/agenticops/web/frontend/src/hooks/useSettings.ts tests/test_changes_api.py && git commit -m "feat(settings): expose rca_min_confidence_for_autofix read-only for the issue page"`（+ Co-Authored-By）。

### Task 2: 问题状态文案走 locale（P2 的徽章部分）

**Files:**
- Create: `$FE/src/lib/issueStatus.ts`
- Modify: `$FE/src/components/ui/IssueStatusBadge.tsx`、`$FE/src/locales/{zh,en}.json`
- Test: `$FE/src/__tests__/issueStatus.test.ts`

**Interfaces:**
- Produces: `export const ISSUE_STATUSES: readonly IssueStatus[]`；locale 键 `issues.status.<status>`（10 个）。Task 14 的列表与 Task 11 的状态行都用这组键。

- [ ] **Step 1: 写失败的测试**

```ts
import { describe, it, expect } from "vitest";
import en from "@/locales/en.json";
import zh from "@/locales/zh.json";
import { ISSUE_STATUSES } from "@/lib/issueStatus";

describe("ISSUE_STATUSES", () => {
  it("lists every IssueStatus once, and each has a label in both locales", () => {
    expect(new Set(ISSUE_STATUSES).size).toBe(ISSUE_STATUSES.length);
    expect([...ISSUE_STATUSES].sort()).toEqual([
      "acknowledged", "dismissed", "fix_approved", "fix_executed", "fix_executing", "fix_planned",
      "investigating", "open", "resolved", "root_cause_identified",
    ]);
    for (const s of ISSUE_STATUSES) {
      expect((en as Record<string, string>)[`issues.status.${s}`], s).toBeTruthy();
      expect((zh as Record<string, string>)[`issues.status.${s}`], s).toBeTruthy();
    }
  });
});
```

- [ ] **Step 2: 跑测试确认失败**：`cd $FE && npx vitest run src/__tests__/issueStatus.test.ts` → FAIL（模块不存在）。
- [ ] **Step 3: 实现** `lib/issueStatus.ts`：

```ts
import type { IssueStatus } from "@/api/types";

/** Every HealthIssue status (models.HealthIssue, 10 states); a label lives at `issues.status.<status>`. */
export const ISSUE_STATUSES: readonly IssueStatus[] = [
  "open", "investigating", "acknowledged", "root_cause_identified", "fix_planned",
  "fix_approved", "fix_executing", "fix_executed", "resolved", "dismissed",
];
```

  locale（en / zh）：

| 键 | en | zh |
|---|---|---|
| `issues.status.open` | Open | 已打开 |
| `issues.status.investigating` | Investigating | 调查中 |
| `issues.status.acknowledged` | Acknowledged | 已确认 |
| `issues.status.root_cause_identified` | Root cause found | 已找到根因 |
| `issues.status.fix_planned` | Fix planned | 已有修复方案 |
| `issues.status.fix_approved` | Fix approved | 修复已批准 |
| `issues.status.fix_executing` | Fixing | 修复执行中 |
| `issues.status.fix_executed` | Fix executed | 修复已执行 |
| `issues.status.resolved` | Resolved | 已解决 |
| `issues.status.dismissed` | Dismissed | 已忽略 |

  `IssueStatusBadge.tsx`：删掉 `LABELS` 常量，组件内 `const { t } = useLocale();`，文字改 `{t(\`issues.status.${status}\`)}`（`import { useLocale } from "@/i18n/LocaleContext"`）。`STYLES` 不变。
- [ ] **Step 4: 跑测试确认通过** → PASS；`npx vitest run src/__tests__/locales.test.ts` → PASS。
- [ ] **Step 5: 前端门禁**。
- [ ] **Step 6: Commit**：`feat(web): issue status labels come from the locale`（只 add 上面 4 个文件）。

### Task 3: RCA 质量与置信度说人话（P5 解释、P6、P16）

**Files:**
- Create: `$FE/src/lib/rcaQuality.ts`
- Modify: `$FE/src/pages/IssueDetail.tsx`（`RcaSection`：徽章、置信度条、Model 行）、`$FE/src/locales/{zh,en}.json`
- Test: `$FE/src/__tests__/rcaQuality.test.ts`

**Interfaces:**
- Consumes: `AppSettings.rca_min_confidence_for_autofix`（Task 1）。
- Produces（Task 8/10/11 用）：

```ts
export const EVIDENCE_PENALTY = 0.6;   // mirrors services/rca_quality.EVIDENCE_PENALTY
export const CRITIC_PENALTY = 0.5;     // mirrors services/rca_quality.CRITIC_PENALTY
export interface ConfidenceBreakdown { raw: number; final: number; evidencePenalty: boolean; criticPenalty: boolean; threshold: number | null; gatePassed: boolean | null }
export function confidenceBreakdown(rca: Pick<RCAResult, "confidence" | "evidence_verified" | "critic_verdict">, threshold: number | null | undefined): ConfidenceBreakdown
export type QualityTone = "ok" | "warn" | "bad";
export interface QualityBadge { key: string; tone: QualityTone; hint: string | null }
export function qualityBadges(rca: Pick<RCAResult, "evidence_verified" | "critic_verdict" | "critic_notes">): QualityBadge[]
export function unmatchedRefs(events: Pick<PipelineEvent, "event_type" | "detail" | "created_at">[] | undefined): string[]
```

- [ ] **Step 1: 写失败的测试**

```ts
import { describe, it, expect } from "vitest";
import { confidenceBreakdown, qualityBadges, unmatchedRefs } from "@/lib/rcaQuality";

describe("confidenceBreakdown", () => {
  it("I#1: 0.95 × 0.6 (evidence not verified) = 0.57, below 0.6 → gate not passed; a weak critic costs nothing", () => {
    const b = confidenceBreakdown({ confidence: 0.57, evidence_verified: false, critic_verdict: "weak" }, 0.6);
    expect(b).toEqual({ raw: 0.95, final: 0.57, evidencePenalty: true, criticPenalty: false, threshold: 0.6, gatePassed: false });
  });
  it("a refuted critic halves the confidence and fails the gate whatever the number", () => {
    const b = confidenceBreakdown({ confidence: 0.45, evidence_verified: true, critic_verdict: "refuted" }, 0.3);
    expect(b.raw).toBe(0.9);
    expect(b.criticPenalty).toBe(true);
    expect(b.gatePassed).toBe(false);
  });
  it("both penalties stack; raw is capped at 1", () => {
    expect(confidenceBreakdown({ confidence: 0.3, evidence_verified: false, critic_verdict: "refuted" }, 0.6).raw).toBe(1);
  });
  it("no penalty: raw = final; at the threshold the gate passes", () => {
    const b = confidenceBreakdown({ confidence: 0.6, evidence_verified: true, critic_verdict: "supported" }, 0.6);
    expect(b.raw).toBe(0.6);
    expect(b.gatePassed).toBe(true);
  });
  it("unknown threshold (settings not loaded) → gatePassed null; a missing confidence reads 0", () => {
    const b = confidenceBreakdown({ confidence: undefined as unknown as number, evidence_verified: null, critic_verdict: null }, undefined);
    expect(b.final).toBe(0);
    expect(b.threshold).toBeNull();
    expect(b.gatePassed).toBeNull();
  });
});

describe("qualityBadges", () => {
  it("plain-language keys and tones, the critic's notes as the hint", () => {
    expect(qualityBadges({ evidence_verified: false, critic_verdict: "weak", critic_notes: "thin evidence" })).toEqual([
      { key: "rca.quality.evidenceUnverified", tone: "bad", hint: null },
      { key: "rca.quality.critic.weak", tone: "warn", hint: "thin evidence" },
    ]);
    expect(qualityBadges({ evidence_verified: true, critic_verdict: "supported", critic_notes: null })).toEqual([
      { key: "rca.quality.evidenceVerified", tone: "ok", hint: null },
      { key: "rca.quality.critic.supported", tone: "ok", hint: null },
    ]);
  });
  it("an unknown or absent critic verdict adds no badge", () => {
    expect(qualityBadges({ evidence_verified: null, critic_verdict: "maybe", critic_notes: null })).toEqual([]);
  });
});

describe("unmatchedRefs", () => {
  it("the newest rca_evidence_check's unmatched_refs; a JSON-string detail is parsed; junk is ignored", () => {
    expect(unmatchedRefs([
      { event_type: "rca_evidence_check", detail: { unmatched_refs: ["old"] }, created_at: "2026-10-03T03:40:00" },
      { event_type: "rca_critic", detail: { verdict: "weak" }, created_at: "2026-10-03T03:41:00" },
      { event_type: "rca_evidence_check", detail: JSON.stringify({ unmatched_refs: ["PATCH …/scale", 7] }) as unknown as Record<string, unknown>, created_at: "2026-10-03T03:41:30" },
    ])).toEqual(["PATCH …/scale"]);
    expect(unmatchedRefs(undefined)).toEqual([]);
    expect(unmatchedRefs([{ event_type: "rca_evidence_check", detail: null, created_at: "x" }])).toEqual([]);
  });
});
```

- [ ] **Step 2: 跑测试确认失败** → FAIL（模块不存在）。
- [ ] **Step 3: 实现** `lib/rcaQuality.ts`：

```ts
import type { PipelineEvent, RCAResult } from "@/api/types";

/** Mirrors services/rca_quality: an RCA whose cited evidence is not grounded is multiplied by 0.6, one the critic
 *  refutes by 0.5; the auto-fix gate is `confidence >= rca_min_confidence_for_autofix` and the critic did not
 *  refute it. The stored confidence is the final one, so the raw one is reconstructed for the explanation. */
export const EVIDENCE_PENALTY = 0.6;
export const CRITIC_PENALTY = 0.5;

export interface ConfidenceBreakdown {
  raw: number;
  final: number;
  evidencePenalty: boolean;
  criticPenalty: boolean;
  threshold: number | null;
  gatePassed: boolean | null;
}

export function confidenceBreakdown(
  rca: Pick<RCAResult, "confidence" | "evidence_verified" | "critic_verdict">,
  threshold: number | null | undefined,
): ConfidenceBreakdown {
  const final = typeof rca.confidence === "number" ? rca.confidence : 0;
  const evidencePenalty = rca.evidence_verified === false;
  const criticPenalty = rca.critic_verdict === "refuted";
  let raw = final;
  if (evidencePenalty) raw /= EVIDENCE_PENALTY;
  if (criticPenalty) raw /= CRITIC_PENALTY;
  raw = Math.min(1, Math.round(raw * 1000) / 1000);
  const t = typeof threshold === "number" ? threshold : null;
  return { raw, final, evidencePenalty, criticPenalty, threshold: t,
           gatePassed: t === null ? null : final >= t && !criticPenalty };
}

export type QualityTone = "ok" | "warn" | "bad";
export interface QualityBadge { key: string; tone: QualityTone; hint: string | null }

export function qualityBadges(
  rca: Pick<RCAResult, "evidence_verified" | "critic_verdict" | "critic_notes">,
): QualityBadge[] {
  const out: QualityBadge[] = [];
  if (rca.evidence_verified === true) out.push({ key: "rca.quality.evidenceVerified", tone: "ok", hint: null });
  if (rca.evidence_verified === false) out.push({ key: "rca.quality.evidenceUnverified", tone: "bad", hint: null });
  const v = rca.critic_verdict;
  if (v === "supported" || v === "weak" || v === "refuted") {
    out.push({ key: `rca.quality.critic.${v}`, tone: v === "supported" ? "ok" : v === "weak" ? "warn" : "bad",
               hint: rca.critic_notes || null });
  }
  return out;
}

function asObject(detail: unknown): Record<string, unknown> | null {
  if (typeof detail === "string") {
    try { return asObject(JSON.parse(detail)); } catch { return null; }
  }
  return detail !== null && typeof detail === "object" && !Array.isArray(detail) ? (detail as Record<string, unknown>) : null;
}

/** The references the newest evidence check could not match to a tool result in the RCA's own run. */
export function unmatchedRefs(
  events: Pick<PipelineEvent, "event_type" | "detail" | "created_at">[] | undefined,
): string[] {
  const checks = (events ?? []).filter((e) => e.event_type === "rca_evidence_check");
  const newest = checks.reduce<(typeof checks)[number] | null>(
    (best, e) => (best === null || (e.created_at ?? "") >= (best.created_at ?? "") ? e : best), null);
  const refs = asObject(newest?.detail)?.unmatched_refs;
  return Array.isArray(refs) ? refs.filter((r): r is string => typeof r === "string") : [];
}
```

  locale：

| 键 | en | zh |
|---|---|---|
| `rca.quality.evidenceVerified` | Evidence checked | 证据已核验 |
| `rca.quality.evidenceUnverified` | Evidence check failed | 证据核验未通过 |
| `rca.quality.critic.supported` | Reviewer: supported | 评审员：支持 |
| `rca.quality.critic.weak` | Reviewer: weak evidence | 评审员：证据偏弱 |
| `rca.quality.critic.refuted` | Reviewer: refuted | 评审员：否定 |
| `rca.confidence.breakdown` | Raw {raw} → {steps} → {final} | 原始 {raw} → {steps} → {final} |
| `rca.confidence.stepEvidence` | evidence check failed ×0.6 | 证据核验未通过 ×0.6 |
| `rca.confidence.stepCritic` | reviewer refuted ×0.5 | 评审员否定 ×0.5 |
| `rca.confidence.criticWeakFree` | a weak reviewer verdict costs nothing | 评审员判「证据偏弱」不扣分 |
| `rca.confidence.threshold` | auto-fix threshold {threshold} | 自动修复阈值 {threshold} |
| `rca.confidence.below` | Below the threshold: auto-fix is paused until a person reviews the root cause. | 低于阈值：自动修复已暂停，等人复核根因。 |
| `rca.unmatchedRefs` | References not found in this RCA's tool calls | 不在本次 RCA 工具调用记录里的引用 |

  `RcaSection`（现有 IssueDetail 内，A2 会把它整体搬进诊断卡，所以这里改的就是最终逻辑）：
  - 徽章改为 `qualityBadges(r).map(b => <span title={b.hint ?? undefined} className={TONE[b.tone]}>{t(b.key)}</span>)`，`TONE = { ok: "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300", warn: "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300", bad: "bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300" }`（加 `text-xs font-medium px-2 py-0.5 rounded-full`）；删掉原来写死的 `critic: {verdict}`。
  - 置信度条：`const b = confidenceBreakdown(r, settings.data?.rca_min_confidence_for_autofix)`（`useSettings()`）；条上在 `b.threshold` 处画一条竖线（`absolute` 定位 `left: ${threshold*100}%`，`w-px h-3 bg-foreground/60`，`title={t("rca.confidence.threshold")…}`）；条下一行：有任一 penalty 时显示 `rca.confidence.breakdown`（`{raw}`、`{final}` 用 `Math.round(x*100)+"%"`，`{steps}` 用应用了的 step 文案以「 → 」连接）；`critic_verdict === "weak"` 时追加 `rca.confidence.criticWeakFree`；`b.gatePassed === false` 时再一行 `rca.confidence.below`（琥珀色）。
  - 未核实引用：`const refs = unmatchedRefs(timeline.data)`（RcaSection 新增一个 `timelineEvents` prop，由 IssueTab 从页面的 `useIssueTimeline` 传入）；非空时列在置信度下方，标题 `rca.unmatchedRefs`，每条 `font-mono text-xs break-all`。
  - Model 行：`model_id` 为空时整行只显示分析时间（P16），不再出现「Model: |」。
- [ ] **Step 4: 跑测试确认通过** → PASS。
- [ ] **Step 5: 前端门禁**。
- [ ] **Step 6: Commit**：`feat(web): explain RCA quality and the auto-fix gate in plain language`。

### Task 4: 锚点显示资源名，事实块不显示空值（P8）

**Files:**
- Modify: `$FE/src/lib/issueDetail.ts`、`$FE/src/pages/IssueDetail.tsx`（头部锚点徽章、IssueTab 事实块）、locale
- Test: `$FE/src/__tests__/issueDetail.test.ts`（追加）

**Interfaces:**
- Produces（Task 11 的 FactsRail 用）：

```ts
export type AnchorBadge = { kind: "resource"; ref: number; label: string } | { kind: "ambiguous" | "account_level" | "unanchored"; candidates: number };
export function anchorBadge(issue: Pick<HealthIssue, "resource_id" | "resource_ref" | "anchor_status" | "anchor_candidates">, resourceName?: string | null): AnchorBadge | null
export interface FactRow { labelKey: string; value: string; kind?: "date" | "mono"; href?: string }
export function factRows(issue: Pick<HealthIssue, "resource_id" | "resource_ref" | "anchor_status" | "account_name" | "severity" | "source" | "detected_at" | "trace_id" | "metric_data">, anchor?: { name: string | null; type: string | null } | null): FactRow[]
export function isBlank(v: unknown): boolean
```

- [ ] **Step 1: 写失败的测试**（追加到 `issueDetail.test.ts`，复用文件里的 `issue()` 工厂）

```ts
describe("anchorBadge with the resource name (P8)", () => {
  it("names the anchored resource, not the alarm's raw resource_id; falls back to #ref, never to 'unknown'", () => {
    const i = issue({ resource_id: "unknown", resource_ref: 36, anchor_status: "anchored" });
    expect(anchorBadge(i, "agenticops-chaos-lab")).toEqual({ kind: "resource", ref: 36, label: "agenticops-chaos-lab" });
    expect(anchorBadge(i)).toEqual({ kind: "resource", ref: 36, label: "#36" });
    expect(anchorBadge(issue({ resource_id: "i-0abc", resource_ref: 5, anchor_status: "anchored" }))).toEqual(
      { kind: "resource", ref: 5, label: "i-0abc" });
  });
});

describe("factRows", () => {
  it("drops empty, 'unknown' and dash values; the anchor row links the resource with its name and type", () => {
    const i = issue({ resource_id: "unknown", resource_ref: 36, anchor_status: "anchored", account_name: "chaos-lab",
                      source: "cloudwatch_alarm", metric_data: { resource_type: "unknown", region: "—" } });
    const rows = factRows(i, { name: "agenticops-chaos-lab", type: "EKS" });
    expect(rows.map((r) => r.labelKey)).toEqual(
      ["facts.anchor", "facts.account", "facts.severity", "facts.source", "facts.detected", "facts.trace"]);
    expect(rows[0]).toEqual({ labelKey: "facts.anchor", value: "agenticops-chaos-lab · EKS", href: "/app/resources/36" });
    expect(rows.find((r) => r.labelKey === "facts.detected")?.kind).toBe("date");
  });
  it("an unanchored issue with a real resource id shows it as the resource row; region/type when present", () => {
    const rows = factRows(issue({ resource_id: "i-0abc", metric_data: { resource_type: "EC2", region: "us-east-1" } }));
    expect(rows.slice(0, 3)).toEqual([
      { labelKey: "facts.resource", value: "i-0abc", kind: "mono" },
      { labelKey: "facts.type", value: "EC2" },
      { labelKey: "facts.region", value: "us-east-1" },
    ]);
  });
  it("isBlank", () => {
    for (const v of ["", " ", "unknown", "Unknown", "—", "-", "n/a", null, undefined]) expect(isBlank(v), String(v)).toBe(true);
    for (const v of ["x", 0, "0"]) expect(isBlank(v), String(v)).toBe(false);
  });
});
```

- [ ] **Step 2: 跑测试确认失败**。
- [ ] **Step 3: 实现**（`lib/issueDetail.ts`）：

```ts
const BLANK = new Set(["", "unknown", "—", "-", "n/a", "none", "null"]);
/** A value not worth a row: absent, empty, or a placeholder an alarm carried instead of a fact. */
export function isBlank(v: unknown): boolean {
  if (v === null || v === undefined) return true;
  if (typeof v === "number") return false;
  return typeof v !== "string" || BLANK.has(v.trim().toLowerCase());
}

export function anchorBadge(
  issue: Pick<HealthIssue, "resource_id" | "resource_ref" | "anchor_status" | "anchor_candidates">,
  resourceName?: string | null,
): AnchorBadge | null {
  if (issue.anchor_status == null) return null;
  if (issue.anchor_status === "anchored" && issue.resource_ref != null) {
    const label = !isBlank(resourceName) ? resourceName! : !isBlank(issue.resource_id) ? issue.resource_id : `#${issue.resource_ref}`;
    return { kind: "resource", ref: issue.resource_ref, label };
  }
  const kind = issue.anchor_status === "anchored" ? "unanchored" : issue.anchor_status;
  return { kind, candidates: kind === "ambiguous" ? issue.anchor_candidates?.candidates?.length ?? 0 : 0 };
}

export interface FactRow { labelKey: string; value: string; kind?: "date" | "mono"; href?: string }

/** The issue's key facts for the right rail, blank rows dropped (an alarm's "unknown" resource is not a fact). */
export function factRows(
  issue: Pick<HealthIssue, "resource_id" | "resource_ref" | "anchor_status" | "account_name" | "severity" | "source"
    | "detected_at" | "trace_id" | "metric_data">,
  anchor?: { name: string | null; type: string | null } | null,
): FactRow[] {
  const rows: FactRow[] = [];
  const f = issueFacts(issue);
  if (issue.anchor_status === "anchored" && issue.resource_ref != null) {
    const name = !isBlank(anchor?.name) ? anchor!.name! : !isBlank(issue.resource_id) ? issue.resource_id : `#${issue.resource_ref}`;
    rows.push({ labelKey: "facts.anchor", value: [name, anchor?.type].filter((x) => !isBlank(x)).join(" · "),
                href: `/app/resources/${issue.resource_ref}` });
  } else if (!isBlank(issue.resource_id)) {
    rows.push({ labelKey: "facts.resource", value: issue.resource_id, kind: "mono" });
  }
  if (!isBlank(f.resourceType)) rows.push({ labelKey: "facts.type", value: f.resourceType! });
  if (!isBlank(f.region)) rows.push({ labelKey: "facts.region", value: f.region! });
  if (!isBlank(issue.account_name)) rows.push({ labelKey: "facts.account", value: issue.account_name! });
  rows.push({ labelKey: "facts.severity", value: issue.severity.toUpperCase() });
  if (!isBlank(issue.source)) rows.push({ labelKey: "facts.source", value: issue.source });
  rows.push({ labelKey: "facts.detected", value: issue.detected_at, kind: "date" });
  if (!isBlank(issue.trace_id)) rows.push({ labelKey: "facts.trace", value: issue.trace_id!, kind: "mono" });
  return rows;
}
```

  （`anchorBadge` 替换原函数；原测试中 `label: issue.resource_id` 的断言按新规则仍成立——资源 id 非空时 label 就是它。）
  locale：`facts.anchor` Anchor / 锚点，`facts.resource` Resource / 资源，`facts.type` Type / 类型，`facts.region` Region / 区域，`facts.account` Account / 账户，`facts.severity` Severity / 严重度，`facts.source` Source / 来源，`facts.detected` Detected / 检测于，`facts.trace` Trace / Trace。
  `IssueDetail.tsx`：页面顶部 `const anchorRes = useResource(a.resource_ref ?? 0)`（`hooks/useResourceDetail`，`enabled: id > 0` 已自带）；头部徽章 `anchorBadge(a, anchorRes.data?.name)`；IssueTab 的四格事实块改为渲染 `factRows(a, { name: anchorRes.data?.name ?? null, type: anchorRes.data?.resource_type ?? null })`（`kind === "date"` 用 `formatFullDate`，`href` 用 `<Link>`）。
- [ ] **Step 4: 跑测试确认通过**（含原 `anchorBadge` 测试）。
- [ ] **Step 5: 前端门禁**。
- [ ] **Step 6: Commit**：`feat(web): anchor badge names the resource; issue facts drop placeholder values`。

### Task 5: 局部图默认收敛（P11）

**Files:**
- Modify: `$FE/src/lib/localGraph.ts`、`$FE/src/components/graph/LocalGraph.tsx`、locale
- Test: `$FE/src/__tests__/localGraph.test.ts`（追加）

**Interfaces:**
- Produces：

```ts
export const COMPACT_NODE_CAP = 15;
export function compactLocalGraph(model: LocalGraphModel, cap?: number): { model: LocalGraphModel; hidden: number }
```
  `LocalGraph` 新 prop：`compact?: boolean`（默认 false，行为与今天完全一致）。Task 11 在诊断卡里用 `compact`。

- [ ] **Step 1: 写失败的测试**（在 `localGraph.test.ts` 里用一个手造的 `LocalGraphModel`，不经过 API 形状）

```ts
import { compactLocalGraph, COMPACT_NODE_CAP, type LgNode, type LocalGraphModel } from "@/lib/localGraph";

function n(id: string, extra: Partial<LgNode> = {}): LgNode {
  return { id, kind: "resource", ref: Number(id.slice(2)) || null, label: id, type: null, hops: 2, health: "unknown",
           issueIds: [], anchor: false, onPath: false, absent: false, merged: [], candidates: [], ...extra };
}

describe("compactLocalGraph (P11)", () => {
  it("keeps the anchor, the causal path, merged signals and 1-hop neighbours, in that order, up to the cap", () => {
    const nodes = [n("r:1", { anchor: true, hops: 0 }), n("r:2", { onPath: true, hops: 2 }),
                   n("m:x", { kind: "merged", ref: null, hops: null }),
                   ...Array.from({ length: 30 }, (_, i) => n(`r:${10 + i}`, { hops: 1 })),
                   n("r:99", { hops: 2 })];
    const links = [{ id: "s:1>2", kind: "structural" as const, source: "r:1", target: "r:2", llm: false, onPath: true },
                   { id: "s:1>99", kind: "structural" as const, source: "r:1", target: "r:99", llm: false, onPath: false }];
    const model: LocalGraphModel = { nodes, links, anchorIds: ["r:1"], truncated: [] };
    const { model: m, hidden } = compactLocalGraph(model);
    expect(m.nodes.length).toBe(COMPACT_NODE_CAP);
    expect(m.nodes.slice(0, 3).map((x) => x.id)).toEqual(["r:1", "r:2", "m:x"]);
    expect(m.nodes.some((x) => x.id === "r:99")).toBe(false); // 2 hops, off the path
    expect(m.links.map((l) => l.id)).toEqual(["s:1>2"]);      // a link to a dropped node goes too
    expect(hidden).toBe(nodes.length - COMPACT_NODE_CAP);
    expect(m.anchorIds).toEqual(["r:1"]);
  });
  it("a small graph is unchanged", () => {
    const model: LocalGraphModel = { nodes: [n("r:1", { anchor: true, hops: 0 }), n("r:2", { hops: 1 })], links: [], anchorIds: ["r:1"], truncated: [] };
    expect(compactLocalGraph(model)).toEqual({ model, hidden: 0 });
  });
});
```

- [ ] **Step 2: 跑测试确认失败**。
- [ ] **Step 3: 实现**（`lib/localGraph.ts` 末尾）：

```ts
/** The default drawing on an issue page (P11): the anchor, the RCA causal path, merged signals, then the
 *  anchor's 1-hop neighbours and candidate issues — capped, so a 132-neighbour star stays readable. */
export const COMPACT_NODE_CAP = 15;

function compactRank(nd: LgNode): number {
  if (nd.anchor) return 0;
  if (nd.onPath) return 1;
  if (nd.kind === "merged" || nd.kind === "issue") return 2;
  if (nd.kind === "resource" && (nd.hops ?? Infinity) <= 1) return 3;
  if (nd.kind === "candidate") return 4;
  return 9;
}

export function compactLocalGraph(model: LocalGraphModel, cap = COMPACT_NODE_CAP): { model: LocalGraphModel; hidden: number } {
  const ranked = model.nodes
    .map((nd, i) => ({ nd, i, r: compactRank(nd) }))
    .filter((x) => x.r < 9)
    .sort((a, b) => a.r - b.r || (a.nd.hops ?? Infinity) - (b.nd.hops ?? Infinity) || a.i - b.i);
  const kept = new Set(ranked.slice(0, cap).map((x) => x.nd.id));
  if (kept.size === model.nodes.length) return { model, hidden: 0 };
  const nodes = model.nodes.filter((nd) => kept.has(nd.id));
  return {
    model: { ...model, nodes, links: model.links.filter((l) => kept.has(l.source) && kept.has(l.target)),
             anchorIds: model.anchorIds.filter((id) => kept.has(id)) },
    hidden: model.nodes.length - nodes.length,
  };
}
```

  注意排序：同 rank 内按 hops、再按原顺序（`a.i - b.i`，buildLocalGraph 已按 anchor/hops/ref 排好）——测试里 `r:1`/`r:2`/`m:x` 依次是 rank 0/1/2。
  `LocalGraph.tsx`：
  - 新 prop `compact?: boolean`；组件内 `const [showAll, setShowAll] = useState(false)`；在 `buildLocalGraph(...)` 之后 `const view = compact && !showAll ? compactLocalGraph(model) : { model, hidden: 0 }`，绘图与列表视图都用 `view.model`。
  - `view.hidden > 0` 时在图上方工具栏（「显示 LLM 推断关系」开关同一行）加按钮 `t("graph.showAll").replace("{n}", String(model.nodes.length))`，点后 `setShowAll(true)`；`showAll` 时显示 `t("graph.showCompact")` 收回。
  - compact 模式下非锚点、非路径节点的文字标签不画，改为 `<title>` 悬停显示（d3 渲染里按 `node.anchor || node.onPath || !compactMode` 决定是否画 label）。
  locale：`graph.showAll` Show all {n} / 显示全部 {n} 个，`graph.showCompact` Show the anchor's neighbourhood only / 只看锚点邻域。
- [ ] **Step 4: 跑测试确认通过**；`localGraph.test.ts` 原有用例不变。
- [ ] **Step 5: 前端门禁**。
- [ ] **Step 6: Commit**：`feat(web): local graph can draw a compact anchor neighbourhood with a show-all toggle`。

### Task 6: 变更步进器在结局处收尾；终态给出下一步（P12、P13）

**Files:**
- Modify: `$FE/src/lib/changeStepper.ts`、`$FE/src/components/plans/ChangeStepper.tsx`、`$FE/src/lib/changeDetail.ts`、`$FE/src/pages/ChangeDetail.tsx`（PRIMARY 加 copy）、locale
- Test: `$FE/src/__tests__/changeStepper.test.ts`、`$FE/src/__tests__/changeDetail.test.ts`（追加/改）

**Interfaces:**
- Produces：`export function visibleStepCount(cr: ChangeStepInput): number`；`ChangeNextAction` 增加 `"copy"`；`changeHeadline` 对 `failed` / `rolled_back` / `rejected` / `cancelled` 返回 `{ todo: "copyAsNew", action: "copy" }`（`completed` 仍是无待办）。ContextPanel 与 ChangeDetail 都读 `changeHeadline`。

- [ ] **Step 1: 写失败的测试**
  - `changeStepper.test.ts` 追加：

```ts
import { visibleStepCount, CHANGE_STEP_KEYS } from "@/lib/changeStepper";

describe("visibleStepCount (P12)", () => {
  const cr = (status: string, extra: Record<string, unknown> = {}) =>
    ({ status, approved_at: null, review_verdict: null, ...extra }) as Parameters<typeof visibleStepCount>[0];
  it("a bad ending is the last step drawn; a good or open path draws all steps", () => {
    expect(visibleStepCount(cr("failed"))).toBe(5);                       // ends at Executed
    expect(visibleStepCount(cr("rolled_back"))).toBe(5);
    expect(visibleStepCount(cr("rejected"))).toBe(2);                     // the review rejected it
    expect(visibleStepCount(cr("rejected", { review_verdict: "approved_for_planning" }))).toBe(4);
    expect(visibleStepCount(cr("cancelled", { approved_at: "2026-10-03T09:00:00" }))).toBe(5);
    expect(visibleStepCount(cr("completed"))).toBe(CHANGE_STEP_KEYS.length);
    expect(visibleStepCount(cr("planned"))).toBe(CHANGE_STEP_KEYS.length);
    expect(visibleStepCount(cr("needs_review"))).toBe(CHANGE_STEP_KEYS.length);
  });
});
```

  - `changeDetail.test.ts`：把现有的
    `expect(changeHeadline(cr({ status: "rejected", rejection_reason: "too risky" }), null)).toEqual({ reason: "too risky", todo: null, action: null });`
    改为 `.toEqual({ reason: "too risky", todo: "copyAsNew", action: "copy" })`，并追加：

```ts
  it("a closed change that did not complete offers copy-as-new; completed has nothing to do (P13)", () => {
    for (const status of ["failed", "rolled_back", "cancelled"] as const) {
      const h = changeHeadline(cr({ status }), null);
      expect([h.todo, h.action], status).toEqual(["copyAsNew", "copy"]);
    }
    expect(changeHeadline(cr({ status: "completed" }), run({ verification_status: "passed" })))
      .toEqual({ reason: null, todo: null, action: null });
  });
```

- [ ] **Step 2: 跑测试确认失败**。
- [ ] **Step 3: 实现**
  - `changeStepper.ts`：

```ts
/** How many steps the stepper draws: a change that ended badly ends at the step it ended on (P12) — no
 *  "Completed" after "Failed"; every other change draws the whole path. */
export function visibleStepCount(cr: ChangeStepInput): number {
  const s = changeStepState(cr);
  return s.tone === "bad" ? s.index + 1 : CHANGE_STEP_KEYS.length;
}
```

  - `ChangeStepper.tsx`：只渲染 `CHANGE_STEP_KEYS.slice(0, visibleStepCount(cr))`（compact 模式同样截断）。
  - `changeDetail.ts`：`ChangeNextAction` 加 `"copy"`；`NEXT` 加 `failed: ["copyAsNew", "copy"], rolled_back: ["copyAsNew", "copy"], rejected: ["copyAsNew", "copy"], cancelled: ["copyAsNew", "copy"]`；把函数注释里的「closed → none」改为「completed → none; a change closed without completing → copy as new」。
  - `ChangeDetail.tsx` 的 `PRIMARY` 加 `copy: { label: t("changes.copyAsNew"), run: () => setCopy(true) }`（类型 `Record<ChangeNextAction, …>` 会强制补上）。
  - locale：`changes.todo.copyAsNew` Copy it as a new change request / 复制为新变更申请。
- [ ] **Step 4: 跑测试确认通过**（changeStepper / changeDetail 全文件）。
- [ ] **Step 5: 前端门禁**。
- [ ] **Step 6: Commit**：`feat(web): change stepper ends at the outcome; a failed change offers copy-as-new`。

---

# A2 — 模板组件 + 问题详情

### Task 7: 可读的时间线（P4）

**Files:**
- Create: `$FE/src/lib/activity.ts`、`$FE/src/components/workitem/ActivityList.tsx`
- Modify: locale
- Test: `$FE/src/__tests__/activity.test.ts`

**Interfaces:**
- Consumes：`PipelineEvent`（问题时间线 `useIssueTimeline`，变更时间线经 `toPipelineEvents` 转换）。
- Produces（Task 11、13 用）：

```ts
export interface ActivityEntry { ts: string; labelKey: string; labelParams: Record<string, string>; summary: string; actor: string; tone: "ok" | "warn" | "bad" | "info"; count: number; raw: PipelineEvent[] }
export function toActivity(events: PipelineEvent[] | undefined): ActivityEntry[]   // oldest first, consecutive duplicates merged
export function ActivityList(props: { entries: ActivityEntry[]; t: (k: string) => string; emptyKey: string }): JSX.Element
```

- [ ] **Step 1: 写失败的测试**

```ts
import { describe, it, expect } from "vitest";
import type { PipelineEvent } from "@/api/types";
import { toActivity } from "@/lib/activity";

const ev = (event_type: string, detail: unknown, extra: Partial<PipelineEvent> = {}): PipelineEvent => ({
  id: 0, event_type, stage: "", status: "completed", detail: detail as Record<string, unknown> | null,
  actor: "system", duration_ms: null, created_at: "2026-10-03T03:39:00", trace_id: null, ...extra,
});

describe("toActivity (P4)", () => {
  it("a known event gets its label key and a summary from its detail; unknown keys stay out of the sentence", () => {
    const [a] = toActivity([ev("rca_needs_review", { confidence: 0.57, reason: "confidence 0.57 < 0.6", rca_id: 1 })]);
    expect(a.labelKey).toBe("activity.type.rca_needs_review");
    expect(a.summary).toBe("confidence 0.57 < 0.6");
    expect(a.tone).toBe("warn");
  });
  it("an unknown event type falls back to the generic label with the raw type; never throws", () => {
    const [a] = toActivity([ev("brand_new_thing", "not json")]);
    expect(a.labelKey).toBe("activity.type.unknown");
    expect(a.labelParams).toEqual({ type: "brand_new_thing" });
    expect(a.summary).toBe("");
  });
  it("authz denials read as rule + permission, shadow ones marked", () => {
    const [a, b] = toActivity([
      ev("authz.denied", { rule: "no-webhook-approve-or-execute", permission: "change.approve" }, { actor: "webhook:e2e" }),
      ev("authz.denied_shadow", { rule: "sod-change-approver-not-requester", permission: "change.approve" }, { created_at: "2026-10-03T03:40:00" }),
    ]);
    expect(a.labelKey).toBe("activity.type.authz_denied");
    expect(a.labelParams).toEqual({ rule: "no-webhook-approve-or-execute", permission: "change.approve" });
    expect(a.tone).toBe("bad");
    expect(b.labelKey).toBe("activity.type.authz_denied_shadow");
  });
  it("consecutive duplicates merge into one entry with a count; the raw events are kept", () => {
    const d = { rule: "no-webhook-approve-or-execute", permission: "change.execute" };
    const out = toActivity([ev("authz.denied", d), ev("authz.denied", d), ev("policy_decision", { action: "auto_approve" })]);
    expect(out.map((x) => [x.labelKey, x.count])).toEqual([["activity.type.authz_denied", 2], ["activity.type.policy_decision", 1]]);
    expect(out[0].raw).toHaveLength(2);
  });
  it("events come out oldest first whatever the input order; a JSON-string detail is parsed", () => {
    const out = toActivity([
      ev("rca_completed", JSON.stringify({ confidence: 0.95 }), { created_at: "2026-10-03T03:40:00" }),
      ev("issue_created", { severity: "high" }, { created_at: "2026-10-03T03:39:00" }),
    ]);
    expect(out.map((x) => x.labelKey)).toEqual(["activity.type.issue_created", "activity.type.rca_completed"]);
    expect(out[1].summary).toBe("95%");
  });
});
```

- [ ] **Step 2: 跑测试确认失败**。
- [ ] **Step 3: 实现** `lib/activity.ts`：

```ts
import type { PipelineEvent } from "@/api/types";

/** Event types with a sentence of their own (`activity.type.<type, dots → _>`); anything else reads generically. */
const KNOWN = new Set([
  "issue_created", "signal_gated", "issue_resource_merged", "status_changed",
  "rca_started", "rca_completed", "rca_evidence_check", "rca_critic", "rca_needs_review", "rca_human_feedback",
  "rca_disputed", "fix_approved", "execution_started", "execution_completed", "resolved", "post_resolution",
  "change_requested", "change_review_started", "policy_decision", "change_reviewed", "review_failed",
  "change_clarified", "change_approved", "change_rejected", "change_cancelled", "change_review_resolved",
  "change.requested", "change.reviewed", "change.clarified", "change.approved", "change.rejected", "change.cancelled",
  "change.execution_started", "change.completed", "change.failed", "change.rolled_back", "change.needs_review",
  "plan.approved", "plan.rejected", "plan.edited", "plan.execute_requested", "plan.execution_cancelled",
  "authz.denied", "authz.denied_shadow",
]);
const BAD = new Set(["authz.denied", "rca_disputed", "change.failed", "change.rolled_back", "change_rejected", "review_failed"]);
const WARN = new Set(["rca_needs_review", "authz.denied_shadow", "change.needs_review", "change_cancelled"]);
// The detail fields worth a sentence, first present wins (the rest stays in the raw view)
const SUMMARY_KEYS = ["reason", "verdict", "outcome", "action", "risk_level", "execution_status", "confidence"];

export interface ActivityEntry {
  ts: string;
  labelKey: string;
  labelParams: Record<string, string>;
  summary: string;
  actor: string;
  tone: "ok" | "warn" | "bad" | "info";
  count: number;
  raw: PipelineEvent[];
}

function asObject(detail: unknown): Record<string, unknown> {
  if (typeof detail === "string") {
    try { return asObject(JSON.parse(detail)); } catch { return {}; }
  }
  return detail !== null && typeof detail === "object" && !Array.isArray(detail) ? (detail as Record<string, unknown>) : {};
}

function summarize(d: Record<string, unknown>): string {
  for (const k of SUMMARY_KEYS) {
    const v = d[k];
    if (k === "confidence" && typeof v === "number") return `${Math.round(v * 100)}%`;
    if (typeof v === "string" && v.trim()) return v.trim();
  }
  return "";
}

function entry(e: PipelineEvent): ActivityEntry {
  const d = asObject(e.detail);
  const type = e.event_type;
  const known = KNOWN.has(type);
  const isAuthz = type === "authz.denied" || type === "authz.denied_shadow";
  return {
    ts: e.created_at ?? "",
    labelKey: known ? `activity.type.${type.replace(/\./g, "_")}` : "activity.type.unknown",
    labelParams: isAuthz ? { rule: String(d.rule ?? ""), permission: String(d.permission ?? "") }
      : known ? {} : { type },
    summary: isAuthz ? "" : summarize(d),
    actor: e.actor || "system",
    tone: BAD.has(type) || e.status === "failed" ? "bad" : WARN.has(type) ? "warn"
      : e.status === "completed" || e.status === "succeeded" ? "ok" : "info",
    count: 1,
    raw: [e],
  };
}

/** The timeline as sentences, oldest first; a run of identical consecutive events is one entry ×N. */
export function toActivity(events: PipelineEvent[] | undefined): ActivityEntry[] {
  const sorted = [...(events ?? [])].sort((a, b) => (a.created_at ?? "").localeCompare(b.created_at ?? "") || a.id - b.id);
  const out: ActivityEntry[] = [];
  for (const e of sorted) {
    const next = entry(e);
    const last = out[out.length - 1];
    if (last && last.labelKey === next.labelKey && last.summary === next.summary && last.actor === next.actor
        && JSON.stringify(last.labelParams) === JSON.stringify(next.labelParams)) {
      last.count += 1;
      last.raw.push(e);
    } else out.push(next);
  }
  return out;
}
```

  `ActivityList.tsx`：

```tsx
import { useState } from "react";
import type { ActivityEntry } from "@/lib/activity";
import { formatShortDate } from "@/lib/formatDate";

const DOT: Record<ActivityEntry["tone"], string> = { ok: "bg-emerald-500", warn: "bg-amber-500", bad: "bg-red-500", info: "bg-blue-500" };

/** The right rail's activity: one sentence per event, duplicates ×N, the raw events behind a toggle. */
export function ActivityList({ entries, t, emptyKey }: { entries: ActivityEntry[]; t: (k: string) => string; emptyKey: string }) {
  const [raw, setRaw] = useState(false);
  if (entries.length === 0) return <p className="text-xs text-muted-foreground">{t(emptyKey)}</p>;
  const total = entries.reduce((n, e) => n + e.raw.length, 0);
  const fill = (key: string, params: Record<string, string>) =>
    Object.entries(params).reduce((s, [k, v]) => s.replace(`{${k}}`, v), t(key));
  return (
    <div className="space-y-2">
      <ol className="space-y-1.5">
        {entries.map((e, i) => (
          <li key={i} className="flex gap-2 text-xs">
            <span className={`mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full ${DOT[e.tone]}`} />
            <div className="min-w-0">
              <span className="text-muted-foreground font-mono mr-1">{formatShortDate(e.ts)}</span>
              <span className="text-foreground">{fill(e.labelKey, e.labelParams)}</span>
              {e.count > 1 && <span className="ml-1 text-muted-foreground">×{e.count}</span>}
              {e.summary && <span className="block text-muted-foreground break-words">{e.summary}</span>}
              <span className="block text-[10px] text-muted-foreground/70">{e.actor}</span>
            </div>
          </li>
        ))}
      </ol>
      <button onClick={() => setRaw(!raw)} className="text-xs text-primary hover:underline">
        {t("activity.raw").replace("{n}", String(total))}
      </button>
      {raw && (
        <pre className="max-h-80 overflow-auto rounded bg-secondary p-2 text-[10px] leading-snug">
          {JSON.stringify(entries.flatMap((e) => e.raw), null, 2)}
        </pre>
      )}
    </div>
  );
}
```

  locale（每个 KNOWN 类型一条 + 通用）：

| 键 | en | zh |
|---|---|---|
| `activity.raw` | Raw events ({n}) | 原始事件 ({n}) |
| `activity.empty` | No activity yet | 还没有动态 |
| `activity.type.unknown` | Event: {type} | 事件：{type} |
| `activity.type.issue_created` | Issue opened | 问题已创建 |
| `activity.type.signal_gated` | Signal gated | 信号经过 Signal Gate |
| `activity.type.issue_resource_merged` | Signal merged into this issue | 信号合并进本问题 |
| `activity.type.status_changed` | Status changed | 状态变更 |
| `activity.type.rca_started` | RCA started | RCA 开始 |
| `activity.type.rca_completed` | RCA finished | RCA 完成 |
| `activity.type.rca_evidence_check` | Evidence check | 证据核验 |
| `activity.type.rca_critic` | Reviewer verdict | 评审员结论 |
| `activity.type.rca_needs_review` | Needs a person: auto-fix paused | 需人工复核：自动修复已暂停 |
| `activity.type.rca_human_feedback` | Human verdict on the RCA | 人工判断 RCA |
| `activity.type.rca_disputed` | RCA disputed | RCA 被质疑 |
| `activity.type.fix_approved` | Fix plan approved | 修复方案已批准 |
| `activity.type.execution_started` | Run started | 执行开始 |
| `activity.type.execution_completed` | Run finished | 执行结束 |
| `activity.type.resolved` | Resolved | 已解决 |
| `activity.type.post_resolution` | Post-resolution review | 解决后复盘 |
| `activity.type.change_requested` | Change requested | 提交变更申请 |
| `activity.type.change_review_started` | SRE review started | SRE 开始审核 |
| `activity.type.policy_decision` | Policy decision | 策略决定 |
| `activity.type.change_reviewed` | Review finished | 审核完成 |
| `activity.type.review_failed` | Review failed | 审核失败 |
| `activity.type.change_clarified` | Requester answered | 申请人已答复 |
| `activity.type.change_approved` | Approved | 已批准 |
| `activity.type.change_rejected` | Rejected | 已拒绝 |
| `activity.type.change_cancelled` | Cancelled | 已取消 |
| `activity.type.change_review_resolved` | Result accepted by a person | 人工验收结论 |
| `activity.type.change_execution_started` | Run queued | 执行已入队 |
| `activity.type.change_completed` | Completed | 已完成 |
| `activity.type.change_failed` | Failed | 失败 |
| `activity.type.change_rolled_back` | Rolled back | 已回滚 |
| `activity.type.change_needs_review` | Waiting for acceptance | 等待验收 |
| `activity.type.plan_approved` | Plan approved | 方案已批准 |
| `activity.type.plan_rejected` | Plan rejected | 方案已拒绝 |
| `activity.type.plan_edited` | Plan edited | 方案已修改 |
| `activity.type.plan_execute_requested` | Run requested | 请求执行 |
| `activity.type.plan_execution_cancelled` | Run cancelled | 执行已取消 |
| `activity.type.authz_denied` | Rule {rule} blocked {permission} | 规则 {rule} 拦下了 {permission} |
| `activity.type.authz_denied_shadow` | Rule {rule} would block {permission} (shadow mode, allowed) | 规则 {rule} 会拦下 {permission}（影子模式，已放行） |

  （审计行 `change.requested` / `change.reviewed` / `change.clarified` / `change.approved` / `change.rejected` / `change.cancelled` 点号转下划线后与同名事件共用一条键——一处翻译两用，这是有意的。）
- [ ] **Step 4: 跑测试确认通过**；locale parity 通过。
- [ ] **Step 5: 前端门禁**。
- [ ] **Step 6: Commit**：`feat(web): readable activity list — one sentence per event, duplicates merged, raw behind a toggle`。

### Task 8: 问题阶段模型与旧链接映射

**Files:**
- Create: `$FE/src/lib/issuePhases.ts`、`$FE/src/lib/workitemRoutes.ts`
- Test: `$FE/src/__tests__/issuePhases.test.ts`、`$FE/src/__tests__/workitemRoutes.test.ts`

**Interfaces:**
- Consumes：`confidenceBreakdown`（Task 3）。
- Produces（Task 11、14 用）：

```ts
// issuePhases.ts
export type IssuePhaseId = "diagnose" | "plan" | "run" | "accept";
export type PhaseState = "done" | "current" | "future" | "failed";
export interface PhaseView<I extends string = string> { id: I; state: PhaseState }
export type WaitingFor = "rca_agent" | "you" | "sre_agent" | "approver" | "executor" | "requester" | "acceptor" | null;
export type IssuePrimary = "reviewRca" | "rerunRca" | "generatePlan" | "approveAndRun" | "retryExecution" | "acceptResult" | "markResolved" | null;
export type IssueSub = "running" | "needsReview" | "rcaRejected" | "reviewOrPlan" | "toGenerate" | "needsNewPlan"
  | "awaitingApproval" | "notQueued" | "executing" | "awaitingAcceptance" | "passed" | "unverified" | "resolved" | "dismissed";
export interface IssuePhaseInput {
  status: IssueStatus;
  rca?: Pick<RCAResult, "confidence" | "evidence_verified" | "critic_verdict" | "human_verdict"> | null; // undefined = list mode (unknown)
  threshold?: number | null;
  plan?: Pick<FixPlan, "status"> | null;
  latestRun?: Pick<FixExecution, "status" | "verification_status"> | null;
}
export interface IssuePhaseResult { current: IssuePhaseId | null; sub: IssueSub; waitingFor: WaitingFor; primary: IssuePrimary; phases: PhaseView<IssuePhaseId>[] }
export const ISSUE_PHASES: readonly IssuePhaseId[];
export function issuePhases(input: IssuePhaseInput): IssuePhaseResult
export function currentFixPlan(plans: FixPlan[] | undefined): FixPlan | null
// workitemRoutes.ts
export const ISSUE_HASHES: readonly ["diagnose", "plan", "run", "accept", "activity"];
export const CHANGE_HASHES: readonly ["request", "review", "plan", "run", "accept", "activity"];
export function legacyIssueTabHash(tab: string | null): string | null
export function parseHash(hash: string, allowed: readonly string[]): string | null
export function legacyIssuesViewRedirect(search: string): string | null
```

- [ ] **Step 1: 写失败的测试** `issuePhases.test.ts`（覆盖 spec §4 问题表的每一行 + Review Focus 1、2）

```ts
import { describe, it, expect } from "vitest";
import type { FixPlan } from "@/api/types";
import { currentFixPlan, issuePhases, type IssuePhaseInput } from "@/lib/issuePhases";

const gateFail = { confidence: 0.57, evidence_verified: false, critic_verdict: "weak", human_verdict: null } as const;
const gatePass = { confidence: 0.9, evidence_verified: true, critic_verdict: "supported", human_verdict: null } as const;
const P = (x: Partial<IssuePhaseInput>): IssuePhaseInput => ({ status: "open", threshold: 0.6, ...x });
const pick = (r: ReturnType<typeof issuePhases>) => [r.current, r.sub, r.waitingFor, r.primary];
const states = (r: ReturnType<typeof issuePhases>) => r.phases.map((p) => p.state);

describe("issuePhases — spec §4 issue table, one case per row", () => {
  it("open / investigating / acknowledged → ① running, the RCA agent, no primary", () => {
    for (const status of ["open", "investigating", "acknowledged"] as const)
      expect(pick(issuePhases(P({ status, rca: null }))), status).toEqual(["diagnose", "running", "rca_agent", null]);
    expect(states(issuePhases(P({ status: "open" })))).toEqual(["current", "future", "future", "future"]);
  });
  it("root_cause_identified, RCA below the gate → ① needs review, you, 'review root cause' (I#1)", () => {
    expect(pick(issuePhases(P({ status: "root_cause_identified", rca: gateFail })))).toEqual(["diagnose", "needsReview", "you", "reviewRca"]);
  });
  it("…a person said the root cause is wrong → ① rejected, you, rerun RCA", () => {
    expect(pick(issuePhases(P({ status: "root_cause_identified", rca: { ...gateFail, human_verdict: "incorrect" } }))))
      .toEqual(["diagnose", "rcaRejected", "you", "rerunRca"]);
  });
  it("root_cause_identified, gate passed → ② to generate, the SRE agent; or a person said correct → you", () => {
    expect(pick(issuePhases(P({ status: "root_cause_identified", rca: gatePass })))).toEqual(["plan", "toGenerate", "sre_agent", "generatePlan"]);
    expect(pick(issuePhases(P({ status: "root_cause_identified", rca: { ...gateFail, human_verdict: "correct" } }))))
      .toEqual(["plan", "toGenerate", "you", "generatePlan"]);
    expect(states(issuePhases(P({ status: "root_cause_identified", rca: gatePass })))).toEqual(["done", "current", "future", "future"]);
  });
  it("root_cause_identified after a failed run → ② needs a new plan; ③ shows the failed run", () => {
    const r = issuePhases(P({ status: "root_cause_identified", rca: gatePass, latestRun: { status: "failed", verification_status: "failed" } }));
    expect(pick(r)).toEqual(["plan", "needsNewPlan", "you", "generatePlan"]);
    expect(states(r)).toEqual(["done", "current", "failed", "future"]);
  });
  it("fix_planned → ③ awaiting approval, the approver, 'approve & run'", () => {
    expect(pick(issuePhases(P({ status: "fix_planned", plan: { status: "pending_approval" } })))).toEqual(["run", "awaitingApproval", "approver", "approveAndRun"]);
    expect(pick(issuePhases(P({ status: "fix_planned", plan: null })))).toEqual(["run", "awaitingApproval", "approver", null]);
  });
  it("fix_approved and no run queued → ③ not queued, you, retry; a queued run → executing", () => {
    expect(pick(issuePhases(P({ status: "fix_approved", plan: { status: "approved" }, latestRun: null })))).toEqual(["run", "notQueued", "you", "retryExecution"]);
    expect(pick(issuePhases(P({ status: "fix_approved", latestRun: { status: "pending", verification_status: null } })))).toEqual(["run", "executing", "executor", null]);
  });
  it("fix_executing → ③ executing, the executor, no primary", () => {
    expect(pick(issuePhases(P({ status: "fix_executing" })))).toEqual(["run", "executing", "executor", null]);
  });
  it("fix_executed: pending acceptance → ④ you accept; passed (auto-resolve off) → ④ mark resolved; no verdict → unverified", () => {
    expect(pick(issuePhases(P({ status: "fix_executed", latestRun: { status: "succeeded", verification_status: "pending_acceptance" } }))))
      .toEqual(["accept", "awaitingAcceptance", "acceptor", "acceptResult"]);
    expect(pick(issuePhases(P({ status: "fix_executed", latestRun: { status: "succeeded", verification_status: "passed" } }))))
      .toEqual(["accept", "passed", "you", "markResolved"]);
    expect(pick(issuePhases(P({ status: "fix_executed", latestRun: { status: "succeeded", verification_status: null } }))))
      .toEqual(["accept", "unverified", "you", "markResolved"]);
  });
  it("resolved / dismissed → terminal: no current phase, no primary", () => {
    const r = issuePhases(P({ status: "resolved", rca: gatePass, plan: { status: "executed" }, latestRun: { status: "succeeded", verification_status: "passed" } }));
    expect(pick(r)).toEqual([null, "resolved", null, null]);
    expect(states(r)).toEqual(["done", "done", "done", "done"]);
    expect(states(issuePhases(P({ status: "dismissed", rca: null })))).toEqual(["future", "future", "future", "future"]);
  });
});

describe("issuePhases — list mode (R2) and missing data (Review Focus 1)", () => {
  it("rca undefined (the list has no RCA): root_cause_identified waits for you to review or plan", () => {
    expect(pick(issuePhases({ status: "root_cause_identified" }))).toEqual(["diagnose", "reviewOrPlan", "you", null]);
  });
  it("threshold unknown (settings not loaded) with an RCA → also review-or-plan, never a guessed gate", () => {
    expect(pick(issuePhases({ status: "root_cause_identified", rca: gateFail, threshold: null }))).toEqual(["diagnose", "reviewOrPlan", "you", null]);
  });
  it("root_cause_identified with rca null (the RCA row is gone) → rerun RCA", () => {
    expect(pick(issuePhases(P({ status: "root_cause_identified", rca: null })))).toEqual(["diagnose", "needsReview", "you", "rerunRca"]);
  });
  it("fix_executed in list mode (no run known) → unverified, you", () => {
    expect(pick(issuePhases({ status: "fix_executed" }))).toEqual(["accept", "unverified", "you", null]);
  });
});

describe("currentFixPlan (Review Focus 2)", () => {
  const plan = (id: number, status: FixPlan["status"], created_at: string) => ({ id, status, created_at }) as FixPlan;
  it("the newest plan not executed / failed / rejected; else the newest; null with none", () => {
    expect(currentFixPlan([plan(2, "pending_approval", "2026-10-03T02"), plan(1, "rejected", "2026-10-03T01")])?.id).toBe(2);
    expect(currentFixPlan([plan(1, "rejected", "2026-10-03T01"), plan(2, "pending_approval", "2026-10-03T02")])?.id).toBe(2);
    expect(currentFixPlan([plan(3, "executed", "2026-10-03T03"), plan(2, "failed", "2026-10-03T02")])?.id).toBe(3);
    expect(currentFixPlan([])).toBeNull();
    expect(currentFixPlan(undefined)).toBeNull();
  });
});
```

  `workitemRoutes.test.ts`（Review Focus 4）：

```ts
import { describe, it, expect } from "vitest";
import { CHANGE_HASHES, ISSUE_HASHES, legacyIssuesViewRedirect, legacyIssueTabHash, parseHash } from "@/lib/workitemRoutes";

describe("legacyIssueTabHash", () => {
  it("maps every old ?tab= to its phase; the pre-2.6.1 'issue' tab to diagnose; unknown → null", () => {
    expect(["investigate", "fixPlan", "execution", "verification", "timeline", "issue"].map(legacyIssueTabHash))
      .toEqual(["diagnose", "plan", "run", "accept", "activity", "diagnose"]);
    expect(legacyIssueTabHash("bogus")).toBeNull();
    expect(legacyIssueTabHash(null)).toBeNull();
  });
});
describe("parseHash", () => {
  it("accepts a known anchor with or without '#'; anything else is null", () => {
    expect(parseHash("#accept", ISSUE_HASHES)).toBe("accept");
    expect(parseHash("review", CHANGE_HASHES)).toBe("review");
    expect(parseHash("#review", ISSUE_HASHES)).toBeNull();
    expect(parseHash("#foo", ISSUE_HASHES)).toBeNull();
    expect(parseHash("", ISSUE_HASHES)).toBeNull();
  });
});
describe("legacyIssuesViewRedirect", () => {
  it("?view=resources|signals → the new page, other params kept; anything else stays", () => {
    expect(legacyIssuesViewRedirect("?view=resources&type=EC2")).toBe("/app/resources?type=EC2");
    expect(legacyIssuesViewRedirect("view=signals")).toBe("/app/signals");
    expect(legacyIssuesViewRedirect("?scope=security")).toBeNull();
    expect(legacyIssuesViewRedirect("?view=issues")).toBeNull();
    expect(legacyIssuesViewRedirect("")).toBeNull();
  });
});
```

- [ ] **Step 2: 跑测试确认失败**。
- [ ] **Step 3: 实现** `lib/issuePhases.ts`：

```ts
import type { FixExecution, FixPlan, IssueStatus, RCAResult } from "@/api/types";
import { confidenceBreakdown } from "@/lib/rcaQuality";

export type IssuePhaseId = "diagnose" | "plan" | "run" | "accept";
export type PhaseState = "done" | "current" | "future" | "failed";
export interface PhaseView<I extends string = string> { id: I; state: PhaseState }
export type WaitingFor = "rca_agent" | "you" | "sre_agent" | "approver" | "executor" | "requester" | "acceptor" | null;
export type IssuePrimary = "reviewRca" | "rerunRca" | "generatePlan" | "approveAndRun" | "retryExecution"
  | "acceptResult" | "markResolved" | null;
export type IssueSub = "running" | "needsReview" | "rcaRejected" | "reviewOrPlan" | "toGenerate" | "needsNewPlan"
  | "awaitingApproval" | "notQueued" | "executing" | "awaitingAcceptance" | "passed" | "unverified" | "resolved" | "dismissed";

export interface IssuePhaseInput {
  status: IssueStatus;
  rca?: Pick<RCAResult, "confidence" | "evidence_verified" | "critic_verdict" | "human_verdict"> | null;
  threshold?: number | null;
  plan?: Pick<FixPlan, "status"> | null;
  latestRun?: Pick<FixExecution, "status" | "verification_status"> | null;
}

export interface IssuePhaseResult {
  current: IssuePhaseId | null;
  sub: IssueSub;
  waitingFor: WaitingFor;
  primary: IssuePrimary;
  phases: PhaseView<IssuePhaseId>[];
}

export const ISSUE_PHASES: readonly IssuePhaseId[] = ["diagnose", "plan", "run", "accept"];
const APPROVABLE = new Set(["draft", "pending_approval"]);
const IN_FLIGHT = new Set(["pending", "running"]);

function line(current: IssuePhaseId, failed: IssuePhaseId[] = []): PhaseView<IssuePhaseId>[] {
  const at = ISSUE_PHASES.indexOf(current);
  return ISSUE_PHASES.map((id, i) => ({
    id, state: failed.includes(id) ? "failed" : i < at ? "done" : i === at ? "current" : "future",
  }));
}

function result(current: IssuePhaseId, sub: IssueSub, waitingFor: WaitingFor, primary: IssuePrimary,
                failed: IssuePhaseId[] = []): IssuePhaseResult {
  return { current, sub, waitingFor, primary, phases: line(current, failed) };
}

/** Spec §4: where an issue is, why, who moves it next and the page's one primary button. `rca: undefined`
 *  is list mode (R2): the list has no RCA, so root_cause_identified cannot tell review from plan. */
export function issuePhases(i: IssuePhaseInput): IssuePhaseResult {
  const run = i.latestRun ?? null;
  switch (i.status) {
    case "open":
    case "investigating":
    case "acknowledged":
      return result("diagnose", "running", "rca_agent", null);
    case "root_cause_identified": {
      if (run && (run.verification_status === "failed" || run.status === "failed" || run.status === "aborted"
                  || run.status === "rolled_back")) {
        return result("plan", "needsNewPlan", "you", "generatePlan", ["run"]);
      }
      if (i.rca === undefined) return result("diagnose", "reviewOrPlan", "you", null);
      if (i.rca === null) return result("diagnose", "needsReview", "you", "rerunRca");
      if (i.rca.human_verdict === "incorrect") return result("diagnose", "rcaRejected", "you", "rerunRca");
      if (i.rca.human_verdict === "correct") return result("plan", "toGenerate", "you", "generatePlan");
      const gate = confidenceBreakdown(i.rca, i.threshold).gatePassed;
      if (gate === null) return result("diagnose", "reviewOrPlan", "you", null);
      return gate ? result("plan", "toGenerate", "sre_agent", "generatePlan")
                  : result("diagnose", "needsReview", "you", "reviewRca");
    }
    case "fix_planned":
      return result("run", "awaitingApproval", "approver", i.plan && APPROVABLE.has(i.plan.status) ? "approveAndRun" : null);
    case "fix_approved":
      return run && IN_FLIGHT.has(run.status) ? result("run", "executing", "executor", null)
                                               : result("run", "notQueued", "you", "retryExecution");
    case "fix_executing":
      return result("run", "executing", "executor", null);
    case "fix_executed":
      if (run?.verification_status === "pending_acceptance") return result("accept", "awaitingAcceptance", "acceptor", "acceptResult");
      if (run?.verification_status === "passed") return result("accept", "passed", "you", "markResolved");
      return result("accept", "unverified", "you", run ? "markResolved" : null);
    case "resolved":
    case "dismissed": {
      const reached: Record<IssuePhaseId, boolean> = {
        diagnose: !!i.rca, plan: !!i.plan, run: !!run, accept: run?.verification_status === "passed" || (i.status === "resolved" && !!run),
      };
      return { current: null, sub: i.status, waitingFor: null, primary: null,
               phases: ISSUE_PHASES.map((id) => ({ id, state: reached[id] ? "done" : "future" })) };
    }
  }
}

const TERMINAL_PLAN = new Set(["executed", "failed", "rejected"]);

/** The plan the page shows and approves: the newest not executed / failed / rejected, else the newest. */
export function currentFixPlan(plans: FixPlan[] | undefined): FixPlan | null {
  const sorted = [...(plans ?? [])].sort((a, b) => b.created_at.localeCompare(a.created_at) || b.id - a.id);
  return sorted.find((p) => !TERMINAL_PLAN.has(p.status)) ?? sorted[0] ?? null;
}
```

  （`resolved` 的测试用例 rca/plan/run 都在 → 四段 done；`dismissed` 什么都没有 → 四段 future。`switch` 覆盖 `IssueStatus` 全部 10 个值，tsc 会因缺 return 报错来守住新增状态。）
  `lib/workitemRoutes.ts`：

```ts
/** Old links into the work-item pages (spec §3): IssueDetail's ?tab= and the Issues hub's ?view=. */
export const ISSUE_HASHES = ["diagnose", "plan", "run", "accept", "activity"] as const;
export const CHANGE_HASHES = ["request", "review", "plan", "run", "accept", "activity"] as const;

const ISSUE_TAB_TO_HASH: Record<string, string> = {
  investigate: "diagnose", issue: "diagnose", fixPlan: "plan", execution: "run", verification: "accept", timeline: "activity",
};

export function legacyIssueTabHash(tab: string | null): string | null {
  return tab != null && Object.prototype.hasOwnProperty.call(ISSUE_TAB_TO_HASH, tab) ? ISSUE_TAB_TO_HASH[tab] : null;
}

export function parseHash(hash: string, allowed: readonly string[]): string | null {
  const h = hash.replace(/^#/, "");
  return allowed.includes(h) ? h : null;
}

export function legacyIssuesViewRedirect(search: string): string | null {
  const q = new URLSearchParams(search);
  const v = q.get("view");
  if (v !== "resources" && v !== "signals") return null;
  q.delete("view");
  const rest = q.toString();
  return `/app/${v}${rest ? `?${rest}` : ""}`;
}
```

- [ ] **Step 4: 跑测试确认通过**。
- [ ] **Step 5: 前端门禁**。
- [ ] **Step 6: Commit**：`feat(web): issue phase model and old-link mapping (pure, tested)`。

### Task 9: 模板组件 StatusLine / PhaseCard / FactsRail / PlanView

**Files:**
- Create: `$FE/src/components/workitem/StatusLine.tsx`、`PhaseCard.tsx`、`FactsRail.tsx`、`$FE/src/components/plans/PlanView.tsx`
- Modify: `$FE/src/lib/plans.ts`（+`planCounts`）、locale
- Test: `$FE/src/__tests__/plans.test.ts`（追加 `planCounts`）

**Interfaces:**
- Consumes：`PhaseState`（Task 8）、`FactRow`（Task 4）、`planStepMarks`（`lib/changeDetail`）。
- Produces（Task 11、13 用，props 精确如下）：

```ts
// StatusLine.tsx
export interface StatusLineAction { key: string; label: string; run: () => void; disabled?: boolean; variant?: "default" | "destructive" }
export interface StatusLineProps {
  refLabel: string;                 // "I#1" / "C#1"
  title: string;
  badges?: React.ReactNode;          // severity / risk / change type chips
  statusLabel: string;               // localized sub-state, e.g. 根因待复核
  tone: "info" | "warn" | "bad" | "ok";
  reason?: string | null;            // at most two lines; the page's ONLY copy of a failure sentence
  waiting?: string | null;           // localized "等你：…" / "等执行器"
  primary?: StatusLineAction | null; // the page's ONE primary button
  menu?: StatusLineAction[];         // the "⋯" menu (secondary actions)
  error?: string | null;             // a 409/403 message, shown in an ErrorBanner under the line
  onDismissError?: () => void;
  backTo: string; backLabel: string;
}
export function StatusLine(p: StatusLineProps): JSX.Element
// PhaseCard.tsx
export interface PhaseCardProps { id: string; index: number; title: string; state: PhaseState; summary?: string | null;
  futureHint?: string | null; badge?: React.ReactNode; open?: boolean; onToggle?: (open: boolean) => void; children?: React.ReactNode }
export function PhaseCard(p: PhaseCardProps): JSX.Element
// FactsRail.tsx
export function FactsRail(p: { title: string; rows: FactRow[]; t: (k: string) => string; extra?: React.ReactNode }): JSX.Element
// PlanView.tsx
export function PlanView(p: { plan: FixPlan; stepsDiff?: ChangeStepsDiff | null; t: (k: string) => string }): JSX.Element
// lib/plans.ts
export function planCounts(plan: Pick<FixPlan, "steps" | "pre_checks" | "post_checks" | "rollback_plan">): { steps: number; preChecks: number; postChecks: number; rollback: number }
```

- [ ] **Step 1: 写失败的测试**（`plans.test.ts` 追加）

```ts
import { planCounts } from "@/lib/plans";

describe("planCounts", () => {
  it("counts steps / pre / post checks; rollback = its steps, or 1 for a non-empty plan without a steps list", () => {
    expect(planCounts({ steps: [{}, {}], pre_checks: [{}], post_checks: [{}, {}, {}], rollback_plan: { steps: ["a", "b"] } }))
      .toEqual({ steps: 2, preChecks: 1, postChecks: 3, rollback: 2 });
    expect(planCounts({ steps: [], pre_checks: [], post_checks: [], rollback_plan: { description: "undo" } }).rollback).toBe(1);
    expect(planCounts({ steps: [], pre_checks: [], post_checks: [], rollback_plan: {} }).rollback).toBe(0);
    expect(planCounts({ steps: null as unknown as unknown[], pre_checks: undefined as unknown as unknown[], post_checks: [], rollback_plan: null as unknown as Record<string, unknown> }))
      .toEqual({ steps: 0, preChecks: 0, postChecks: 0, rollback: 0 });
  });
});
```

- [ ] **Step 2: 跑测试确认失败**。
- [ ] **Step 3: 实现**
  - `lib/plans.ts` 追加：

```ts
/** The four counts PlanView's header shows ("1 step · 3 pre-checks · 3 post-checks · rollback 1"). */
export function planCounts(plan: Pick<FixPlan, "steps" | "pre_checks" | "post_checks" | "rollback_plan">) {
  const len = (v: unknown) => (Array.isArray(v) ? v.length : 0);
  const rb = plan.rollback_plan && typeof plan.rollback_plan === "object" ? plan.rollback_plan : {};
  const rollback = Array.isArray((rb as Record<string, unknown>).steps) ? len((rb as Record<string, unknown>).steps)
    : Object.keys(rb).length > 0 ? 1 : 0;
  return { steps: len(plan.steps), preChecks: len(plan.pre_checks), postChecks: len(plan.post_checks), rollback };
}
```
  （`import type { FixPlan } from "@/api/types"` 若文件里还没有。）
  - `StatusLine.tsx`：一张 `Card`。第一行：返回链接（`← {backLabel}`）。第二行：`refLabel` 等宽灰底 chip、`badges`、`title`（`text-2xl font-semibold`）。第三行（`flex flex-wrap items-start gap-3`）：左侧圆点（按 `tone`：info 蓝 / warn 琥珀 / bad 红 / ok 绿）+ `statusLabel`（`font-medium`）；其下 `reason`（`line-clamp-2`，点击展开全文——用一个 `expanded` state 切换 `line-clamp-2`）；`waiting` 文本（`text-sm text-muted-foreground`）；右侧固定（`ml-auto shrink-0 whitespace-nowrap`）`primary` 按钮（`bg-primary text-primary-foreground`，`variant=destructive` 时红）和「⋯」按钮。「⋯」打开一个下拉菜单：`absolute right-0 mt-1 z-20 min-w-48 rounded-lg border bg-popover shadow-lg animate-[slideInRight_0.2s_ease-out]`，列 `menu` 项；ESC 与点外部关闭（`useEffect` 绑 `keydown`/`mousedown`，打开时才绑）。`menu` 为空时不渲染「⋯」。`error` 非空时在卡下方渲染 `<ErrorBanner message={error} onRetry={onDismissError} actionLabel={t("common.close")}/>`（StatusLine 内 `useLocale()`）。
  - `PhaseCard.tsx`：`<section id={id}>`；卡头是 `<button aria-expanded>`（Enter/空格天然可用），左侧圆形序号：done = 绿色 ✓，current = 蓝底序号，failed = 红色 `!`，future = 灰色序号；标题；`summary`（done/failed 折叠时显示的一句话）；右侧 `badge`。展开规则：受控（`open` + `onToggle`）或非受控默认值 `state === "current" || state === "failed"`。future 卡不可展开，只在卡头下显示 `futureHint`（`text-xs text-muted-foreground`）。failed 卡 `border-red-500/40`，current 卡 `border-primary/40`。
  - `FactsRail.tsx`：`Card` + 标题 + `<dl>`：每行 `dt`（`t(row.labelKey)`）/ `dd`（`kind === "date"` → `formatFullDate`；`kind === "mono"` → `font-mono text-xs break-all`；`href` → `<Link>`）。`extra` 渲染在列表下方（问题页放合并信号入口）。
  - `PlanView.tsx`：把现在 `IssueDetail.tsx` FixPlanTab 的方案主体（风险徽章、`FixPlanStatusBadge`、`planLabel`、标题、哈希行 `plans.hash` + `plans.approvedVersion`、summary markdown、`RunbookStep` 列表、预检 / 后检 `CheckItem`、`RollbackPlan`）与 `ChangeDetail.tsx` 方案卡的 `steps_diff` 渲染（`planStepMarks` 的摘要行、逐步 added/modified 标注、removed 列表）合成一个组件。头部加一行计数：`t("plan.counts")` 的 `{steps}{pre}{post}{rollback}` 用 `planCounts`；`stepsDiff` 为 `undefined`（修复方案）时完全不渲染差异部分；为 `null`（变更但申请没带步骤）时也不渲染。哈希一致性：`plan.approved_hash` 存在时，`approved_hash === content_hash` 显示 `t("plan.hashMatches")`（绿），否则 `t("plan.hashDrifted")`（红）。
  - locale：`plan.counts` {steps} steps · {pre} pre-checks · {post} post-checks · rollback {rollback} / {steps} 步 · 预检 {pre} · 后检 {post} · 回滚 {rollback}；`plan.hashMatches` Matches the approved content / 与批准内容一致；`plan.hashDrifted` Changed since approval / 批准后内容已变；`workitem.menu` More actions / 更多操作；`workitem.expandAll` Expand all / 全部展开；`workitem.collapseAll` Collapse all / 全部折叠。
- [ ] **Step 4: 跑测试确认通过**。
- [ ] **Step 5: 前端门禁**（组件未被页面引用也要过 tsc）。
- [ ] **Step 6: Commit**：`feat(web): work-item template components and the shared PlanView`。

### Task 10: 「你的判断」（P9）

**Files:**
- Create: `$FE/src/lib/verdict.ts`、`$FE/src/components/issue/VerdictBlock.tsx`
- Modify: locale
- Test: `$FE/src/__tests__/verdict.test.ts`

**Interfaces:**
- Consumes：`useRcaFeedback(issueId)`（`hooks/useSignals`，payload `{verdict?, location_verdict?, note?}`）、`useIssueFeedback()`（`hooks/useAgentMemory`，`{issueId, feedback: {type, note?, confidence}}`）。
- Produces：

```ts
export type VerdictChoice = "correct" | "partial" | "rcaWrong" | "falsePositive";
export const VERDICT_CHOICES: readonly VerdictChoice[];
export interface VerdictRequests {
  rcaFeedback: { verdict?: "correct" | "incorrect"; location_verdict?: LocationVerdict; note?: string } | null;
  issueFeedback: { type: "confirmed" | "false_positive"; note?: string; confidence: number } | null;
}
export function locationJudgeable(rca: Pick<RCAResult, "location_status" | "location_verdict"> | null | undefined): boolean
export function choiceAvailable(choice: VerdictChoice, rca: Pick<RCAResult, "location_status" | "location_verdict"> | null | undefined): boolean
export function noteRequired(choice: VerdictChoice): boolean
export function verdictRequests(choice: VerdictChoice, rca: Pick<RCAResult, "location_status" | "location_verdict"> | null | undefined, note: string): VerdictRequests
export function VerdictBlock(p: { issueId: number; rca: RCAResult | null | undefined; onDone?: () => void }): JSX.Element
```

- [ ] **Step 1: 写失败的测试**

```ts
import { describe, it, expect } from "vitest";
import { choiceAvailable, locationJudgeable, noteRequired, verdictRequests } from "@/lib/verdict";

const valid = { location_status: "valid" as const, location_verdict: null };
const absent = { location_status: "absent" as const, location_verdict: null };

describe("verdict (P9): one block, the existing two endpoints", () => {
  it("both right → RCA correct + location correct, then confirmed", () => {
    expect(verdictRequests("correct", valid, "")).toEqual({
      rcaFeedback: { verdict: "correct", location_verdict: "correct" },
      issueFeedback: { type: "confirmed", confidence: 5 },
    });
  });
  it("no judgeable location → the location verdict is left out (the backend would 409)", () => {
    expect(verdictRequests("correct", absent, "").rcaFeedback).toEqual({ verdict: "correct" });
    expect(verdictRequests("correct", { location_status: "valid", location_verdict: "partial" }, "").rcaFeedback)
      .toEqual({ verdict: "correct" }); // already judged once
  });
  it("partly right needs a judgeable location", () => {
    expect(choiceAvailable("partial", valid)).toBe(true);
    expect(choiceAvailable("partial", absent)).toBe(false);
    expect(choiceAvailable("partial", null)).toBe(false);
    expect(verdictRequests("partial", valid, "").rcaFeedback).toEqual({ verdict: "correct", location_verdict: "partial" });
  });
  it("root cause wrong → RCA incorrect (+ location incorrect when judgeable) with the note; no issue feedback", () => {
    expect(verdictRequests("rcaWrong", valid, "it was the HPA")).toEqual({
      rcaFeedback: { verdict: "incorrect", location_verdict: "incorrect", note: "it was the HPA" }, issueFeedback: null,
    });
  });
  it("not an issue → false_positive with the note only (the backend dismisses the issue)", () => {
    expect(verdictRequests("falsePositive", null, " planned chaos ")).toEqual({
      rcaFeedback: null, issueFeedback: { type: "false_positive", note: "planned chaos", confidence: 4 },
    });
  });
  it("notes are required for the two negative choices; the RCA choices need an RCA", () => {
    expect(["correct", "partial", "rcaWrong", "falsePositive"].map((c) => noteRequired(c as never))).toEqual([false, false, true, true]);
    expect(choiceAvailable("correct", null)).toBe(false);
    expect(choiceAvailable("rcaWrong", null)).toBe(false);
    expect(choiceAvailable("falsePositive", null)).toBe(true);
    expect(locationJudgeable({ location_status: "partial", location_verdict: null })).toBe(true);
  });
});
```

- [ ] **Step 2: 跑测试确认失败**。
- [ ] **Step 3: 实现** `lib/verdict.ts`：

```ts
import type { LocationVerdict, RCAResult } from "@/api/types";

/** "Your verdict" (P9): one choice replaces 👍👎, the location's three buttons and False positive / Confirmed.
 *  It maps onto the two existing endpoints — POST /health-issues/{id}/rca-feedback, then /feedback. */
export type VerdictChoice = "correct" | "partial" | "rcaWrong" | "falsePositive";
export const VERDICT_CHOICES: readonly VerdictChoice[] = ["correct", "partial", "rcaWrong", "falsePositive"];

type LocInput = Pick<RCAResult, "location_status" | "location_verdict"> | null | undefined;

export interface VerdictRequests {
  rcaFeedback: { verdict?: "correct" | "incorrect"; location_verdict?: LocationVerdict; note?: string } | null;
  issueFeedback: { type: "confirmed" | "false_positive"; note?: string; confidence: number } | null;
}

/** The backend takes a location verdict only for a valid / partial location, and this block sends it once. */
export function locationJudgeable(rca: LocInput): boolean {
  return !!rca && (rca.location_status === "valid" || rca.location_status === "partial") && !rca.location_verdict;
}

export function choiceAvailable(choice: VerdictChoice, rca: LocInput): boolean {
  if (choice === "falsePositive") return true;
  if (!rca) return false;
  return choice === "partial" ? locationJudgeable(rca) : true;
}

export function noteRequired(choice: VerdictChoice): boolean {
  return choice === "rcaWrong" || choice === "falsePositive";
}

export function verdictRequests(choice: VerdictChoice, rca: LocInput, note: string): VerdictRequests {
  const n = note.trim();
  const withNote = <T extends object>(o: T) => (n ? { ...o, note: n } : o);
  const loc = locationJudgeable(rca);
  switch (choice) {
    case "correct":
      return { rcaFeedback: withNote({ verdict: "correct" as const, ...(loc ? { location_verdict: "correct" as const } : {}) }),
               issueFeedback: { type: "confirmed", confidence: 5 } };
    case "partial":
      return { rcaFeedback: withNote({ verdict: "correct" as const, location_verdict: "partial" as const }),
               issueFeedback: { type: "confirmed", confidence: 5 } };
    case "rcaWrong":
      return { rcaFeedback: withNote({ verdict: "incorrect" as const, ...(loc ? { location_verdict: "incorrect" as const } : {}) }),
               issueFeedback: null };
    case "falsePositive":
      return { rcaFeedback: null, issueFeedback: withNote({ type: "false_positive" as const, confidence: 4 }) };
  }
}
```

  `VerdictBlock.tsx`：
  - `rca?.human_verdict` 已有时：只读显示「已判断：{正确|错误}」+ 定位判断（`location_verdict` 与 by/at，沿用现有 `location.verdict.*` 文案），不再给选项（与今天一致：判断过就不再出按钮）。
  - 否则：四个 radio（`VERDICT_CHOICES`，`choiceAvailable` 为 false 的置灰并在旁边小字说明原因：无 RCA → `verdict.needRca`，定位不可判 → `location.cannotJudge`）；`noteRequired(choice)` 时显示必填 textarea（maxLength 2000）；「提交判断」按钮在 `!choice || (noteRequired(choice) && !note.trim())` 时禁用。
  - 提交：`const req = verdictRequests(choice, rca, note)`；先 `await rcaFb.mutateAsync(req.rcaFeedback)`（非 null 时），再 `await issueFb.mutateAsync({ issueId, feedback: req.issueFeedback })`（非 null 时）；第二步失败时显示 `t("verdict.partialSaved")` + 后端原话（第一步已生效，不回滚）；成功调 `onDone?.()`。`issueFb` 成功后 `useIssueFeedback` 自己会 invalidate `["anomaly", id]`、`["anomalies"]`。
  - locale：

| 键 | en | zh |
|---|---|---|
| `verdict.title` | Your verdict | 你的判断 |
| `verdict.hint` | One submit records both the root-cause verdict and the location verdict | 一次提交，同时记录根因结论与定位判断 |
| `verdict.choice.correct` | Root cause and location are both right | 根因和定位都正确 |
| `verdict.choice.partial` | Partly right (root cause right, location incomplete or misranked) | 部分正确（根因对，定位不全或排序不对） |
| `verdict.choice.rcaWrong` | The root cause is wrong | 根因错误 |
| `verdict.choice.falsePositive` | This is not an issue (false positive) | 这不是问题（误报） |
| `verdict.note` | Note | 备注 |
| `verdict.noteRequired` | Required for this choice | 这一项必填 |
| `verdict.submit` | Submit verdict | 提交判断 |
| `verdict.needRca` | Needs an RCA result | 需要先有 RCA 结果 |
| `verdict.recorded` | Recorded: {verdict} | 已判断：{verdict} |
| `verdict.partialSaved` | The root-cause verdict was saved; the issue feedback failed: | 根因判断已保存；问题反馈失败： |

- [ ] **Step 4: 跑测试确认通过**。
- [ ] **Step 5: 前端门禁**。
- [ ] **Step 6: Commit**：`feat(web): one "your verdict" block over the existing feedback endpoints`。

### Task 11: 问题详情套用模板（P1、P3 问题侧、P7、P10、P14）

**Files:**
- Create: `$FE/src/lib/issueDetailModel.ts`
- Rewrite: `$FE/src/pages/IssueDetail.tsx`
- Modify: locale
- Test: `$FE/src/__tests__/issueDetailModel.test.ts`

**Interfaces:**
- Consumes：Task 3–10 的全部导出；现有 hooks（`useAnomaly`、`useAnomalyRca`、`useFixPlans`、`useIssueExecutions`、`useIssueTimeline`、`useUpdateIssueStatus`、`useCancelExecution`、`useApproveFixPlan`、`useRejectFixPlan`、`useExecuteFixPlan`、`useAcceptExecution`、`useResource`、`useSettings`、`useAuth`）。
- Produces：

```ts
export interface ReasonRef { key: string; params?: Record<string, string> } // or literal text:
export type Reason = ReasonRef | { text: string };
export interface IssueDetailModel {
  phase: IssuePhaseResult;
  statusKey: string;          // `workitem.sub.<sub>`
  tone: "info" | "warn" | "bad" | "ok";
  reason: Reason | null;      // the ONE place a failure / pause sentence appears
  waitingKey: string | null;  // `workitem.wait.<waitingFor>`
  primaryKey: string | null;  // `workitem.primary.<primary>`
  menu: IssueMenuItem[];      // see table
  plan: FixPlan | null;       // currentFixPlan
  otherPlans: FixPlan[];
  latestRun: FixExecution | null;
  pendingRun: FixExecution | null; // issueStatuses(...).pending — acceptance only on the latest run at fix_executed
}
export type IssueMenuItem = "runRca" | "skipReviewGeneratePlan" | "markResolved" | "dismiss" | "reopen" | "cancelRun";
export function issueDetailModel(input: { issue: Pick<HealthIssue, "status">; rca: RCAResult | null | undefined; threshold: number | null | undefined; plans: FixPlan[] | undefined; executions: FixExecution[] | undefined }): IssueDetailModel
```

- [ ] **Step 1: 写失败的测试**（I#1 形状 + 关键行；断言「唯一主按钮」「原因只一处」）

```ts
import { describe, it, expect } from "vitest";
import type { FixExecution, FixPlan, RCAResult } from "@/api/types";
import { issueDetailModel } from "@/lib/issueDetailModel";

const rcaI1 = { confidence: 0.57, evidence_verified: false, critic_verdict: "weak", human_verdict: null } as RCAResult;
const run = (x: Partial<FixExecution>) => ({ id: 4, fix_plan_id: 1, status: "succeeded", verification_status: null,
  verification_reason: null, acceptance_note: null, error_message: null, created_at: "2026-10-03T10:00:00", ...x }) as FixExecution;

describe("issueDetailModel", () => {
  it("I#1: one primary (review root cause), the pause explained with the gate's numbers, menu holds the rest", () => {
    const m = issueDetailModel({ issue: { status: "root_cause_identified" }, rca: rcaI1, threshold: 0.6, plans: [], executions: [] });
    expect(m.primaryKey).toBe("workitem.primary.reviewRca");
    expect(m.statusKey).toBe("workitem.sub.needsReview");
    expect(m.reason).toEqual({ key: "workitem.reason.rcaBelowGate", params: { conf: "57%", threshold: "60%" } });
    expect(m.menu).toEqual(["runRca", "skipReviewGeneratePlan", "markResolved", "dismiss"]);
    expect(m.tone).toBe("warn");
  });
  it("a failed run: the failure sentence is the status line's reason — the run's own text, once", () => {
    const failed = run({ status: "failed", verification_status: "failed", verification_reason: "post-check 2 failed" });
    const m = issueDetailModel({ issue: { status: "root_cause_identified" }, rca: { ...rcaI1, confidence: 0.9, evidence_verified: true } as RCAResult,
                                 threshold: 0.6, plans: [], executions: [failed] });
    expect(m.reason).toEqual({ text: "post-check 2 failed" });
    expect(m.tone).toBe("bad");
    expect(JSON.stringify(m).split("post-check 2 failed").length - 1).toBe(2); // the reason + the run row itself, nothing else
  });
  it("pending acceptance only for the newest run while the issue is at fix_executed", () => {
    const pend = run({ id: 5, verification_status: "pending_acceptance", verification_reason: "no post-checks declared" });
    const m = issueDetailModel({ issue: { status: "fix_executed" }, rca: rcaI1, threshold: 0.6, plans: [], executions: [pend] });
    expect(m.pendingRun?.id).toBe(5);
    expect(m.primaryKey).toBe("workitem.primary.acceptResult");
    expect(m.reason).toEqual({ text: "no post-checks declared" });
    const moved = issueDetailModel({ issue: { status: "resolved" }, rca: rcaI1, threshold: 0.6, plans: [], executions: [pend] });
    expect(moved.pendingRun).toBeNull();
  });
  it("no RCA at all (Review Focus 1): running, no primary, menu offers Run RCA", () => {
    const m = issueDetailModel({ issue: { status: "open" }, rca: null, threshold: 0.6, plans: undefined, executions: undefined });
    expect([m.primaryKey, m.reason]).toEqual([null, null]);
    expect(m.menu[0]).toBe("runRca");
  });
  it("approved but not queued → retry is the primary and the reason says so", () => {
    const plan = { id: 1, status: "approved", created_at: "2026-10-03T09:00:00" } as FixPlan;
    const m = issueDetailModel({ issue: { status: "fix_approved" }, rca: rcaI1, threshold: 0.6, plans: [plan], executions: [] });
    expect(m.primaryKey).toBe("workitem.primary.retryExecution");
    expect(m.reason).toEqual({ key: "workitem.reason.notQueued" });
  });
  it("terminal: no primary; menu has reopen only", () => {
    const m = issueDetailModel({ issue: { status: "dismissed" }, rca: null, threshold: 0.6, plans: [], executions: [] });
    expect([m.primaryKey, m.menu]).toEqual([null, ["reopen"]]);
  });
});
```

- [ ] **Step 2: 跑测试确认失败**。
- [ ] **Step 3: 实现** `lib/issueDetailModel.ts`：

```ts
import type { FixExecution, FixPlan, HealthIssue, RCAResult } from "@/api/types";
import { issueStatuses, latestExecution, newestFirst } from "@/lib/issueDetail";
import { currentFixPlan, issuePhases, type IssuePhaseResult } from "@/lib/issuePhases";
import { confidenceBreakdown } from "@/lib/rcaQuality";

export interface ReasonRef { key: string; params?: Record<string, string> }
export type Reason = ReasonRef | { text: string };
export type IssueMenuItem = "runRca" | "skipReviewGeneratePlan" | "markResolved" | "dismiss" | "reopen" | "cancelRun";

export interface IssueDetailModel {
  phase: IssuePhaseResult;
  statusKey: string;
  tone: "info" | "warn" | "bad" | "ok";
  reason: Reason | null;
  waitingKey: string | null;
  primaryKey: string | null;
  menu: IssueMenuItem[];
  plan: FixPlan | null;
  otherPlans: FixPlan[];
  latestRun: FixExecution | null;
  pendingRun: FixExecution | null;
}

const pct = (x: number) => `${Math.round(x * 100)}%`;
const runText = (r: FixExecution | null) =>
  r ? r.acceptance_note || r.verification_reason || r.error_message || null : null;

/** IssueDetail's view model: everything the status line and the phase cards say, i18n-free (keys + data). */
export function issueDetailModel(input: {
  issue: Pick<HealthIssue, "status">;
  rca: RCAResult | null | undefined;
  threshold: number | null | undefined;
  plans: FixPlan[] | undefined;
  executions: FixExecution[] | undefined;
}): IssueDetailModel {
  const { issue, rca, threshold } = input;
  const plan = currentFixPlan(input.plans);
  const latestRun = latestExecution(input.executions);
  // undefined (still loading) keeps list mode — never a flash of "rerun RCA"; null means there is no RCA
  const phase = issuePhases({ status: issue.status, rca, threshold, plan, latestRun });
  const pendingRun = issueStatuses(issue, input.executions).pending;

  let reason: Reason | null = null;
  switch (phase.sub) {
    case "needsReview":
      if (rca) {
        const b = confidenceBreakdown(rca, threshold);
        reason = b.criticPenalty ? { key: "workitem.reason.rcaRefuted" }
          : { key: "workitem.reason.rcaBelowGate", params: { conf: pct(b.final), threshold: pct(b.threshold ?? 0) } };
      } else reason = { key: "workitem.reason.noRca" };
      break;
    case "rcaRejected": reason = { key: "workitem.reason.rcaRejected" }; break;
    case "needsNewPlan": { const t = runText(latestRun); reason = t ? { text: t } : { key: "workitem.reason.runFailed" }; break; }
    case "notQueued": reason = { key: "workitem.reason.notQueued" }; break;
    case "awaitingAcceptance": { const t = runText(latestRun); reason = t ? { text: t } : null; break; }
    default: reason = null;
  }

  const terminal = issue.status === "resolved" || issue.status === "dismissed";
  const menu: IssueMenuItem[] = terminal ? ["reopen"] : [
    "runRca",
    ...(issue.status === "root_cause_identified" && phase.primary !== "generatePlan" ? ["skipReviewGeneratePlan" as const] : []),
    ...(phase.sub === "executing" && latestRun && (latestRun.status === "pending" || latestRun.status === "running") ? ["cancelRun" as const] : []),
    ...(phase.primary === "markResolved" ? [] : ["markResolved" as const]),
    "dismiss",
  ];

  const tone = phase.sub === "needsNewPlan" ? "bad"
    : ["needsReview", "rcaRejected", "notQueued", "awaitingAcceptance", "awaitingApproval", "unverified", "reviewOrPlan"].includes(phase.sub) ? "warn"
    : phase.sub === "passed" || phase.sub === "resolved" ? "ok" : "info";

  return {
    phase,
    statusKey: `workitem.sub.${phase.sub}`,
    tone,
    reason,
    waitingKey: phase.waitingFor ? `workitem.wait.${phase.waitingFor}` : null,
    primaryKey: phase.primary ? `workitem.primary.${phase.primary}` : null,
    menu,
    plan,
    otherPlans: newestFirstPlans(input.plans).filter((p) => p.id !== plan?.id),
    latestRun,
    pendingRun,
  };
}

function newestFirstPlans(plans: FixPlan[] | undefined): FixPlan[] {
  return [...(plans ?? [])].sort((a, b) => b.created_at.localeCompare(a.created_at) || b.id - a.id);
}
// newestFirst (runs) is re-exported for the page's run list
export { newestFirst };
```

  （测试里「失败句出现 2 次」= `reason.text` 一次 + `latestRun.verification_reason` 本身一次；页面只渲染 `reason`，执行卡只渲染检查证据——见下。）

  **页面 `IssueDetail.tsx`（整页重写，opus）**——结构：

```
<div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_320px]">
  <div className="space-y-4 min-w-0">            ← 左栏
    <StatusLine …/>                               ← 唯一状态指示（P1）
    {pendingRun && <待验收横幅/>}                  ← 只在 phase.current === "accept" 时由 ④ 卡承担，见下
    [全部展开/折叠] 一个小按钮
    <PhaseCard id="diagnose" …>  RCA + 定位 + 局部图（compact）+ VerdictBlock
    <PhaseCard id="plan" …>      PlanView + 其它版本
    <PhaseCard id="run" …>       审批记录 + 批准/拒绝（未批准时）+ 执行证据
    <PhaseCard id="accept" …>    判定 + 接受/拒绝
  </div>
  <aside className="space-y-4">                    ← 右栏
    <FactsRail rows={factRows(a, anchor)} extra={合并信号入口}/>
    <Card> 动态 ActivityList(toActivity(timeline.data)) </Card>
  </aside>
</div>
```

  逐条要求（实现者逐条在报告里勾）：
  1. **数据 hooks 原样保留**：现有 9 个 hooks + `useResource(a.resource_ref ?? 0)` + `useSettings()`。`issueDetailModel({ issue: a, rca: rca.isLoading ? undefined : (rca.data ?? null), threshold: settings.data?.rca_min_confidence_for_autofix, plans: fixPlans.data, executions: executions.data })`（加载中传 `undefined`，加载完没有 RCA 传 `null`）。
  2. **轮询与失效**（保留 94530d0 行为）：现有 `lastStatus` ref + `useEffect`（状态变化 → invalidate `["issue-executions", issueId]` 与 `["fix-plans"]`）原样搬过来；`useIssueExecutions` / `useAnomaly` 现有的 refetchInterval 逻辑在 hooks 里，不动。
  3. **URL**：页面挂载时若 `?tab=` 存在 → `legacyIssueTabHash(tab)` 得到 hash，`navigate({ search: <去掉 tab 的其余参数>, hash }, { replace: true })`；`location.hash` 经 `parseHash(hash, ISSUE_HASHES)` 得到目标：阶段 id → 该 PhaseCard 受控展开并 `scrollIntoView({ block: "start" })`；`activity` → 右栏动态卡展开并滚到它；未知 hash 忽略。点击 PhaseCard 头切换展开时用 `replace` 写 hash（不产生历史记录）。
  4. **StatusLine**：`refLabel=\`I#${a.id}\``、`title=a.title`、`badges=<SeverityBadge/>`、`statusLabel=t(model.statusKey)`、`tone=model.tone`、`reason`（`"text" in reason ? reason.text : fill(t(reason.key), reason.params)`）、`waiting=model.waitingKey && t(model.waitingKey)`、`backTo="/app/issues"`（`backLabel=t("nav.issues")`）。主按钮映射：

| `phase.primary` | 处理 |
|---|---|
| `reviewRca` | 展开 diagnose 卡并滚到 VerdictBlock（`document.getElementById("verdict")`） |
| `rerunRca` | 现有 `triggerRca()` |
| `generatePlan` | 现有 `triggerFixPlan()` |
| `approveAndRun` | 打开修复方案批准 ReasonDialog（见 6） |
| `retryExecution` | `useConfirm` 确认（`t("workitem.confirm.retry")`）后 `executeMut.mutate(plan.id)` |
| `acceptResult` | 打开接受 ReasonDialog（现有 `AcceptanceActions` 的 accepted 分支，理由必填） |
| `markResolved` | `useConfirm(t("workitem.confirm.resolve"))` → `updateStatus("resolved")` |

  「⋯」菜单映射：`runRca` → `triggerRca`；`skipReviewGeneratePlan` → `triggerFixPlan`；`markResolved` → 确认后 resolved；`dismiss` → 确认（destructive，`t("workitem.confirm.dismiss")`）后 `dismissed`；`reopen` → 确认后 `open`；`cancelRun` → 现有 cancel 确认后 `cancelExecMut.mutate(latestRun.id)`。`actionMsg` 的错误串进 StatusLine 的 `error`。
  5. **① 诊断卡**：`summary`（折叠时）= `t("workitem.summary.diagnose")` 填 `{conf}` / `{verdict}`；内容 = 现有 RcaSection（Task 3 已改好；删除其中 👍👎，因为 VerdictBlock 取代它）、现有 LocationSection 的**展示部分**（候选、路径、dropped；删除它的三个定位按钮，VerdictBlock 取代）、「贡献因素 / 建议」各用 `<details>` 折叠、`<details>` 折叠的局部拓扑 `<LocalGraph subject={{ issueId: a.id }} path={rca.data?.location?.path} compact />`、`<div id="verdict"><VerdictBlock issueId={a.id} rca={rca.data} onDone={() => { anomaly.refetch(); rca.refetch(); }} /></div>`（问题为终态时不渲染 VerdictBlock）。无 RCA 时卡内只写 `t("issues.noRca")` 与 `t("issues.rcaHint")`，**不放按钮**（主按钮或菜单负责，P10）。
  6. **② 方案卡**：有 `model.plan` → `<PlanView plan={model.plan} t={t} />`；`model.otherPlans` 非空时一个 `<details>` 列其它版本（`planLabel` + `FixPlanStatusBadge`）。无方案 → 只显示 `t("workitem.future.issue.plan")`（**不放「Create Fix Plan」**，P10）。
  7. **③ 审批并执行卡**：
     - 批准记录：`plan.approved_by` / `approved_at` / `approved_version` + 哈希（PlanView 已显示哈希一致性，这里只写谁、何时、版本）。
     - 未批准且 `canApprovePlan(plan, a.status)`：L2/L3 警告（现有 `issues.approvalWarning`）+「批准并执行」「拒绝」两个按钮（与 StatusLine 主按钮同一个处理函数）；`approvalBlockedReason` 非空时显示现有 `issues.approvalBlocked.*`。
     - 批准 ReasonDialog：标题 `t("workitem.approveTitle").replace("{label}", planLabel(plan, t))`（「批准并执行 I#1 修复方案 v1」），`description = \`${plan.title} · ${t("plans.hash")} ${shortHash(plan.content_hash)}\``，`confirmText = t("workitem.primary.approveAndRun")`，理由选填；**保留** `!isAuthenticated` 时的 claimed-approver 输入框与 `approved_by` 透传（Review Focus 3）；提交 `approveMut.mutate({ id: plan.id, content_hash: plan.content_hash ?? "", reason: reason || undefined, approved_by: … })`。拒绝 ReasonDialog 理由必填，同今天。
     - 执行证据：`newestFirst(executions.data)` 每次运行一个 `<details>`（最新的展开），内容 `<ExecutionEvidence execution={ex} />`；**不渲染 `ex.error_message` / `verification_reason` 的独立红框**（原因只在状态行，P3）。`executions.error` → `<ErrorBanner>`（保留「拉取失败不能读成没有执行」）。执行中显示 Spinner + 已用时（`started_at` 起算）。
     - 无方案时 `futureHint = t("workitem.future.issue.run")`。
  8. **④ 验收卡**：最新运行的 `<VerificationChip>` + `verification_reason`（这是判定本身的原因字段，属于验收卡的证据；与状态行重复？——**不重复**：状态行在 `awaitingAcceptance` 时显示的就是这句，所以验收卡在 `model.pendingRun` 存在时**不再**显示 `verification_reason`，只显示 accepted_by / accepted_at / note 与「接受结果 / 拒绝」按钮；其它情况才显示判定原因）。接受 / 拒绝复用现有 `AcceptanceActions`（搬进页面文件底部），理由必填。`verification.history` 列表（多次运行）保留。
  9. **右栏**：`FactsRail` 用 `factRows(a, { name: anchorRes.data?.name ?? null, type: anchorRes.data?.resource_type ?? null })`；`extra`：`a.merged_alerts.length > 0` 时一行 `t("workitem.mergedSignals").replace("{n}", …)`，点击展开现有 `MergedAlertsSection`（组件搬进页面文件）；下面一行 `Link to="/app/signals"` → `t("workitem.rawSignals")`。动态卡：`<ActivityList entries={toActivity(timeline.data)} t={t} emptyKey="activity.empty" />`，`timeline.isLoading` → Spinner。
  10. **删除**：页面不再 import `IssueStatusStepper`、`PipelineStepper`、`IssueActionBar`、`IssueStatusBadge`（头部不再有三枚状态）；tab 栏与 `ISSUE_TABS` / `parseIssueTab` 的使用删除（`lib/issueDetail.ts` 里这两个导出保留到 Task 16 统一清理，它们有测试）。
  11. 终态（resolved / dismissed）：阶段卡按 `phase.phases` 的 done/future 显示，全部可展开查看历史；StatusLine `statusLabel` = `t("issues.status." + a.status)`，`a.resolved_at` 填进 reason（`t("workitem.reason.resolvedAt")`）。

  locale（新增，zh/en 成对）：

| 键 | en | zh |
|---|---|---|
| `workitem.phase.diagnose` | Diagnose | 诊断 |
| `workitem.phase.plan` | Plan | 方案 |
| `workitem.phase.run` | Approve & run | 审批并执行 |
| `workitem.phase.accept` | Accept | 验收 |
| `workitem.sub.running` | Investigating | 调查中 |
| `workitem.sub.needsReview` | Root cause needs review | 根因待复核 |
| `workitem.sub.rcaRejected` | Root cause rejected | 根因被判错误 |
| `workitem.sub.reviewOrPlan` | Review root cause or plan a fix | 待复核根因或生成方案 |
| `workitem.sub.toGenerate` | Fix plan to generate | 待生成修复方案 |
| `workitem.sub.needsNewPlan` | The fix failed — needs a new plan | 修复失败，需要新方案 |
| `workitem.sub.awaitingApproval` | Awaiting approval | 待审批 |
| `workitem.sub.notQueued` | Approved, run not queued | 已批准，未入队 |
| `workitem.sub.executing` | Running | 执行中 |
| `workitem.sub.awaitingAcceptance` | Awaiting acceptance | 待验收 |
| `workitem.sub.passed` | Verified | 已通过验证 |
| `workitem.sub.unverified` | Run finished without a verdict | 已执行，无判定 |
| `workitem.sub.resolved` | Resolved | 已解决 |
| `workitem.sub.dismissed` | Dismissed | 已忽略 |
| `workitem.wait.rca_agent` | Waiting for the RCA agent | 等 RCA 智能体 |
| `workitem.wait.you` | Waiting for you | 等你 |
| `workitem.wait.sre_agent` | Waiting for the SRE agent | 等 SRE 智能体 |
| `workitem.wait.approver` | Waiting for an approver | 等审批人 |
| `workitem.wait.executor` | Waiting for the executor | 等执行器 |
| `workitem.wait.requester` | Waiting for the requester | 等申请人 |
| `workitem.wait.acceptor` | Waiting for acceptance | 等验收人 |
| `workitem.primary.reviewRca` | Review root cause | 复核根因 |
| `workitem.primary.rerunRca` | Rerun RCA | 重新运行 RCA |
| `workitem.primary.generatePlan` | Generate fix plan | 生成修复方案 |
| `workitem.primary.approveAndRun` | Approve & run | 批准并执行 |
| `workitem.primary.retryExecution` | Retry execution | 重试执行 |
| `workitem.primary.acceptResult` | Accept result | 接受结果 |
| `workitem.primary.markResolved` | Mark resolved | 标记已解决 |
| `workitem.menu.runRca` | Run RCA again | 重新运行 RCA |
| `workitem.menu.skipReviewGeneratePlan` | Skip review, generate a fix plan | 跳过复核，直接生成修复方案 |
| `workitem.menu.markResolved` | Mark resolved manually | 手动标记已解决 |
| `workitem.menu.dismiss` | Dismiss this issue | 忽略此问题 |
| `workitem.menu.reopen` | Reopen | 重新打开 |
| `workitem.menu.cancelRun` | Cancel the run | 取消执行 |
| `workitem.reason.rcaBelowGate` | RCA confidence {conf} is below the auto-fix threshold {threshold}: auto-fix is paused. | RCA 置信度 {conf}，低于自动修复阈值 {threshold}，自动修复已暂停。 |
| `workitem.reason.rcaRefuted` | The reviewer refuted the root cause: auto-fix is paused. | 评审员否定了根因，自动修复已暂停。 |
| `workitem.reason.noRca` | No RCA result is stored for this issue. | 这个问题没有存下 RCA 结果。 |
| `workitem.reason.rcaRejected` | A person judged the root cause wrong; rerun the RCA. | 根因已被判为错误，请重新运行 RCA。 |
| `workitem.reason.runFailed` | The last run failed. | 上一次执行失败。 |
| `workitem.reason.notQueued` | Approved, but the run could not be queued — retry it. | 已批准，但未能入队执行 —— 请重试。 |
| `workitem.reason.resolvedAt` | Resolved {at} | 解决于 {at} |
| `workitem.summary.diagnose` | RCA {conf} · {verdict} | RCA {conf} · {verdict} |
| `workitem.future.issue.plan` | The SRE agent generates it once the root cause is confirmed (or skip review from ⋯). | 复核为「正确」后由 SRE 智能体生成；也可在「⋯」里跳过复核直接生成。 |
| `workitem.future.issue.run` | L0 / L1 run automatically; L2 and above wait for a person to approve & run. | L0 / L1 自动批准并执行；L2 及以上等人「批准并执行」。 |
| `workitem.future.issue.accept` | Verified automatically after the run; a person accepts when it cannot decide. | 执行后自动验证；无法判定时等人验收。 |
| `workitem.approveTitle` | Approve & run {label} | 批准并执行 {label} |
| `workitem.confirm.retry` | Queue the run again? The executor runs the approved plan. | 重新入队执行？执行器将运行已批准的方案。 |
| `workitem.confirm.resolve` | Mark this issue resolved? | 确认标记为已解决？ |
| `workitem.confirm.dismiss` | Dismiss this issue? It is hidden from active views. | 忽略此问题？它将不再出现在进行中的视图里。 |
| `workitem.confirm.reopen` | Reopen this issue? | 重新打开这个问题？ |
| `workitem.mergedSignals` | {n} merged signals | 合并信号 {n} 条 |
| `workitem.rawSignals` | Raw signals → | 原始信号 → |
| `workitem.activity` | Activity | 动态 |
| `workitem.facts` | Key facts | 关键事实 |

- [ ] **Step 4: 跑测试确认通过**；`issueDetail.test.ts` 原有用例全过。
- [ ] **Step 5: 前端门禁**。
- [ ] **Step 6: Commit**：`feat(web): IssueDetail on the work-item template — one status line, phase cards, facts and activity rail`。

---

# A3 — 变更详情

### Task 12: 变更阶段模型

**Files:**
- Create: `$FE/src/lib/changePhases.ts`、`$FE/src/lib/changeDetailModel.ts`
- Test: `$FE/src/__tests__/changePhases.test.ts`

**Interfaces:**
- Consumes：`changeHeadline`（Task 6 版）、`activeChangePlan`、`newestFirst`、`PhaseView` / `PhaseState` / `WaitingFor`（Task 8）。
- Produces（Task 13、14 用）：

```ts
export type ChangePhaseId = "request" | "review" | "plan" | "run" | "accept";
export type ChangePrimary = "startReview" | "answerReviewer" | "approveAndRun" | "retryExecution" | "markCompleted" | "copyAsNew" | null;
export type ChangeSub = "draft" | "reviewing" | "needsClarification" | "awaitingApproval" | "notQueued" | "executing"
  | "awaitingAcceptance" | "completed" | "failed" | "rolledBack" | "rejected" | "cancelled";
export interface ChangePhaseResult { current: ChangePhaseId; sub: ChangeSub; waitingFor: WaitingFor; primary: ChangePrimary; phases: PhaseView<ChangePhaseId>[]; terminal: boolean }
export const CHANGE_PHASES: readonly ChangePhaseId[];
export function changePhases(cr: Pick<ChangeRequest, "status" | "review_verdict" | "approved_at">): ChangePhaseResult
// changeDetailModel.ts
export interface ChangeDetailModel { phase: ChangePhaseResult; statusKey: string; tone: "info" | "warn" | "bad" | "ok"; reason: string | null; waitingKey: string | null; primaryKey: string | null; plan: FixPlan | null; latestRun: FixExecution | null; runs: FixExecution[]; acceptNote: { key: string; params?: Record<string, string> } | null; menu: ChangeMenuItem[] }
export type ChangeMenuItem = "reject" | "cancel" | "copyAsNew" | "restartReview";
export function changeDetailModel(cr: ChangeRequestDetail): ChangeDetailModel
```

- [ ] **Step 1: 写失败的测试**（spec §4 变更表每行 + C#1 原因只出现一次）

```ts
import { describe, it, expect } from "vitest";
import type { ChangeRequestDetail, FixExecution } from "@/api/types";
import { changePhases } from "@/lib/changePhases";
import { changeDetailModel } from "@/lib/changeDetailModel";

const C = (status: string, extra: Record<string, unknown> = {}) =>
  ({ status, review_verdict: null, approved_at: null, ...extra }) as Parameters<typeof changePhases>[0];
const pick = (r: ReturnType<typeof changePhases>) => [r.current, r.sub, r.waitingFor, r.primary];
const ids = (r: ReturnType<typeof changePhases>) => r.phases.map((p) => `${p.id}:${p.state}`);

describe("changePhases — spec §4 change table", () => {
  it("open states", () => {
    expect(pick(changePhases(C("draft")))).toEqual(["request", "draft", "requester", "startReview"]);
    expect(pick(changePhases(C("under_review")))).toEqual(["review", "reviewing", "sre_agent", null]);
    expect(pick(changePhases(C("needs_clarification")))).toEqual(["review", "needsClarification", "requester", "answerReviewer"]);
    expect(pick(changePhases(C("planned")))).toEqual(["run", "awaitingApproval", "approver", "approveAndRun"]);
    expect(pick(changePhases(C("approved")))).toEqual(["run", "notQueued", "you", "retryExecution"]);
    expect(pick(changePhases(C("executing")))).toEqual(["run", "executing", "executor", null]);
    expect(pick(changePhases(C("needs_review")))).toEqual(["accept", "awaitingAcceptance", "acceptor", "markCompleted"]);
    expect(ids(changePhases(C("planned")))).toEqual(["request:done", "review:done", "plan:done", "run:current", "accept:future"]);
  });
  it("completed: all five done, no primary", () => {
    const r = changePhases(C("completed"));
    expect(pick(r)).toEqual(["accept", "completed", null, null]);
    expect(ids(r)).toEqual(["request:done", "review:done", "plan:done", "run:done", "accept:done"]);
  });
  it("a bad ending ends the list at the phase it ended on (no Completed after Failed); next step: copy as new", () => {
    expect(ids(changePhases(C("failed")))).toEqual(["request:done", "review:done", "plan:done", "run:failed"]);
    expect(pick(changePhases(C("failed")))).toEqual(["run", "failed", null, "copyAsNew"]);
    expect(ids(changePhases(C("rolled_back")))).toEqual(["request:done", "review:done", "plan:done", "run:failed"]);
    expect(ids(changePhases(C("rejected")))).toEqual(["request:done", "review:failed"]);
    expect(ids(changePhases(C("rejected", { review_verdict: "approved_for_planning" })))).toEqual(
      ["request:done", "review:done", "plan:done", "run:failed"]);
    expect(ids(changePhases(C("cancelled")))).toEqual(["request:failed"]);
    expect(ids(changePhases(C("cancelled", { review_verdict: "needs_clarification" })))).toEqual(["request:done", "review:failed"]);
    expect(ids(changePhases(C("cancelled", { approved_at: "2026-10-03T09:55:56" })))).toEqual(
      ["request:done", "review:done", "plan:done", "run:failed"]);
    for (const s of ["failed", "rolled_back", "rejected", "cancelled"]) expect(changePhases(C(s)).terminal, s).toBe(true);
  });
});

describe("changeDetailModel — C#1 (failed at pre-check #1): the failure sentence appears exactly once", () => {
  const sentence = "Pre-check #1 FAILED: Deployment frontend reports 0 ready replicas (expected 3/3).";
  const run = { id: 1, fix_plan_id: 1, status: "aborted", verification_status: "failed", verification_reason: sentence,
                error_message: sentence, acceptance_note: null, created_at: "2026-10-03T09:56:11" } as FixExecution;
  const cr = { id: 1, status: "failed", review_verdict: "approved_for_planning", approved_at: "2026-10-03T09:55:56",
               needs_review_reason: null, review_reasons: [], rejection_reason: null, plans: [], executions: [run],
               policy_decision: null } as unknown as ChangeRequestDetail;
  it("the status line carries it; the accept card points at the run instead of repeating it", () => {
    const m = changeDetailModel(cr);
    expect(m.reason).toBe(sentence);
    expect(m.acceptNote).toEqual({ key: "workitem.accept.systemFailed", params: { n: "1" } });
    expect(m.primaryKey).toBe("workitem.primary.copyAsNew");
    const { runs, latestRun, ...shown } = m; // the runs are evidence rows, rendered without their sentence
    expect(JSON.stringify(shown).split(sentence).length - 1).toBe(1);
    expect(runs).toHaveLength(1);
    expect(latestRun?.id).toBe(1);
  });
});
```

- [ ] **Step 2: 跑测试确认失败**。
- [ ] **Step 3: 实现** `lib/changePhases.ts`：

```ts
import type { ChangeRequest } from "@/api/types";
import type { PhaseView, WaitingFor } from "@/lib/issuePhases";

export type ChangePhaseId = "request" | "review" | "plan" | "run" | "accept";
export type ChangePrimary = "startReview" | "answerReviewer" | "approveAndRun" | "retryExecution" | "markCompleted" | "copyAsNew" | null;
export type ChangeSub = "draft" | "reviewing" | "needsClarification" | "awaitingApproval" | "notQueued" | "executing"
  | "awaitingAcceptance" | "completed" | "failed" | "rolledBack" | "rejected" | "cancelled";
export interface ChangePhaseResult {
  current: ChangePhaseId;
  sub: ChangeSub;
  waitingFor: WaitingFor;
  primary: ChangePrimary;
  phases: PhaseView<ChangePhaseId>[];
  terminal: boolean;
}

export const CHANGE_PHASES: readonly ChangePhaseId[] = ["request", "review", "plan", "run", "accept"];

function open(current: ChangePhaseId, sub: ChangeSub, waitingFor: WaitingFor, primary: ChangePrimary): ChangePhaseResult {
  const at = CHANGE_PHASES.indexOf(current);
  return { current, sub, waitingFor, primary, terminal: false,
           phases: CHANGE_PHASES.map((id, i) => ({ id, state: i < at ? "done" : i === at ? "current" : "future" })) };
}

/** Spec §4 change table. A change that ended badly ends its phase list at the phase it ended on. */
function ended(at: ChangePhaseId, sub: ChangeSub): ChangePhaseResult {
  const idx = CHANGE_PHASES.indexOf(at);
  return { current: at, sub, waitingFor: null, primary: "copyAsNew", terminal: true,
           phases: CHANGE_PHASES.slice(0, idx + 1).map((id, i) => ({ id, state: i < idx ? "done" : "failed" })) };
}

export function changePhases(cr: Pick<ChangeRequest, "status" | "review_verdict" | "approved_at">): ChangePhaseResult {
  const reviewPassed = cr.review_verdict === "approved_for_planning";
  switch (cr.status) {
    case "draft": return open("request", "draft", "requester", "startReview");
    case "under_review": return open("review", "reviewing", "sre_agent", null);
    case "needs_clarification": return open("review", "needsClarification", "requester", "answerReviewer");
    case "planned": return open("run", "awaitingApproval", "approver", "approveAndRun");
    case "approved": return open("run", "notQueued", "you", "retryExecution");
    case "executing": return open("run", "executing", "executor", null);
    case "needs_review": return open("accept", "awaitingAcceptance", "acceptor", "markCompleted");
    case "completed":
      return { current: "accept", sub: "completed", waitingFor: null, primary: null, terminal: true,
               phases: CHANGE_PHASES.map((id) => ({ id, state: "done" as const })) };
    case "failed": return ended("run", "failed");
    case "rolled_back": return ended("run", "rolledBack");
    case "rejected": return ended(reviewPassed ? "run" : "review", "rejected");
    case "cancelled":
      return ended(cr.approved_at || reviewPassed ? "run" : cr.review_verdict ? "review" : "request", "cancelled");
  }
}
```

  `lib/changeDetailModel.ts`：

```ts
import type { ChangeRequestDetail, FixExecution, FixPlan } from "@/api/types";
import { activeChangePlan, changeHeadline } from "@/lib/changeDetail";
import { newestFirst } from "@/lib/issueDetail";
import { changePhases, type ChangePhaseResult } from "@/lib/changePhases";

export type ChangeMenuItem = "reject" | "cancel" | "copyAsNew" | "restartReview";
export interface ChangeDetailModel {
  phase: ChangePhaseResult;
  statusKey: string;
  tone: "info" | "warn" | "bad" | "ok";
  reason: string | null;
  waitingKey: string | null;
  primaryKey: string | null;
  plan: FixPlan | null;
  latestRun: FixExecution | null;
  runs: FixExecution[];
  acceptNote: { key: string; params?: Record<string, string> } | null;
  menu: ChangeMenuItem[];
}

const CANCELLABLE = ["draft", "needs_clarification", "planned", "approved"];
const COPYABLE = ["needs_review", "completed", "failed", "rolled_back", "rejected", "cancelled"];

/** ChangeDetail's view model. The reason (changeHeadline's — the same sentence ContextPanel shows) lives only in
 *  the status line; a run the system judged failed is pointed at from the accept card, not repeated (P3). */
export function changeDetailModel(cr: ChangeRequestDetail): ChangeDetailModel {
  const runs = newestFirst(cr.executions);
  const latestRun = runs[0] ?? null;
  const phase = changePhases(cr);
  const reason = changeHeadline(cr, latestRun).reason;
  const failedRun = latestRun && latestRun.verification_status === "failed";
  const menu: ChangeMenuItem[] = [
    ...(cr.status === "under_review" ? ["restartReview" as const] : []),
    ...(cr.status === "planned" ? ["reject" as const] : []),
    ...(CANCELLABLE.includes(cr.status) ? ["cancel" as const] : []),
    ...(COPYABLE.includes(cr.status) && phase.primary !== "copyAsNew" ? ["copyAsNew" as const] : []),
  ];
  return {
    phase,
    statusKey: `changes.status.${cr.status}`,
    tone: phase.terminal && phase.sub !== "completed" ? "bad"
      : phase.sub === "completed" ? "ok"
      : ["needsClarification", "awaitingApproval", "notQueued", "awaitingAcceptance"].includes(phase.sub) ? "warn" : "info",
    reason,
    waitingKey: phase.waitingFor ? `workitem.wait.${phase.waitingFor}` : null,
    primaryKey: phase.primary ? `workitem.primary.${phase.primary}` : null,
    plan: activeChangePlan(cr.plans),
    latestRun,
    runs,
    acceptNote: failedRun ? { key: "workitem.accept.systemFailed", params: { n: String(latestRun!.id) } } : null,
    menu,
  };
}
```

- [ ] **Step 4: 跑测试确认通过**。
- [ ] **Step 5: 前端门禁**。
- [ ] **Step 6: Commit**：`feat(web): change phase model and view model (pure, tested)`。

### Task 13: 变更详情套用模板（C-a…C-g）

**Files:**
- Rewrite: `$FE/src/pages/ChangeDetail.tsx`
- Modify: locale

**Interfaces:**
- Consumes：Task 7、9、12 的导出；现有 hooks（`useChange`、`useChangeAction`、`useChangeTimeline`、`useSettings`、`useAccounts`）；现有 `NewChangeDialog`、`ReasonDialog`、`ExecutionEvidence`、`VerificationChip`、`LocalGraph`、`ChangeStatusBadge`。

- [ ] **Step 1: 写页面**（没有新纯函数；Task 12 的模型测试就是它的逻辑测试）。结构同问题页：左栏 `StatusLine` + 5 张 `PhaseCard`（按 `model.phase.phases`，终态时只画到结局那张），右栏 `FactsRail` + 动态。逐条要求：
  1. 外层 `ChangeDetail` 保留 `key={id}` 包装（换路由时重置状态）；`changesOn` / 404 / loading / error 分支原样保留。
  2. **URL**：`parseHash(location.hash, CHANGE_HASHES)` → 展开并滚到该阶段 / 动态卡；点卡头用 `replace` 写 hash。
  3. **StatusLine**：`refLabel=\`C#${cr.id}\``；`badges` = `RiskLevelBadge` + `t("plans.changeType." + (cr.effective_change_type ?? cr.requested_change_type))`；`statusLabel=t(model.statusKey)`；`reason=model.reason`；`waiting`；`backTo="/app/changes"`。主按钮映射：`startReview` → `runDirect({action:"review"})`；`answerReviewer` → 展开 review 卡并聚焦 `#change-clarify`；`approveAndRun` → 现有 `openApprove`（**哈希在打开时取定**，Ruling E-T5b，`plan = model.plan` 即 `activeChangePlan`，Ruling E-T5a）；`retryExecution` → 现有 `onExecute`；`markCompleted` → 现有 `openAccept("completed")`；`copyAsNew` → `setCopy(true)`。菜单：`restartReview`（`t("changes.restartReview")`，执行 `runDirect({action:"review"})`，旁注 `changes.restartReviewHint` 作为菜单项 title）、`reject`（现有拒绝 ReasonDialog，理由必填）、`cancel`（现有取消 ReasonDialog）、`copyAsNew`。错误（`act.error` / `msg`）进 StatusLine `error`。
  4. **① 申请**：description markdown、申请人、创建时间、外部单号（`externalRefLink`，链接只给 http(s)）、目标（`target_resources` 链接 + 未解析的 `target_hints` 琥珀色，`isHintResolved`）、理由、申请步骤（`proposed_steps`）。`summary` = `t("workitem.summary.request")` 填 `{by}{at}{n}`（目标个数）。
  5. **② 审核**：审核人与时间、结论、动作、策略（`policy_rule → policy_action`）、`review_reasons` 与 `policySummary(...).reasons` **只显示前 3 条**，其余在 `<details>` 里（`t("workitem.moreReasons").replace("{n}", …)`）；升级提示（`changes.riskEscalated`）；影子影响数 `changes.shadowImpact` 与 `<details>` 里的 `<LocalGraph subject={{ changeRequestId: cr.id }} note={impactNote} height={300} />`（`impactNote` 规则同今天）。`needs_clarification` 时，澄清 textarea（`id="change-clarify"`）与「回答审核方」按钮在这张卡里（`sendClarify` 原样）。`summary` = `t("workitem.summary.review")` 填结论 / 风险 / 动作。
  6. **③ 方案**：`model.plan` 存在 → `<PlanView plan={model.plan} stepsDiff={cr.steps_diff} t={t} />`；否则 `futureHint = t("workitem.future.change.plan")`。`summary` = `planLabel` + `planCounts`。
  7. **④ 审批并执行**：实际审批（`approved_by` · `approved_at` · `approved_version` + 短哈希 · `approval_reason`；或拒绝 / 取消记录）；`planned` 时「批准并执行」+「拒绝」按钮（与 StatusLine 同一处理函数）和说明 `t("changes.approveRunsNote")`；`approved` 时「重试执行」；执行证据：`model.runs` 每次运行一个 `<details>`（最新展开），内容只有 `<ExecutionEvidence execution={ex} />`——**不渲染** `ExecutionsTable` 的 error 行或任何复述失败原因的红框（P3、C-b）；执行中显示「执行中」+ 已用时。
  8. **⑤ 验收**：`model.acceptNote` 存在 → 只写 `t(acceptNote.key).replace("{n}", …)`；`needs_review` → `t("changes.needsReviewNote")` +「标记完成」「标记失败」（理由必填，现有 `openAccept`）；`completed` → `VerificationChip` + accepted_by / at / note。
  9. **右栏**：`FactsRail` 行：目标（第一个目标的 `resource_id`，多于一个时 `+N`）、账户（`acct.name (provider)` 或 `plans.form.accountAny`）、风险、申请人、外部单（链接）、创建于、Trace。动态：`<ActivityList entries={toActivity(toPipelineEvents(tl.data ?? []))} t={t} emptyKey="changes.noEvents" />`。
  10. `ReasonDialog` 与 `NewChangeDialog`（复制为新变更，`initial` 原样）挂在页面底部，逻辑不变。
  11. 删除：页面不再 import `ChangeStepper`、`ExecutionsTable`、`PipelineTimeline`。

  locale 新增：

| 键 | en | zh |
|---|---|---|
| `workitem.phase.request` | Request | 申请 |
| `workitem.phase.review` | Review | 审核 |
| `workitem.primary.startReview` | Start review | 发起审核 |
| `workitem.primary.answerReviewer` | Answer the reviewer | 回答审核方 |
| `workitem.primary.markCompleted` | Mark completed | 标记完成 |
| `workitem.primary.copyAsNew` | Copy as new | 复制为新变更 |
| `workitem.summary.request` | {by} · {at} · {n} targets | {by} 于 {at} 提交 · 目标 {n} 个 |
| `workitem.summary.review` | {verdict} · {risk} · {action} | {verdict} · {risk} · {action} |
| `workitem.moreReasons` | {n} more reasons | 其余 {n} 条理由 |
| `workitem.future.change.review` | The SRE agent reviews it once the review starts. | 发起审核后由 SRE 智能体审核。 |
| `workitem.future.change.plan` | The SRE agent writes the implementation plan during review. | SRE 智能体在审核中生成实施方案。 |
| `workitem.future.change.run` | An approver approves & runs the plan. | 审批人「批准并执行」。 |
| `workitem.future.change.accept` | Verified automatically after the run; a person accepts when it cannot decide. | 执行后自动验证；无法判定时等人验收。 |
| `workitem.accept.systemFailed` | The system judged it failed (see run #{n}); no acceptance needed. | 系统已判定失败（见执行 #{n}），不需要人工验收。 |

- [ ] **Step 2: 前端门禁**（tsc / vitest / build）。
- [ ] **Step 3: Commit**：`feat(web): ChangeDetail on the work-item template — outcome ends the phase list, the failure is said once`。

---

# A4 — 列表与信息架构

### Task 14: WorkItemTable 与两个列表（L-a、L-c、L-d、P15、P2 列表部分）

**Files:**
- Create: `$FE/src/components/ui/WorkItemTable.tsx`、`$FE/src/lib/workItems.ts`
- Modify: `$FE/src/pages/IssuesAndPlans.tsx`（IssuesView）、`$FE/src/components/plans/ChangePlansTab.tsx`、locale
- Test: `$FE/src/__tests__/workItems.test.ts`

**Interfaces:**
- Consumes：`issuePhases`（list mode，R2）、`changePhases`、`ISSUE_PHASES` / `CHANGE_PHASES`。
- Produces：

```ts
// workItems.ts
export interface WorkItemRow { key: string; ref: string; href: string; title: string; subtitle: string | null;
  statusKey: string; dots: PhaseView[]; waitKey: string | null; level: string | null; account: string | null; updated: string | null }
export function issueRow(a: Anomaly): WorkItemRow
export function changeRow(cr: ChangeRequest, accountName?: string | null): WorkItemRow
// WorkItemTable.tsx
export function WorkItemTable(p: { rows: WorkItemRow[]; levelHeader: string; renderLevel: (row: WorkItemRow) => React.ReactNode;
  rowActions?: (row: WorkItemRow) => React.ReactNode; emptyMessage: string; t: (k: string) => string }): JSX.Element
```

- [ ] **Step 1: 写失败的测试**

```ts
import { describe, it, expect } from "vitest";
import type { Anomaly, ChangeRequest } from "@/api/types";
import { changeRow, issueRow } from "@/lib/workItems";

const anomaly = (x: Partial<Anomaly>) => ({ id: 1, title: "EKS-agenticops-chaos-lab-RunningPods-Low", status: "root_cause_identified",
  severity: "high", resource_id: "unknown", resource_type: "unknown", account_name: "chaos-lab", detected_at: "2026-10-03T03:39:04",
  ...x }) as Anomaly;

describe("issueRow (list mode, R2)", () => {
  it("I#1: locale status, the same wait key the page would say in list mode, no raw enum", () => {
    const r = issueRow(anomaly({}));
    expect(r).toMatchObject({ ref: "I#1", href: "/app/issues/1", statusKey: "issues.status.root_cause_identified",
                              waitKey: "workitem.wait.you", level: "high", account: "chaos-lab" });
    expect(r.subtitle).toBeNull(); // "unknown" is not a subtitle
    expect(r.dots.map((d) => d.state)).toEqual(["current", "future", "future", "future"]);
  });
  it("a resolved issue has no wait; a real resource id is the subtitle", () => {
    const r = issueRow(anomaly({ status: "resolved", resource_type: "EC2", resource_id: "i-0abc" }));
    expect(r.waitKey).toBeNull();
    expect(r.subtitle).toBe("EC2 · i-0abc");
  });
});

describe("changeRow", () => {
  it("C#1 failed: the dots end at the failed phase; next step copy-as-new is the wait text", () => {
    const r = changeRow({ id: 1, title: "E2E intake", status: "failed", review_verdict: "approved_for_planning",
      approved_at: "x", risk_level: "L1", requested_by: "webhook:e2e-itsm", external_ref: { system: "e2e-itsm", ticket_id: "CHG-1001" },
      updated_at: "2026-10-03T09:56:39", created_at: null } as unknown as ChangeRequest, "chaos-lab");
    expect(r).toMatchObject({ ref: "C#1", href: "/app/changes/1", statusKey: "changes.status.failed",
                              waitKey: "workitem.primary.copyAsNew", level: "L1", account: "chaos-lab" });
    expect(r.subtitle).toBe("webhook:e2e-itsm · e2e-itsm CHG-1001");
    expect(r.dots.map((d) => d.state)).toEqual(["done", "done", "done", "failed"]);
  });
});
```

- [ ] **Step 2: 跑测试确认失败**。
- [ ] **Step 3: 实现** `lib/workItems.ts`：

```ts
import type { Anomaly, ChangeRequest } from "@/api/types";
import { isBlank } from "@/lib/issueDetail";
import { issuePhases, type PhaseView } from "@/lib/issuePhases";
import { changePhases } from "@/lib/changePhases";

export interface WorkItemRow {
  key: string; ref: string; href: string; title: string; subtitle: string | null;
  statusKey: string; dots: PhaseView[]; waitKey: string | null; level: string | null; account: string | null; updated: string | null;
}

/** An issue list row. The list has no RCA or runs, so the wait comes from list-mode issuePhases (R2). */
export function issueRow(a: Anomaly): WorkItemRow {
  const p = issuePhases({ status: a.status });
  const sub = [a.resource_type, a.resource_id].filter((x) => !isBlank(x)).join(" · ");
  return { key: `I${a.id}`, ref: `I#${a.id}`, href: `/app/issues/${a.id}`, title: a.title, subtitle: sub || null,
           statusKey: `issues.status.${a.status}`, dots: p.phases, waitKey: p.waitingFor ? `workitem.wait.${p.waitingFor}` : null,
           level: a.severity, account: a.account_name, updated: a.resolved_at ?? a.detected_at };
}

/** A change list row; a closed change's "wait" column says its next step (copy as new) instead. */
export function changeRow(cr: ChangeRequest, accountName?: string | null): WorkItemRow {
  const p = changePhases(cr);
  const ext = cr.external_ref ? `${cr.external_ref.system} ${cr.external_ref.ticket_id}` : null;
  return { key: `C${cr.id}`, ref: `C#${cr.id}`, href: `/app/changes/${cr.id}`, title: cr.title,
           subtitle: [cr.requested_by, ext].filter(Boolean).join(" · ") || null,
           statusKey: `changes.status.${cr.status}`, dots: p.phases,
           waitKey: p.waitingFor ? `workitem.wait.${p.waitingFor}` : p.primary === "copyAsNew" ? "workitem.primary.copyAsNew" : null,
           level: cr.risk_level, account: accountName ?? null, updated: cr.updated_at ?? cr.created_at };
}
```

  `WorkItemTable.tsx`：一张表，列：`#`（`ref`，等宽，主色）· 标题（`title` + 灰色 `subtitle`）· 状态（`dots` 画 4/5 个小圆点：done 绿、current 蓝、failed 红、future 灰；后接 `t(statusKey)`）· 等谁 / 下一步（`waitKey && t(waitKey)`，`text-xs`）· `levelHeader` 列（`renderLevel(row)`）· 账户 · 更新（`formatShortDate`）· 可选 `rowActions` 列（悬停才显示，`opacity-0 group-hover:opacity-100`）。整行可点（`useNavigate()(row.href)`，Enter 也触发；`rowActions` 内的按钮 `e.stopPropagation()`）。空列表显示 `emptyMessage`。
  `IssuesAndPlans.tsx` 的 `IssuesView`：
  - **筛选压成一行**（P15）：状态（全部 / 进行中 / 已解决 / 已忽略，沿用 `getPhase` 与计数，计数写进 option 文字）、严重度（全部 / critical / high / medium / low，计数同上）、范围（运维事件 / 安全发现 / 全部，仍写 `?scope=`）三个 `<select>`，加排序 `<select>` 与搜索框，右侧 `Link to="/app/signals"`（`t("workitem.rawSignals")`）。删除原来的状态 chip 行、severity chip 行、scope 分段按钮。
  - 表格换成 `<WorkItemTable rows={filtered.map(issueRow)} levelHeader={t("facts.severity")} renderLevel={(r) => <SeverityBadge severity={r.level as Anomaly["severity"]} />} rowActions={…} … />`。
  - **rowActions（R3）**：把 `IssueRow.tsx` 里的快捷操作（解决 / 确认 / 忽略 / 重新打开，含它们的 `useConfirm` 确认与 `useUpdateIssueStatus` / `useIssueFeedback` 调用、toast）抽成同目录的 `IssueQuickActions.tsx`（props：`issue: Anomaly`），文案改走 locale（`workitem.menu.markResolved`、`verdict.choice.correct` 的短版 `workitem.quick.confirm`、`workitem.menu.dismiss`、`workitem.menu.reopen`）；安全问题行的「打开安全页 →」链接（`isSecurityIssue`）放进 `subtitle` 后面（WorkItemTable 支持 `subtitle` 为 ReactNode 的话会更简单——为保持纯函数，`issueRow` 只给字符串；安全链接由 `rowActions` 渲染）。`IssueRow.tsx` 不再被引用，Task 16 删除。
  `ChangePlansTab.tsx`：表格换成 `<WorkItemTable rows={rows.map((c) => changeRow(c, accountName(c.account_id)))} levelHeader={t("plans.risk")} renderLevel={(r) => r.level ? <RiskLevelBadge level={r.level as RiskLevel} /> : "—"} … />`（`accountName` 由 `useAccounts` 映射）；筛选行（状态 / 账户 / 申请人 / 时间窗）与 `LIST_LIMIT` 提示原样。
  locale：`workitem.col.ref` # / #，`workitem.col.title` Title / 标题，`workitem.col.status` Status / 状态，`workitem.col.wait` Waiting for / next step · 等谁 / 下一步，`workitem.col.account` Account / 账户，`workitem.col.updated` Updated / 更新，`workitem.quick.confirm` Confirm / 确认，`workitem.filter.status` Status / 状态，`workitem.filter.severity` Severity / 严重度，`workitem.filter.scope` Scope / 范围。
- [ ] **Step 4: 跑测试确认通过**。
- [ ] **Step 5: 前端门禁**。
- [ ] **Step 6: Commit**：`feat(web): one WorkItemTable for issues and changes; issue filters on one row`。

### Task 15: 资源独立入口、`/app/signals`、旧链接重定向（L-b）

**Files:**
- Create: `$FE/src/pages/Resources.tsx`、`$FE/src/pages/Signals.tsx`
- Modify: `$FE/src/pages/IssuesAndPlans.tsx`（去掉视图切换，导出 `ResourcesView`）、`$FE/src/App.tsx`、`$FE/src/components/layout/NavItems.tsx`、locale
- Test: `$FE/src/__tests__/navOrder.test.ts`（更新）、`workitemRoutes.test.ts`（Task 8 已覆盖重定向函数）

**Interfaces:**
- Consumes：`legacyIssuesViewRedirect`（Task 8）。

- [ ] **Step 1: 改测试**：读 `navOrder.test.ts` 现有断言，把期望的侧栏顺序改为在 `changes` 之后插入 `resources`：`dashboard, chat, issues, changes, resources, audit, schedules, reports, agent-metrics, skills, galaxy, security`。跑 → FAIL。
- [ ] **Step 2: 实现**
  - `NavItems.tsx`：在 `changes` 后加 `{ id: "resources", to: "/app/resources", icon: "server", labelKey: "nav.resources", end: false }`；`ICON_PATHS` 加 `server: "M5 12h14M5 12a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v4a2 2 0 01-2 2M5 12a2 2 0 00-2 2v4a2 2 0 002 2h14a2 2 0 002-2v-4a2 2 0 00-2-2m-2-4h.01M17 16h.01"`（Heroicons outline `server`）。`NavPreviewCard` 若按 id 分支，给 `resources` 一个最小预览或沿用默认分支。
  - `IssuesAndPlans.tsx`：删除 `View` 类型、视图切换按钮组与 `titles`；页面只渲染标题 `t("issues.title")` + `IssuesView`；把 `ResourcesView` 改为 `export function ResourcesView`（内部不变，`initialType` 仍从 `?type=` 读）。组件顶部：`const redirect = legacyIssuesViewRedirect(location.search); if (redirect) return <Navigate to={redirect} replace />;`（`useLocation`）。
  - `pages/Resources.tsx`：`export default function Resources() { const { t } = useLocale(); const navigate = useNavigate(); const [sp] = useSearchParams(); return (<div className="space-y-4"><h1 className="text-xl font-semibold text-foreground">{t("resources.title")}</h1><ResourcesView navigate={navigate} t={t} initialType={sp.get("type") || ""} /></div>); }`。
  - `pages/Signals.tsx`：标题 `t("signals.title")` + `<SignalsPanel />`。
  - `App.tsx`：`resources` 与 `signals` 两个懒加载路由（`Suspense` 写法同其它页），放在 `resources/:id` 之前；`issues` 路由不变（重定向在页面里做）。
  - locale：`nav.resources` Resources / 资源。
- [ ] **Step 3: 跑测试确认通过**（navOrder、workitemRoutes、locales）。
- [ ] **Step 4: 前端门禁**。
- [ ] **Step 5: Commit**：`feat(web): Resources gets its own entry, signals live at /app/signals, old ?view= links redirect`。

### Task 16: 收尾——删除死代码、文档、最终门禁

**Files:**
- Delete（确认无引用后）：`$FE/src/components/ui/IssueActionBar.tsx`、`$FE/src/components/ui/IssueStatusStepper.tsx`、`$FE/src/components/ui/IssueRow.tsx`；`PipelineStepper.tsx` 仍被 `ContextPanel` 用则保留；`ChangeStepper.tsx`（ContextPanel 用）保留；`ExecutionsTable.tsx` / `PipelineTimeline.tsx` 若已无引用则删除。`lib/issueDetail.ts` 的 `ISSUE_TABS` / `parseIssueTab` 若已无引用则删除，连同它们的测试用例。
- Modify：`CLAUDE.md`（前端一节 pages / components / lib 清单；IssueDetail / ChangeDetail 描述改为阶段卡模板；侧栏「资源」与 `/app/signals`；`GET /api/settings` 的只读字段）、`docs/WORKFLOW.md`（Web 操作段落：问题与变更详情的状态行、主按钮、「你的判断」、hash 锚点）、`docs/MVP-2.6.1-RELEASE.md`（新增一节「2.6.1 之后：统一工单模板（方案 A）」——六个可达面逐行，Web API 与 Web UI 分两行；本计划的 R1–R4；测试数字据实填）、README 双语（若 README 描述了问题页 / 侧栏，同一提交内同步 `README.md` 与 `README_CN.md`）。

- [ ] **Step 1: 引用检查**：对每个候选文件 `grep -rlw <Name> $FE/src` 只剩它自己才删；删 locale 中只被删除组件用过的键（`issues.tab.*`、`issues.statusBusiness/Execution/Verification` 等）——每删一个键先 `grep -rn "\"<key>\"\|'<key>'\|\`<key>" $FE/src` 确认无引用。
- [ ] **Step 2: 前端门禁**。
- [ ] **Step 3: 后端全量**（Task 1 改过 app.py；按 Global Constraints 跑全量、还原 agent-memory/skills）：期望 6358 passed / 85 skipped（基线 + Task 1 的 1 个）+ 1 个已知 DNS 假失败。
- [ ] **Step 4: 文档**（见上；数字只写实测的）。
- [ ] **Step 5: Commit**：`chore(web): drop the components the work-item template replaced; docs for the template`（只 add 明确路径）。

---

## 自检记录（写计划时完成）

- **Spec 覆盖**：§1 标准 1→T11/T13（StatusLine 唯一主按钮）、2→T8/T12/T14、3→T11/T12（模型测试）、4→T6/T9/T11/T12/T13、5→T10/T11、6→T2/T3/T4/T7/T11/T13/T14、7→T8/T15、8→每个 Task 的门禁 + T16；§3→T8/T15；§4→T8/T12；§5→T7/T9/T10/T14；§6→T11/T13/T14；§7 第 1–11 条→T11 第 2/7/8/9 条、T13 第 1/3/10 条；§8→T1；§9 六个面→T16 写入发布说明；§11→各 Task；§12→Global Constraints + T16；§13/§14→裁定 R1–R4 与 Review Focus。
- **类型一致**：`PhaseView` / `PhaseState` / `WaitingFor` 只在 `issuePhases.ts` 定义，`changePhases.ts` 与 `workItems.ts` import；`FactRow` 只在 `issueDetail.ts`；locale 前缀 `workitem.*` 在 T9/T11/T13/T14 一致。
- **无占位**：所有纯函数给出完整代码与测试；页面任务给出逐条要求与 locale 表。
