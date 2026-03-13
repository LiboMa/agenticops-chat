# Resource Detail Page + Dashboard Trends

**Date**: 2026-03-14
**Status**: Approved
**Principle**: Small, precise, performant — no over-engineering

---

## 1. Resource Detail Page

### Route

`/app/resources/:id` — new page, replaces `?highlight=` in CommandPalette.

### Layout

Tab-based detail page with type-aware tabs:

```
┌─────────────────────────────────────────────┐
│ [EC2] web-prod-01  i-0abc123                │
│ t3.large · us-east-1 · ● running · prod-main│
├──────┬────────┬───────────┬─────────┬───────┤
│ Over │ Issues │ Fix Plans │ Network │ Tags  │
├──────┴────────┴───────────┴─────────┴───────┤
│ (tab content)                                │
└──────────────────────────────────────────────┘
```

### Tabs

| Tab | Content | Data source |
|-----|---------|-------------|
| **Overview** | Type-specific metadata from `resource_metadata` JSON | `GET /api/resources/:id` (existing) |
| **Issues** | HealthIssue list for this `resource_id`, clickable | `GET /api/resources/:id/issues` (new) |
| **Fix Plans** | FixPlan + FixExecution history | `GET /api/resources/:id/fix-plans` (new) |
| **Network** (compute) / **Contains** (infra) | See below | `GET /api/resources/:id/related` (new) |
| **Tags** | `tags` JSON as key-value table | From existing resource response |

### Type-aware 4th tab

Resource types classified into two groups:

**Compute** (EC2, Lambda, RDS, ECS, EKS, ElastiCache, ELB): Tab = "Network"
- Shows: parent VPC, Subnet, associated Security Groups with rules
- Direction: "I belong to" (looking up)

**Infrastructure** (VPC, Subnet, SecurityGroup, RouteTable, IGW, NAT, TGW): Tab = "Contains"
- VPC → Subnets, contained resources
- Subnet → parent VPC, CIDR, AZ, contained resources
- SG → inbound/outbound rules, "Used By" resource list
- Direction: "I contain / am used by" (looking down)

### Resource linking

All resource references are clickable links navigating to `/app/resources/:id`. This enables traversal: EC2 → VPC → Subnet → back to EC2.

Lookup: match by `resource_id` field (AWS ID like `vpc-xxx`, `sg-xxx`). If the referenced resource exists in `aws_resources`, link it. If not, show as plain text.

### Data source for related resources

Query `graph_nodes` + `graph_edges` tables (already populated by scan agent). Fallback: parse `resource_metadata` for VPC/Subnet/SG IDs and look up in `aws_resources`.

---

## 2. Dashboard Trends (Compact Strip)

### Layout

Inserted between KPI strip and content grid:

```
┌──────────┬──────────┬──────────┬──────────┬──────────┐  [7d] 30d 90d
│ Issues   │ Severity │Resources │ MTTR     │ Fix Rate │
│ +8 / -12 │ 2 crit   │ +14      │ 2.4h ↓   │ 87% ↑    │
│ ▁▃▅▂▄▆▃  │ ▁▃▅▂▄▆▃  │ ▁▃▅▂▄▆▃  │ ▆▅▄▃▂▁▂  │ ▁▂▃▄▅▆▇  │
└──────────┴──────────┴──────────┴──────────┴──────────┘
```

### 5 Trend Cards

| Card | Headline | Sparkline | Query |
|------|----------|-----------|-------|
| **Issue Trend** | opened / resolved counts in period | Daily opened vs resolved bars | `GROUP BY date(detected_at)` on HealthIssue + count resolved_at |
| **Severity** | Current critical count | Daily stacked by severity | `GROUP BY date(detected_at), severity` on HealthIssue |
| **Resource Changes** | Net new in period (+N / -N) | Daily new/updated count | `GROUP BY date(created_at)` on AWSResource |
| **MTTR** | Average hours + trend arrow | Daily average resolve time | `AVG(resolved_at - detected_at)` on resolved HealthIssues per day |
| **Fix Success Rate** | Percentage + trend arrow | Daily success ratio | `COUNT(succeeded) / COUNT(*)` on FixExecution per day |

### Time range

- Toggle: 7d (default) / 30d / 90d
- Single `days` parameter controls all 5 queries
- Frontend: `staleTime: 60_000` (1 minute cache)

### Data strategy

All real-time aggregation from existing tables. No new tables, no cron jobs.

Performance: each query scans at most 90 days of data with indexed date columns. SQLite handles this in <10ms for typical datasets (<100k rows). Single API call returns all 5 datasets.

---

## 3. Backend API

### New endpoints

```
GET /api/resources/{id}/issues?limit=20
  → List[HealthIssueResponse] where resource_id matches

GET /api/resources/{id}/fix-plans?limit=20
  → List[FixPlanResponse] joined with FixExecution

GET /api/resources/{id}/related
  → { network: [...], contains: [...], used_by: [...] }
  Uses graph_edges or resource_metadata fallback

GET /api/dashboard/trends?days=7
  → {
      issues: [{date, opened, resolved}, ...],
      severity: [{date, critical, high, medium, low}, ...],
      resources: [{date, added, updated}, ...],
      mttr: [{date, avg_hours}, ...],
      fix_rate: [{date, total, succeeded, rate}, ...],
      summary: {
        issues_opened, issues_resolved,
        resource_net_change,
        mttr_avg_hours, mttr_trend,  // "up" | "down" | "flat"
        fix_rate_pct, fix_rate_trend
      }
    }
```

### Query strategy

- `/resources/{id}/issues`: `session.query(HealthIssue).filter(HealthIssue.resource_id == resource.resource_id)`
- `/resources/{id}/fix-plans`: Join through HealthIssue.resource_id → FixPlan
- `/resources/{id}/related`: Query `graph_edges` where source or target matches resource node ID
- `/dashboard/trends`: 5 aggregate queries with `GROUP BY date(...)`, date range filter via `WHERE detected_at >= :cutoff`

All queries use existing indexes. No new indexes needed.

---

## 4. Frontend Changes

### New files

| File | Purpose |
|------|---------|
| `pages/ResourceDetail.tsx` | Detail page with tabs |
| `hooks/useResourceDetail.ts` | Fetch resource + issues + fix-plans + related |
| `hooks/useDashboardTrends.ts` | Fetch `/api/dashboard/trends` |

### Modified files

| File | Change |
|------|--------|
| `App.tsx` | Add route `resources/:id` → ResourceDetail |
| `pages/Dashboard.tsx` | Add TrendStrip below KPI strip |
| `pages/Resources.tsx` | Row click → navigate to `/app/resources/:id` |
| `components/CommandPalette.tsx` | Resource route: `/app/resources/${item.id}` (remove `?highlight=`) |

### No new dependencies

Charts rendered with pure CSS/HTML (div bars like existing Dashboard). No chart library needed.

---

## 5. What's NOT in scope

- No real-time AWS API calls from detail page
- No CloudWatch metrics in resource detail (user explicitly excluded)
- No new DB tables or models
- No daily snapshot cron job
- No chart library (Recharts, etc.)
- No resource deletion tracking (resource changes = new/updated only)

---

## 6. Performance checklist

- [ ] All DB queries use existing indexed columns
- [ ] Dashboard trends: single API call, 5 lightweight aggregations
- [ ] Frontend staleTime ≥ 60s on all trend queries
- [ ] Resource detail: lazy-load tab content (only fetch when tab active)
- [ ] Related resources query has fallback if graph tables empty
