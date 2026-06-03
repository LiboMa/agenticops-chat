# Chat + Session UI Refresh — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restyle the web chat (session sidebar + message list + composer) to an open-webui-style blue/white minimal look, with time-grouped sessions — without changing any logic, hooks, backend, or state.

**Architecture:** One new pure function `lib/groupSessions.ts` (the only testable unit) buckets the already-sorted/filtered session list into time groups for render. Everything else is presentational: restyle `SessionFlyout` (grouped render + neutral active state + hover actions + blue `+New`), `MessageList` (flat assistant messages), `ChatInput` (floating pill), `Chat.tsx` (toolbar spacing), and minor `index.css` utility additions. Every existing handler, hook call, and state variable is preserved verbatim — only JSX structure and Tailwind classes change.

**Tech Stack:** React 18 + TypeScript + Tailwind + Vite/Vitest (node test env); Playwright for manual visual smoke (proven working on this project).

**Spec:** `docs/superpowers/specs/2026-06-03-chat-ui-refresh-design.md`

---

## Conventions

- **Frontend tests:** from `src/agenticops/web/frontend/`, `npm run test` (vitest `--run`, node env). Pure-logic tests only (no DOM rendering), matching `__tests__/sessionSort.prop.test.ts`.
- **Type-check / build:** `cd src/agenticops/web/frontend && npx tsc --noEmit && npm run build`.
- **Commits:** one per task, `git commit --no-verify`. Do NOT push.
- **`lib/` gitignore caveat:** new files under `src/.../lib/` need `git add -f` (existing `chatStream.ts`/`attachments.ts` were force-added). `__tests__/`, `components/`, `pages/` add normally.
- **Branch:** continue on the current branch `MVP-1.1.1-RELEASE`.
- **CRITICAL constraint:** this is a pure restyle. Do NOT change any hook call, handler, state variable, prop, or imported function. Only JSX markup + Tailwind classes (+ the one new render-only `groupSessions`). If a task seems to require a logic change, STOP and report.
- **Color tokens:** the app already has blue `--primary-*` (light + dark) and semantic tokens (`--background`, `--card`, `--muted`, `--border`, `--accent`, `--destructive`). Prefer these existing tokens + Tailwind `primary-*` classes. Do NOT introduce hardcoded hex blues — use `bg-primary-600`, `text-primary`, `bg-muted`, etc., so dark mode works automatically.

---

## File Structure

**Frontend (create):**
- `src/agenticops/web/frontend/src/lib/groupSessions.ts` — pure time-bucketing of sessions.
- `src/agenticops/web/frontend/src/__tests__/groupSessions.test.ts` — unit tests.

**Frontend (modify — restyle only):**
- `src/agenticops/web/frontend/src/components/chat/SessionFlyout.tsx` — grouped render + neutral active + blue `+New` + hover actions.
- `src/agenticops/web/frontend/src/components/chat/MessageList.tsx` — flat assistant messages, spacing.
- `src/agenticops/web/frontend/src/components/chat/ChatInput.tsx` — floating pill composer.
- `src/agenticops/web/frontend/src/pages/Chat.tsx` — toolbar centering/spacing.
- `src/agenticops/web/frontend/src/index.css` — minor utility classes (pill shadow, inline-code chip) if needed.

---

## Task 1: `groupSessions.ts` pure function + tests

**Files:**
- Create: `src/agenticops/web/frontend/src/lib/groupSessions.ts`
- Create: `src/agenticops/web/frontend/src/__tests__/groupSessions.test.ts`

- [ ] **Step 1: Write the module**

Create `src/agenticops/web/frontend/src/lib/groupSessions.ts`:

```typescript
import type { ChatSession } from "@/api/types";

export interface SessionGroup {
  label: string;
  sessions: ChatSession[];
}

/**
 * Bucket an ALREADY sorted+filtered session list (from sortSessions/filterArchived)
 * into time groups for rendering. Pinned/Starred take precedence over date.
 * A session appears in exactly one group. Empty groups are omitted. Input order
 * is preserved within each group (so sortSessions' ordering still holds).
 *
 * `now` is injectable for deterministic tests (defaults to Date.now()).
 */
export function groupSessions(
  sessions: ChatSession[],
  now: number = Date.now(),
): SessionGroup[] {
  const startOfToday = new Date(now);
  startOfToday.setHours(0, 0, 0, 0);
  const todayMs = startOfToday.getTime();
  const dayMs = 86_400_000;

  const buckets: Record<string, ChatSession[]> = {
    Pinned: [],
    Starred: [],
    Today: [],
    Yesterday: [],
    "Previous 7 days": [],
    "Previous 30 days": [],
    Older: [],
  };

  for (const s of sessions) {
    if (s.pinned) { buckets.Pinned.push(s); continue; }
    if (s.starred) { buckets.Starred.push(s); continue; }
    const t = new Date(s.last_activity_at).getTime();
    if (t >= todayMs) buckets.Today.push(s);
    else if (t >= todayMs - dayMs) buckets.Yesterday.push(s);
    else if (t >= todayMs - 7 * dayMs) buckets["Previous 7 days"].push(s);
    else if (t >= todayMs - 30 * dayMs) buckets["Previous 30 days"].push(s);
    else buckets.Older.push(s);
  }

  const order = ["Pinned", "Starred", "Today", "Yesterday", "Previous 7 days", "Previous 30 days", "Older"];
  return order
    .filter((label) => buckets[label].length > 0)
    .map((label) => ({ label, sessions: buckets[label] }));
}
```

- [ ] **Step 2: Write the failing tests**

Create `src/agenticops/web/frontend/src/__tests__/groupSessions.test.ts`:

```typescript
import { describe, it, expect } from "vitest";
import { groupSessions } from "@/lib/groupSessions";
import type { ChatSession } from "@/api/types";

// Fixed "now": 2026-06-03T12:00:00Z
const NOW = new Date("2026-06-03T12:00:00Z").getTime();
const DAY = 86_400_000;

function sess(over: Partial<ChatSession> & { session_id: string; last_activity_at: string }): ChatSession {
  return {
    id: 1,
    name: "s",
    created_at: over.last_activity_at,
    updated_at: over.last_activity_at,
    message_count: 0,
    pinned: false,
    starred: false,
    archived: false,
    ...over,
  } as ChatSession;
}

describe("groupSessions", () => {
  it("buckets by date relative to the injected now", () => {
    const today = sess({ session_id: "t", last_activity_at: "2026-06-03T09:00:00Z" });
    const yesterday = sess({ session_id: "y", last_activity_at: "2026-06-02T09:00:00Z" });
    const week = sess({ session_id: "w", last_activity_at: "2026-05-30T09:00:00Z" });
    const month = sess({ session_id: "m", last_activity_at: "2026-05-20T09:00:00Z" });
    const old = sess({ session_id: "o", last_activity_at: "2026-01-01T09:00:00Z" });
    const groups = groupSessions([today, yesterday, week, month, old], NOW);
    const labels = groups.map((g) => g.label);
    expect(labels).toEqual(["Today", "Yesterday", "Previous 7 days", "Previous 30 days", "Older"]);
  });

  it("pinned and starred take precedence over date", () => {
    const pinnedOld = sess({ session_id: "p", last_activity_at: "2026-01-01T00:00:00Z", pinned: true });
    const starredOld = sess({ session_id: "st", last_activity_at: "2026-01-01T00:00:00Z", starred: true });
    const today = sess({ session_id: "t", last_activity_at: "2026-06-03T09:00:00Z" });
    const groups = groupSessions([pinnedOld, starredOld, today], NOW);
    expect(groups.map((g) => g.label)).toEqual(["Pinned", "Starred", "Today"]);
    expect(groups[0].sessions[0].session_id).toBe("p");
    expect(groups[1].sessions[0].session_id).toBe("st");
  });

  it("omits empty groups", () => {
    const today = sess({ session_id: "t", last_activity_at: "2026-06-03T09:00:00Z" });
    const groups = groupSessions([today], NOW);
    expect(groups).toHaveLength(1);
    expect(groups[0].label).toBe("Today");
  });

  it("each session appears in exactly one group", () => {
    const list = [
      sess({ session_id: "a", last_activity_at: "2026-06-03T09:00:00Z", pinned: true }),
      sess({ session_id: "b", last_activity_at: "2026-06-03T09:00:00Z" }),
      sess({ session_id: "c", last_activity_at: "2026-05-01T09:00:00Z" }),
    ];
    const groups = groupSessions(list, NOW);
    const total = groups.reduce((n, g) => n + g.sessions.length, 0);
    expect(total).toBe(3);
  });

  it("preserves input order within a group", () => {
    const a = sess({ session_id: "a", last_activity_at: "2026-06-03T11:00:00Z" });
    const b = sess({ session_id: "b", last_activity_at: "2026-06-03T08:00:00Z" });
    const groups = groupSessions([a, b], NOW); // already sorted by caller
    expect(groups[0].sessions.map((s) => s.session_id)).toEqual(["a", "b"]);
  });

  it("empty input → empty array", () => {
    expect(groupSessions([], NOW)).toEqual([]);
  });
});
```

- [ ] **Step 3: Run tests**

Run: `cd /Users/malibo/MyDev/AgenticOps/src/agenticops/web/frontend && npx vitest --run src/__tests__/groupSessions.test.ts`
Expected: PASS (6 tests).

- [ ] **Step 4: Type-check**

Run: `npx tsc --noEmit`
Expected: PASS.

- [ ] **Step 5: Commit** (force-add — `lib/` gitignored)

```bash
cd /Users/malibo/MyDev/AgenticOps
git add -f src/agenticops/web/frontend/src/lib/groupSessions.ts
git add src/agenticops/web/frontend/src/__tests__/groupSessions.test.ts
git commit --no-verify -m "feat(web): groupSessions — time-bucketed session grouping (pure, tested)"
```
Verify: `git ls-files src/agenticops/web/frontend/src/lib/groupSessions.ts` prints the path.

---

## Task 2: SessionFlyout — grouped render + minimal blue/white restyle

**Files:**
- Modify: `src/agenticops/web/frontend/src/components/chat/SessionFlyout.tsx`

**Constraint:** preserve EVERY hook, handler, and state variable. Only change: (a) import + use `groupSessions`, (b) render groups with labels, (c) restyle classes, (d) move pin/star markers + actions per the design. Do NOT touch `handleNew/handleDelete/handleTogglePin/handleToggleStar/handleToggleArchive/handleRenameSubmit`, `useActiveStreamingSessions`, `relativeTime`, or the `filtered`/`renamingId`/`showArchived` logic.

- [ ] **Step 1: Add the groupSessions import**

In `SessionFlyout.tsx`, after the `sortSessions` import line (line 11), add:
```typescript
import { groupSessions } from "@/lib/groupSessions";
```

- [ ] **Step 2: Compute groups from the filtered list**

Immediately after the `activeStreaming` line (line 90), add:
```typescript
  const groups = useMemo(() => groupSessions(filtered), [filtered]);
```
(`useMemo` is already imported on line 1.)

- [ ] **Step 3: Restyle the header (blue `+ New`, drop the bare ＋ for a labeled button)**

Replace the header block (lines 130-155) — the `<div className="flex items-center justify-between px-3 pt-3 pb-2">...</div>` — with:

```tsx
      {/* Header */}
      <div className="flex items-center justify-between px-3 pt-3 pb-2">
        <h3 className="text-sm font-semibold text-foreground">
          {t("chat.sessions")}
        </h3>
        <div className="flex items-center gap-1">
          <button
            onClick={handleNew}
            disabled={createMut.isPending}
            className="flex items-center gap-1 px-2.5 py-1 rounded-lg bg-primary-600 hover:bg-primary-700 text-white text-xs font-medium transition-colors disabled:opacity-50"
            title={t("chat.newChat")}
          >
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
            </svg>
            {t("chat.newChat")}
          </button>
          <button
            onClick={onClose}
            className="w-7 h-7 flex items-center justify-center rounded-lg text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
            title={t("chat.close")}
          >
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
            </svg>
          </button>
        </div>
      </div>
```

- [ ] **Step 4: Restyle the search box (rounded, muted)**

Replace the search input (lines 159-165) with:
```tsx
        <input
          ref={searchRef}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder={t("chat.search")}
          className="w-full px-3 py-1.5 text-xs bg-muted border border-transparent rounded-lg text-foreground placeholder-muted-foreground/60 focus:outline-none focus:ring-2 focus:ring-primary-500/40 focus:bg-background focus:border-border transition-colors"
        />
```

- [ ] **Step 5: Replace the flat list render with grouped render + neutral active + relocated actions**

Replace the entire session-list body — the `filtered.length === 0 ? (...) : (<div className="space-y-0.5">{filtered.map(...)}</div>)` block (lines 179-278) — with the grouped version below. The empty-state branch stays; only the populated branch changes from `filtered.map` to `groups.map(... group.sessions.map ...)`:

```tsx
        ) : filtered.length === 0 ? (
          <div className="px-2 py-4 text-center">
            <p className="text-[11px] text-muted-foreground/60">
              {search ? "No matches" : t("chat.noSessions")}
            </p>
          </div>
        ) : (
          <div className="space-y-2 pb-2">
            {groups.map((group) => (
              <div key={group.label}>
                <div className="px-2 pt-2 pb-1 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground/70">
                  {group.label}
                </div>
                <div className="space-y-0.5">
                  {group.sessions.map((s) => {
                    const isActive = selectedId === s.session_id;
                    return (
                      <div
                        key={s.session_id}
                        onClick={() => onSelect(s.session_id)}
                        className={`group relative rounded-lg cursor-pointer px-2.5 py-2 transition-colors ${
                          isActive ? "bg-muted" : "hover:bg-muted/60"
                        }`}
                      >
                        {renamingId === s.session_id ? (
                          <input
                            ref={renameRef}
                            value={renameValue}
                            onChange={(e) => setRenameValue(e.target.value)}
                            onBlur={handleRenameSubmit}
                            onKeyDown={(e) => {
                              if (e.key === "Enter") { e.preventDefault(); handleRenameSubmit(); }
                              if (e.key === "Escape") setRenamingId(null);
                            }}
                            onClick={(e) => e.stopPropagation()}
                            className="text-xs font-medium bg-background border border-border rounded px-1 py-0.5 w-full focus:outline-none focus:ring-1 focus:ring-primary"
                          />
                        ) : (
                          <div className="flex items-center gap-1.5 pr-4">
                            {activeStreaming.includes(s.session_id) && (
                              <span
                                title="Streaming…"
                                className="inline-block w-1.5 h-1.5 rounded-full bg-primary-500 animate-pulse flex-shrink-0"
                              />
                            )}
                            {s.pinned && <span className="text-[10px] flex-shrink-0" title={t("chat.pinned")}>📌</span>}
                            {s.starred && <span className="text-[10px] flex-shrink-0" title={t("chat.starred")}>⭐</span>}
                            <p
                              onDoubleClick={(e) => {
                                e.stopPropagation();
                                setRenamingId(s.session_id);
                                setRenameValue(s.name);
                              }}
                              className={`text-[13px] truncate ${isActive ? "font-semibold text-foreground" : "text-foreground/90"}`}
                            >
                              {s.name}
                            </p>
                          </div>
                        )}

                        {/* Hover action menu */}
                        <div className="absolute top-1/2 -translate-y-1/2 right-1 opacity-0 group-hover:opacity-100 flex items-center gap-0.5 bg-muted rounded-md px-0.5 transition-opacity">
                          <button
                            onClick={(e) => handleTogglePin(s.session_id, s.pinned, e)}
                            className="w-5 h-5 rounded flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
                            title={s.pinned ? t("chat.unpin") : t("chat.pin")}
                          >
                            <span className="text-[10px]">{s.pinned ? "📌" : "📍"}</span>
                          </button>
                          <button
                            onClick={(e) => handleToggleStar(s.session_id, s.starred, e)}
                            className="w-5 h-5 rounded flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
                            title={s.starred ? t("chat.unstar") : t("chat.star")}
                          >
                            <span className="text-[10px]">{s.starred ? "⭐" : "☆"}</span>
                          </button>
                          <button
                            onClick={(e) => handleToggleArchive(s.session_id, s.archived, e)}
                            className="w-5 h-5 rounded flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
                            title={s.archived ? t("chat.unarchive") : t("chat.archive")}
                          >
                            <span className="text-[10px]">{s.archived ? "📂" : "📁"}</span>
                          </button>
                          <button
                            onClick={(e) => handleDelete(s.session_id, e)}
                            className="w-5 h-5 rounded flex items-center justify-center text-muted-foreground hover:text-destructive hover:bg-destructive/10 transition-colors"
                            title={t("common.delete")}
                          >
                            <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                            </svg>
                          </button>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>
        )}
```

NOTE: this drops the per-row `relativeTime(...)` second line (the time is now conveyed by the group label, matching open-webui). `relativeTime` becomes unused — remove the `relativeTime` function (lines 21-37) to avoid an unused-symbol tsc error. If tsc does NOT flag it (it may not, depending on config), leaving it is harmless; prefer removing it for cleanliness. Report which.

- [ ] **Step 6: Restyle the footer**

Replace the footer block (lines 282-295) with:
```tsx
      {/* Footer with archive toggle */}
      <div className="border-t border-border px-3 py-2 flex items-center justify-between">
        <label className="flex items-center gap-1.5 cursor-pointer">
          <input
            type="checkbox"
            checked={showArchived}
            onChange={(e) => setShowArchived(e.target.checked)}
            className="w-3 h-3 rounded border-border accent-primary"
          />
          <span className="text-[10px] text-muted-foreground">{t("chat.showArchived")}</span>
        </label>
        <span className="text-[10px] text-muted-foreground/50">
          {sessions?.length ?? 0} session{(sessions?.length ?? 0) !== 1 ? "s" : ""}
        </span>
      </div>
```

- [ ] **Step 7: Type-check + build**

Run: `cd /Users/malibo/MyDev/AgenticOps/src/agenticops/web/frontend && npx tsc --noEmit && npm run build`
Expected: PASS + build OK. (If tsc flags unused `relativeTime`, remove that function per Step 5.)

- [ ] **Step 8: Commit**

```bash
cd /Users/malibo/MyDev/AgenticOps
git add src/agenticops/web/frontend/src/components/chat/SessionFlyout.tsx
git commit --no-verify -m "feat(web): session sidebar refresh — time groups, neutral active, blue +New"
```

---

## Task 3: MessageList — flat assistant messages + spacing

**Files:**
- Modify: `src/agenticops/web/frontend/src/components/chat/MessageList.tsx`

**Constraint:** Only change the `MessageRow` assistant-branch wrapper classes and inter-message spacing. Do NOT touch the virtualizer, scroll-anchoring useEffect, streaming trailer, `renderMessageMarkdown`/`renderMarkdown`, or props.

- [ ] **Step 1: Read the current MessageRow assistant rendering**

Run:
```bash
cd /Users/malibo/MyDev/AgenticOps
sed -n '/^function MessageRow/,/^}/p' src/agenticops/web/frontend/src/components/chat/MessageList.tsx
```
Identify the assistant branch: currently the assistant content sits in `<div className="flex-1 max-w-3xl space-y-2">` with the markdown in a `<div className="text-sm ... report-content ...">`. The user branch uses `bg-primary-50 border border-primary-100 rounded-xl ...`.

- [ ] **Step 2: Make the assistant message flat (no bubble), refine the user bubble**

In `MessageRow`, the assistant content container is already effectively bubble-less (`flex-1 max-w-3xl space-y-2` — no background). The open-webui look needs: (a) confirm assistant has NO background/border (it doesn't — good), (b) the user bubble gets a softer rounded style. Update ONLY the user-branch bubble class. Find the user container:
```tsx
      <div className={msg.role === "user"
        ? "bg-primary-50 border border-primary-100 rounded-xl px-4 py-2.5 max-w-2xl"
        : "flex-1 max-w-3xl space-y-2"}>
```
Replace with (rounded-2xl, asymmetric corner for chat feel, keep blue):
```tsx
      <div className={msg.role === "user"
        ? "bg-primary-50 border border-primary-100 rounded-2xl rounded-br-md px-4 py-2.5 max-w-2xl text-primary-900"
        : "flex-1 max-w-3xl space-y-2"}>
```

- [ ] **Step 3: Increase inter-message breathing room**

Find the virtualized row wrapper that has `className="pb-5"` (the measured row div in the `items.map`). Change `pb-5` to `pb-7` for more space between messages. (Only that one class.)

- [ ] **Step 4: Type-check + build**

Run: `cd /Users/malibo/MyDev/AgenticOps/src/agenticops/web/frontend && npx tsc --noEmit && npm run build`
Expected: PASS + build OK.

- [ ] **Step 5: Commit**

```bash
cd /Users/malibo/MyDev/AgenticOps
git add src/agenticops/web/frontend/src/components/chat/MessageList.tsx
git commit --no-verify -m "feat(web): message area refresh — flat assistant text, softer user bubble, roomier spacing"
```

---

## Task 4: ChatInput — floating pill composer

**Files:**
- Modify: `src/agenticops/web/frontend/src/components/chat/ChatInput.tsx`

**Constraint:** Preserve ALL behavior (paste/drop useEffect, addFiles, attachment badges + id-keyed removal, validation error, Cmd+Enter, disabled-while-streaming, detail-level select, send/stop). Only change the layout markup/classes of the bottom control row into a pill.

- [ ] **Step 1: Read the current control-row markup**

Run:
```bash
cd /Users/malibo/MyDev/AgenticOps
sed -n '/return (/,/^}/p' src/agenticops/web/frontend/src/components/chat/ChatInput.tsx | head -120
```
The structure is: outer `<div ref={containerRef} className="border-t border-border p-4 bg-secondary ...">`, then badges, then error, then `<div className="flex gap-3 max-w-4xl mx-auto">` containing the hidden file input, detail `<select>`, attach button, `<textarea>`, and send/stop button.

- [ ] **Step 2: Wrap the controls in a pill**

Replace the controls row — the `<div className="flex gap-3 max-w-4xl mx-auto">...</div>` that holds the select/attach/textarea/send — with a pill container. Keep every child element and its handlers EXACTLY; only the wrapper class and child chrome change:

```tsx
      <div className="max-w-4xl mx-auto">
        <div className="flex items-end gap-1.5 rounded-3xl border border-border bg-background shadow-[0_2px_12px_rgba(30,64,175,0.07)] px-2 py-1.5 focus-within:ring-2 focus-within:ring-primary-500/30 transition-shadow">
          {/* Hidden file input (multiple) */}
          <input
            ref={fileInputRef}
            type="file"
            multiple
            className="hidden"
            accept={acceptAttr}
            onChange={handleFileSelect}
          />

          {/* Detail level selector */}
          {onDetailLevelChange && (
            <select
              value={detailLevel ?? "medium"}
              onChange={(e) => onDetailLevelChange(e.target.value)}
              disabled={disabled}
              className="self-center text-[11px] border-none rounded-lg px-1.5 py-1 text-muted-foreground bg-transparent hover:bg-muted focus:outline-none disabled:opacity-50 cursor-pointer"
              title="Response detail level"
            >
              <option value="concise">Concise</option>
              <option value="medium">Medium</option>
              <option value="detailed">Detailed</option>
            </select>
          )}

          {/* Attach button */}
          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={disabled}
            className="self-center w-8 h-8 flex items-center justify-center rounded-full text-muted-foreground hover:text-primary-600 hover:bg-muted disabled:opacity-50 transition-colors"
            title="Attach file"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13" />
            </svg>
          </button>

          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onPaste={handlePaste}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                e.preventDefault();
                handleSend();
              }
            }}
            placeholder="Ask about AWS resources… (paste/drag files, Cmd+Enter to send)"
            disabled={disabled}
            rows={1}
            className="flex-1 bg-transparent border-none px-2 py-2 text-sm text-foreground placeholder:text-muted-foreground/50 focus:outline-none resize-none disabled:opacity-50 max-h-40"
          />
          {streaming ? (
            <button
              onClick={onCancel}
              className="self-center w-9 h-9 flex items-center justify-center bg-red-500 hover:bg-red-600 text-white rounded-full transition-colors flex-shrink-0"
              title="Stop"
            >
              <span className="w-3 h-3 bg-white rounded-sm" />
            </button>
          ) : (
            <button
              onClick={handleSend}
              disabled={(!input.trim() && attachments.length === 0) || disabled}
              className="self-center w-9 h-9 flex items-center justify-center bg-primary-600 hover:bg-primary-700 disabled:bg-muted disabled:text-muted-foreground/40 text-white rounded-full transition-colors flex-shrink-0"
              title="Send"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 10l7-7m0 0l7 7m-7-7v18" />
              </svg>
            </button>
          )}
        </div>
      </div>
```

NOTE: this changes `rows={2}` → `rows={1}` + `max-h-40` for the pill look (the textarea grows naturally; the existing value/handlers are unchanged). The Send/Stop buttons become round icon buttons (↑ / ■) instead of text — same `onClick`, same `disabled` condition (`(!input.trim() && attachments.length === 0) || disabled`).

- [ ] **Step 3: Confirm the outer container + badges + error are unchanged**

Verify the outer `<div ref={containerRef} className="border-t border-border p-4 bg-secondary ...">`, the attachment badge block, and the `attachError` block are all still present above the pill (only the control row was replaced). The badges may have their bg refreshed but keep `key={a.id}` + `removeAttachment(a.id)`.

- [ ] **Step 4: Type-check + build**

Run: `cd /Users/malibo/MyDev/AgenticOps/src/agenticops/web/frontend && npx tsc --noEmit && npm run build`
Expected: PASS + build OK.

- [ ] **Step 5: Commit**

```bash
cd /Users/malibo/MyDev/AgenticOps
git add src/agenticops/web/frontend/src/components/chat/ChatInput.tsx
git commit --no-verify -m "feat(web): floating pill composer — round send/stop, inline detail select"
```

---

## Task 5: Chat.tsx toolbar + index.css polish

**Files:**
- Modify: `src/agenticops/web/frontend/src/pages/Chat.tsx`
- Modify: `src/agenticops/web/frontend/src/index.css`

**Constraint:** Only the session-toolbar markup/classes in Chat.tsx (center the title, quiet the Save-as-Report button). No change to layout state, flyout toggle, save dialog, context panel, or any handler.

- [ ] **Step 1: Read the current session toolbar**

Run:
```bash
cd /Users/malibo/MyDev/AgenticOps
grep -n "Session toolbar\|Save as Report\|currentSession?.name\|setShowSaveReport\|setFlyoutOpen" src/agenticops/web/frontend/src/pages/Chat.tsx
```
Locate the toolbar `<div className="flex items-center gap-2 px-4 py-2 border-b border-border bg-card/50">` containing the flyout toggle button, the session name `<h3>`, and the `Save as Report` button.

- [ ] **Step 2: Restyle the toolbar (center title, lighter border, quiet button)**

Replace the toolbar's class `className="flex items-center gap-2 px-4 py-2 border-b border-border bg-card/50"` with:
```tsx
            className="flex items-center gap-2 px-4 py-2.5 border-b border-border/60"
```
Change the session name `<h3>` class from `text-sm font-medium text-foreground truncate flex-1` to center it:
```tsx
                className="text-sm font-medium text-foreground truncate flex-1 text-center"
```
Change the `Save as Report` button class to a quiet outline chip — find its className (currently `flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium text-muted-foreground hover:text-foreground bg-secondary hover:bg-muted border border-border rounded-md transition-colors`) and replace with:
```tsx
                className="flex items-center gap-1.5 px-2.5 py-1 text-xs font-medium text-muted-foreground hover:text-foreground hover:bg-muted border border-border/60 rounded-lg transition-colors"
```
(Leave the flyout-toggle button, the SVGs, and all onClick handlers exactly as they are.)

- [ ] **Step 3: Add an inline-code chip style to index.css (if not already present)**

Run: `grep -n "report-content\|md-code\|\.md-pre" src/agenticops/web/frontend/src/index.css | head`
If there's no rule giving inline `code` a light chip background within `.report-content`, append to `index.css`:
```css
/* Chat: inline code/command chip (blue-tinted, theme-aware) */
.report-content code {
  background: hsl(var(--muted));
  color: hsl(var(--foreground));
  padding: 0.1rem 0.35rem;
  border-radius: 0.3rem;
  font-size: 0.85em;
}
.report-content pre code {
  background: transparent;
  padding: 0;
}
```
If a similar rule already exists, leave it and report.

- [ ] **Step 4: Type-check + build**

Run: `cd /Users/malibo/MyDev/AgenticOps/src/agenticops/web/frontend && npx tsc --noEmit && npm run build`
Expected: PASS + build OK.

- [ ] **Step 5: Commit**

```bash
cd /Users/malibo/MyDev/AgenticOps
git add src/agenticops/web/frontend/src/pages/Chat.tsx src/agenticops/web/frontend/src/index.css
git commit --no-verify -m "feat(web): chat toolbar polish + inline-code chip style"
```

---

## Task 6: Full verification + Playwright visual smoke (light + dark) + docs

**Files:**
- Modify: `docs/WORKFLOW.md`

- [ ] **Step 1: Full automated gate**

Run:
```bash
cd /Users/malibo/MyDev/AgenticOps/src/agenticops/web/frontend
npx tsc --noEmit && npm run build && npm run test
```
Expected: tsc clean, build OK, vitest green (groupSessions 6 + attachments 13 + chatStream 4 + sessionSort 2 = 25).

- [ ] **Step 2: Launch a fresh server on a free port serving the new build**

```bash
cd /Users/malibo/MyDev/AgenticOps
.venv/bin/python -m uvicorn agenticops.web.app:app --host 127.0.0.1 --port 8012 > /tmp/aiops-ui-smoke.log 2>&1 &
sleep 6
curl -s -m5 http://127.0.0.1:8012/api/health | head -c 80
```

- [ ] **Step 3: Playwright visual smoke — light + dark**

Drive `http://127.0.0.1:8012/app/chat` (set `localStorage.aiops_token` first, as auth is off but the frontend RequireAuth checks token presence — navigate to `/app/login`, set token, then `/app/chat`). Verify and capture a screenshot in BOTH themes (toggle the theme button):
- Session sidebar shows group labels (Pinned/Today/…); active session has gray fill; `+ New` is a blue labeled button; hovering a row reveals pin/star/archive/delete; streaming dot is blue.
- Message area: user = blue bubble, assistant = flat text; tool chip visible; inline code chip styled.
- Composer is a floating pill with a round blue send button; paste an image → badge appears; detail select works.
- Toggle to dark mode → all of the above is legible (no invisible text, no white-on-white).
- Console has 0 errors.
Record results. (Reuse the Playwright approach from the prior paste/drop smoke test.)

- [ ] **Step 4: Stop the smoke server**

```bash
lsof -ti:8012 | xargs kill 2>/dev/null && echo "stopped 8012"
```

- [ ] **Step 5: Update WORKFLOW.md**

In `docs/WORKFLOW.md`, find the chat section and append a brief note under it (or near the "Web composer input" note added previously):
```markdown
**Chat UI (v1.1.x):** open-webui-style blue/white minimal look — sessions grouped by time
(Pinned/Today/Previous 7 days/…), neutral active row with a blue streaming dot, hover-revealed
pin/star/archive/delete, flat assistant messages (no bubble) with soft-blue user bubbles, and a
floating pill composer. Purely presentational — no change to streaming, pagination, or session logic.
```

- [ ] **Step 6: Commit docs**

```bash
cd /Users/malibo/MyDev/AgenticOps
git add docs/WORKFLOW.md
git commit --no-verify -m "docs: note chat UI refresh (open-webui blue/white) in WORKFLOW"
```

---

## Self-Review Notes (author)

- **Spec coverage:** time grouping (T1 groupSessions + T2 render), minimal gray-active sidebar w/ blue accents + blue +New + hover actions + drop always-on emoji noise (T2), flat assistant + blue user bubble (T3), floating pill composer w/ round blue send + inline detail select (T4), toolbar polish + inline-code chip (T5), both light+dark verified + docs (T6). All spec sections map to a task.
- **Pure-restyle guarantee:** every task's constraint block forbids logic/hook/handler changes; T2 explicitly preserves all handlers (handleNew/Delete/TogglePin/Star/Archive/RenameSubmit, useActiveStreamingSessions); T4 preserves the paste/drop useEffect + addFiles + id-keyed removal; T3 preserves virtualizer/scroll/markdown. Only `groupSessions` (render-only) is new logic, and it's unit-tested.
- **Type/name consistency:** `groupSessions(sessions, now?)` → `SessionGroup[]` (T1) consumed as `groups.map(g => g.label / g.sessions)` (T2). `activeStreaming.includes(s.session_id)`, `removeAttachment(a.id)`, `attachments.length`, `detailLevel`/`onDetailLevelChange` — all match existing code. Send button disabled condition `(!input.trim() && attachments.length === 0) || disabled` matches the current ChatInput exactly.
- **Color discipline:** uses existing `primary-*` + semantic tokens (`bg-muted`, `text-foreground`, `border-border`, `bg-background`) so dark mode is automatic; no hardcoded hex. T6 explicitly verifies dark.
- **`relativeTime` removal:** flagged in T2 Step 5 (becomes unused when the per-row time line is replaced by group labels) — remove to keep tsc clean.
- **No new deps. No new features** (message actions / tool-detail / highlighting explicitly out of scope per spec).
