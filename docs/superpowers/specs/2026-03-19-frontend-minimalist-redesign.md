# Frontend Minimalist Redesign — Design Spec

## Overview

Redesign the AgenticOps web frontend from 18 pages / 11 nav items to a minimalist 10-page / 6-icon layout. Chat becomes the core interface with a resizable context panel. Issues and Fix Plans merge into a unified pipeline view. Resources fold into Dashboard.

## Goals

- Reduce navigation complexity (11 items → 6 icons)
- Make Chat the primary interaction surface
- Unify the Issue → RCA → Fix Plan → Execute → Resolve pipeline into one view
- Maintain full functionality — nothing removed, only reorganized
- Add i18n (Chinese/English manual switch)
- Keep existing visual style (dark Slate/Indigo theme, Tailwind CSS)

## Navigation Structure

### Before (11 sidebar items, 224px wide)

Dashboard, Chat, Resources, Issues, Fix Plans, Reports, Schedules, Notifications, Audit Log, Knowledge Base, Skills

### After (6 icon sidebar, 52px wide)

| Icon | Page | Notes |
|------|------|-------|
| Grid | Dashboard | + Resources summary merged in |
| Chat | Chat | Core page, session flyout, context panel |
| Clock | Issues & Plans | Unified pipeline list |
| Calendar | Schedules | Unchanged |
| File | Reports | Unchanged |
| Gear | Settings | + Notifications, Audit, KB, Skills as sub-tabs |

## Routes

```
/app                → Dashboard
/app/chat           → Chat (new session)
/app/chat/:id       → Chat (specific session)
/app/issues         → Issues & Plans (unified pipeline list)
/app/issues/:id     → Issue Detail (sub-page)
/app/schedules      → Schedules
/app/schedules/:id  → Schedule Detail
/app/reports        → Reports
/app/reports/:id    → Report Detail
/app/settings       → Settings (tabbed: General, Accounts, Notifications, Audit, KB, Skills, MCP)
```

### Removed standalone pages

AnomalyDetail (→ context panel or /app/issues/:id), FixPlans (→ merged into Issues), FixPlanDetail (→ tab in Issue detail), NotificationLogs (→ Settings/Notifications tab), AuditLog (→ Settings/Audit tab), KnowledgeBase (→ Settings/KB tab), Skills (→ Settings/Skills tab), Resources (→ Dashboard module), ResourceDetail (→ Dashboard drill-down or modal).

## Shell Layout

### Icon Sidebar (52px)

- Fixed left sidebar, 52px wide
- Logo at top (gradient square, "A" initial)
- 5 page icons + 1 settings icon at bottom
- Active icon: left 2px indigo border + tinted background
- Hover: show tooltip label
- Issues icon: red badge dot when open issues exist

### TopBar

- Removed from shell (current 40px TopBar with breadcrumb, clock, font size, theme toggle)
- Theme toggle and CN/EN switch move into Settings page or a small controls area in the sidebar bottom
- Breadcrumb removed — current page is indicated by the active sidebar icon
- The TopBar space is reclaimed for content

**Alternative**: Keep a minimal 36px TopBar with only: page title (left), CN/EN toggle + theme toggle (right). No breadcrumb, no clock, no font size selector.

Decision: Keep minimal TopBar (36px) with page title + CN/EN + theme toggle.

## Chat Page

The primary interface. Three-zone layout:

```
┌──────┬────────────┬───┬──────────────┐
│      │            │   │              │
│ Icon │  Session   │   │   Context    │
│ Side │  Flyout    │ C │   Panel      │
│ bar  │  (200px)   │ h │  (resizable) │
│ 52px │  toggle    │ a │              │
│      │            │ t │  Tabs:       │
│      │            │   │  Issue |     │
│      │            │   │  Fix Plan |  │
│      │            │   │  Timeline    │
│      │            │   │              │
│      │            ├───┤              │
│      │            │ ⌨ │              │
└──────┴────────────┴───┴──────────────┘
```

### Session Flyout (200px)

- Triggered by clicking the Chat icon in the sidebar
- Click again to close (toggle behavior)
- Contains: "Sessions" header + "+" new session button, search input, session list
- Active session: indigo left border + tinted background
- Each session: name + relative timestamp
- Sorted by last activity

### Chat Area

- Message bubbles: user (left, dark bg), agent (right, indigo bg)
- Agent messages may contain:
  - Skill badges (e.g. `security-engineer`, `aws-compute`)
  - Inline Issue/Fix Plan cards (clickable → opens context panel)
  - Markdown content with tables, code blocks
  - Token count + timestamp below each message
- Auto-scroll to bottom on new messages

### Chat Input

- **Cmd/Ctrl+Enter to send, Enter for newline**
- Multi-line auto-expanding textarea
- Left: attachment button (file upload)
- Right: send button (indigo)
- Below input: metadata line showing "Detail: medium | Model: opus-4.6"

### Context Panel (resizable)

- Opens when user clicks an Issue/Fix Plan card in chat, or navigates from Issues page
- Drag handle between Chat and Panel (6px, visible grip indicator)
- Resizable range: 30% — 70%
- Panel remembers last width (localStorage)
- Close button (X) in panel header → panel closes, chat goes full width

**Panel Tabs:**

| Tab | Content |
|-----|---------|
| Issue | Severity badge, title, description, pipeline stepper, metadata grid (resource, region, account, detected), action buttons (Run RCA, Create Fix Plan) |
| Fix Plan | Plan details, risk level (L0-L3), approval status, steps, execute/approve buttons |
| Timeline | Event timeline for the issue (pipeline events in chronological order) |

## Issues & Plans Page

Unified pipeline list replacing the separate Issues and Fix Plans pages.

### Filter Bar

- Status phase filter chips: All, Open, In Progress, Resolved
- Count badges on each chip
- Search input (right side)

### List Rows

Each row displays:

```
[SEVERITY] #ID Title                          [pipeline stepper] status_label
           region · resource · time ago
```

- Severity badge: color-coded (CRITICAL=red, HIGH=orange, MEDIUM=amber, LOW=blue)
- Pipeline mini-stepper: 5 segments representing open → investigating → rca → fix → resolved
  - Completed: indigo fill
  - Current: indigo fill
  - Resolved: green fill
  - Remaining: dark gray
- Status label: current state text (right-aligned)
- Resolved rows: reduced opacity (0.5)
- Critical rows with active issues: subtle red tint background
- Click row → navigate to /app/issues/:id or open in Chat context panel

### Issue Detail Page (/app/issues/:id)

Full-page detail view (for when accessed outside of Chat):
- Same content as Context Panel tabs but with more space
- Pipeline stepper (full width)
- RCA results section
- Fix Plan section with approval workflow
- Timeline section
- Action bar at bottom

## Dashboard Page

Full overview with all modules:

| Module | Content |
|--------|---------|
| Issues Summary | Open issues by severity, clickable counts → jump to Issues page filtered |
| Resources Summary | Resource counts by type and account (merged from Resources page), expandable/drillable |
| Active Fix Plans | In-progress fix plans with progress indicators |
| Recent Activity | Last 10 pipeline events (issue created, fix executed, etc.) |
| Scheduled Jobs | Next execution times, last run status |
| Trends | Issue count trend chart (7/30/90 day toggle) |

Layout: responsive grid, cards with consistent styling.

## Settings Page

Tabbed layout consolidating low-frequency configuration:

| Tab | Content (moved from) |
|-----|---------------------|
| General | Model config, scan focus, pipeline toggles, deployment profile |
| Accounts | Cloud account CRUD (existing) |
| Notifications | Channel config, testing (from Notifications page) |
| Audit | Event timeline (from Audit Log page) |
| Knowledge Base | Vector search, KB query (from KB page) |
| Skills | Skills inventory, search, details (from Skills page) |
| MCP Servers | MCP server management (existing in Settings) |

## Internationalization (i18n)

- **Default language**: English
- **Switch**: Manual toggle button in TopBar (right side), shows "CN" / "EN"
- **Persistence**: localStorage key `aiops_locale`
- **Implementation**: React context provider with translation function `t(key)`
- **Translation files**: `src/locales/en.json`, `src/locales/zh.json`
- **Scope**: All UI labels, button text, status names, page titles, error messages, empty states
- **Not translated**: Agent responses (content from backend), log entries, resource IDs

## Visual Design

Retain existing dark theme:

- **Background**: Slate 900 (#0f172a) main, Slate 800 (#1e293b) cards/sidebar
- **Text**: Slate 200 (#e2e8f0) primary, Slate 400 (#94a3b8) secondary, Slate 500 (#64748b) muted
- **Accent**: Indigo 600 (#4f46e5) primary actions, Indigo 200 (#c7d2fe) active text
- **Borders**: Slate 700 (#334155)
- **Severity**: Red (#dc2626) critical, Orange (#f97316) high, Amber (#f59e0b) medium, Blue (#3b82f6) low
- **Success**: Green (#22c55e)
- **Font**: System font stack (-apple-system, BlinkMacSystemFont, Segoe UI, Roboto, ...)
- **Border radius**: 6px cards, 10px chat bubbles, 4px badges
- **Transitions**: Smooth 150ms for hover states, 200ms for panel open/close

## Tech Stack (unchanged)

- React 18 + TypeScript 5.6
- Vite build
- Tailwind CSS 3.4
- Radix UI primitives
- TanStack Query 5
- No new UI framework dependencies

## New Dependencies

- None for layout changes
- i18n: No external library needed — simple context + JSON approach (~200 LOC)

## Component Changes Summary

### New Components

| Component | Purpose |
|-----------|---------|
| `IconSidebar` | 52px icon sidebar replacing 224px Sidebar |
| `SessionFlyout` | Toggle-able session list panel |
| `ContextPanel` | Resizable right panel with tabs |
| `DragHandle` | Resize handle between chat and panel |
| `PipelineStepper` | Mini 5-segment status bar for issue rows |
| `IssueRow` | Unified list row with severity + pipeline stepper |
| `LocaleProvider` | i18n context provider |
| `LocaleToggle` | CN/EN switch button |
| `MinimalTopBar` | 36px top bar (page title + controls) |

### Modified Components

| Component | Change |
|-----------|--------|
| `AppShell` | Replace Sidebar with IconSidebar, add MinimalTopBar, remove old TopBar |
| `Chat` | Add session flyout trigger, context panel integration |
| `ChatInput` | Change Enter behavior (newline), add Cmd+Enter send |
| `MessageList` | Add clickable Issue/FixPlan inline cards |
| `Settings` | Add tabs for Notifications, Audit, KB, Skills |
| `Dashboard` | Add Resources summary module |

### Removed Pages (code deleted)

- `Anomalies.tsx` → merged into Issues & Plans
- `AnomalyDetail.tsx` → replaced by Issue detail + Context Panel
- `FixPlans.tsx` → merged into Issues & Plans
- `FixPlanDetail.tsx` → replaced by Fix Plan tab in Context Panel
- `NotificationLogs.tsx` → moved to Settings/Notifications tab
- `AuditLog.tsx` → moved to Settings/Audit tab
- `KnowledgeBase.tsx` → moved to Settings/KB tab
- `Skills.tsx` → moved to Settings/Skills tab
- `Resources.tsx` → merged into Dashboard
- `ResourceDetail.tsx` → Dashboard drill-down

### Removed Layout Components

- `Sidebar.tsx` (224px) → replaced by `IconSidebar.tsx` (52px)
- `TopBar.tsx` (40px) → replaced by `MinimalTopBar.tsx` (36px)
