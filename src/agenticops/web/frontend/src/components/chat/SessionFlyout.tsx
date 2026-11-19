import { useEffect, useMemo, useRef, useState } from "react";
import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import {
  useChatSessionList,
  useCreateChatSession,
  useDeleteChatSession,
  useRenameChatSession,
  useUpdateChatSession,
} from "@/hooks/useChatSessions";
import { useLocale } from "@/i18n/LocaleContext";
import { sessionRowLabel } from "@/lib/chatMessageStatus";
import { useConfirm } from "@/components/ui/ConfirmDialog";
import { StatusText } from "@/components/ui/StatusText";
import { useActiveStreamingSessions } from "@/hooks/useSessionStream";
import { useAuth } from "@/hooks/useAuth";
import { useBootstrap } from "@/hooks/useBootstrap";
import { draftKey, hasDraft } from "@/lib/chatDrafts";
import { currentUserId } from "@/lib/home";
import { otherVisibility, visibilityWord } from "@/lib/sessionVisibility";
import {
  SESSION_VIEWS, activityKey, agoParts, countsLine, menuActions, nextAfterDelete, sessionGroups,
  type MenuAction, type SessionView,
} from "@/lib/sessionList";
import type { ChatSession } from "@/api/types";

interface Props {
  open: boolean;
  selectedId: string | null;
  onSelect: (id: string) => void;
  onClose: () => void;
  /** the open conversation was deleted and there is no other: the page goes to its welcome */
  onNone?: () => void;
}

const fill = (text: string, vars: Record<string, string | number>) =>
  Object.entries(vars).reduce((s, [k, v]) => s.replace(`{${k}}`, String(v)), text);
const UNDO_MS = 8000;

/** The conversation list (MVP-2.9.0 N22 — the 2.8.0 spec's S5). The server filters, searches and orders: three
 *  tabs that each ask it (the archive was only ever filtered here, from rows that were never fetched), a search over
 *  every conversation, pinned ones first however old. A row is a link; what can be done to it is one ⋯ menu;
 *  archiving can be undone; a list that did not load says so instead of «no conversations». */
export function SessionFlyout({ open, selectedId, onSelect, onClose, onNone }: Props) {
  const { t } = useLocale();
  const [view, setView] = useState<SessionView>("all");
  const [draft, setDraft] = useState("");
  const [q, setQ] = useState("");
  useEffect(() => {                                     // the search runs once the typing pauses
    const id = window.setTimeout(() => setQ(draft.trim()), 300);
    return () => window.clearTimeout(id);
  }, [draft]);
  const list = useChatSessionList(view, q);
  const createMut = useCreateChatSession();
  const deleteMut = useDeleteChatSession();
  const renameMut = useRenameChatSession();
  const updateMut = useUpdateChatSession();
  const { isAuthenticated } = useAuth();
  const boot = useBootstrap();
  const { confirm, dialog } = useConfirm();
  const searchRef = useRef<HTMLInputElement>(null);
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [renameFailed, setRenameFailed] = useState(false);
  const renameRef = useRef<HTMLInputElement>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [undo, setUndo] = useState<{ sessionId: string; name: string; archived: boolean } | null>(null);

  useEffect(() => { if (open) searchRef.current?.focus(); }, [open]);
  useEffect(() => {
    if (renamingId && renameRef.current) { renameRef.current.focus(); renameRef.current.select(); }
  }, [renamingId]);
  useEffect(() => {
    if (!undo) return;
    const id = window.setTimeout(() => setUndo(null), UNDO_MS);
    return () => window.clearTimeout(id);
  }, [undo]);

  const pages = list.data?.pages ?? [];
  const rows = useMemo(() => pages.flatMap((p) => p.items), [pages]);
  const last = pages[pages.length - 1];
  const groups = useMemo(() => sessionGroups(rows), [rows]);
  const activeStreaming = useActiveStreamingSessions();
  const failedFirst = list.isError && !list.data;
  const counts = last ? countsLine(q, last.total, last.all_total) : null;

  const handleNew = async () => {
    const s = await createMut.mutateAsync(undefined);
    onSelect(s.session_id);
  };

  const submitRename = async () => {
    const name = renameValue.trim();
    const session = rows.find((s) => s.session_id === renamingId);
    if (!renamingId || !name || !session || name === session.name) { setRenamingId(null); setRenameFailed(false); return; }
    try {
      await renameMut.mutateAsync({ sessionId: renamingId, name });
      setRenamingId(null); setRenameFailed(false);
    } catch {
      setRenameFailed(true);                            // the box stays open with what was typed
    }
  };

  const change = (s: ChatSession, fields: Parameters<typeof updateMut.mutate>[0], after?: () => void) => {
    setProblem(null);
    updateMut.mutate(fields, { onSuccess: after, onError: () => setProblem(fill(t("chat.actionFailed"), { name: s.name })) });
  };

  const act = async (s: ChatSession, action: MenuAction) => {
    if (action === "rename") { setRenameFailed(false); setRenameValue(s.name); setRenamingId(s.session_id); return; }
    if (action === "pin") return change(s, { sessionId: s.session_id, pinned: !s.pinned });
    if (action === "star") return change(s, { sessionId: s.session_id, starred: !s.starred });
    if (action === "visibility") return change(s, { sessionId: s.session_id, visibility: otherVisibility(s) });
    if (action === "archive") {
      const archived = !s.archived;
      return change(s, { sessionId: s.session_id, archived }, () => setUndo({ sessionId: s.session_id, name: s.name, archived }));
    }
    if (!(await confirm(fill(t("chat.deleteConfirmNamed"), { name: s.name }), { variant: "destructive", confirmText: t("common.delete") }))) return;
    const next = nextAfterDelete(rows, s.session_id);
    setProblem(null);
    try {
      await deleteMut.mutateAsync(s.session_id);
      if (selectedId === s.session_id) { if (next) onSelect(next); else onNone?.(); }
    } catch {
      setProblem(fill(t("chat.actionFailed"), { name: s.name }));
    }
  };

  const emptyText = q ? t("chat.empty.search") : view === "archived" ? t("chat.empty.archived") : view === "starred" ? t("chat.empty.starred") : t("chat.noSessions");
  const item = "flex w-full cursor-pointer select-none items-center rounded px-2.5 py-1.5 text-sm outline-none data-[highlighted]:bg-accent";

  return (
    <div className="flex-shrink-0 flex flex-col bg-card border-r border-border overflow-hidden w-full h-full">
      {/* Header */}
      <div className="flex items-center justify-between px-3 pt-3 pb-2">
        <h3 className="text-sm font-semibold text-foreground">{t("chat.sessions")}</h3>
        <div className="flex items-center gap-1">
          <button onClick={handleNew} disabled={createMut.isPending} title={t("chat.newChat")}
                  className="flex items-center gap-1 px-2.5 py-1 rounded-lg bg-primary-600 hover:bg-primary-700 text-white text-xs font-medium transition-colors disabled:opacity-50 max-[767px]:min-h-[44px]">
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden>
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
            </svg>
            {t("chat.newChat")}
          </button>
          <button onClick={onClose} title={t("chat.close")} aria-label={t("chat.close")}
                  className="w-7 h-7 flex items-center justify-center rounded-lg text-muted-foreground hover:text-foreground hover:bg-accent transition-colors max-[767px]:h-[44px] max-[767px]:w-[44px]">
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden>
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
            </svg>
          </button>
        </div>
      </div>

      {/* The three views: each one asks the server */}
      <div role="tablist" aria-label={t("chat.sessions")} className="mx-2 mb-2 flex rounded-lg border border-border p-0.5 text-xs">
        {SESSION_VIEWS.map((v) => (
          <button key={v} type="button" role="tab" aria-selected={view === v} onClick={() => { setView(v); setUndo(null); }}
                  className={`flex-1 rounded-md px-2 py-1 max-[767px]:min-h-[40px] ${view === v ? "bg-selected font-semibold text-primary" : "text-muted-foreground hover:text-foreground"}`}>
            {t(`chat.view.${v}`)}
          </button>
        ))}
      </div>

      {/* Search: over every conversation of the view, on the server */}
      <div className="px-2 pb-2">
        <input ref={searchRef} type="search" value={draft} onChange={(e) => setDraft(e.target.value)} maxLength={200}
               placeholder={t("chat.search")} aria-label={t("chat.search")}
               className="w-full px-3 py-1.5 text-xs max-[767px]:text-[16px] bg-muted border border-transparent rounded-lg text-foreground placeholder-muted-foreground/60 focus:outline-none focus:ring-2 focus:ring-primary-500/40 focus:bg-background focus:border-border transition-colors" />
      </div>

      {problem && (
        <p role="alert" className="mx-2 mb-2 rounded-md border border-status-danger/30 bg-status-danger/10 px-2.5 py-1.5 text-xs text-status-danger">{problem}</p>
      )}
      {list.isError && list.data && (
        <p role="status" className="mx-2 mb-2 flex items-center justify-between gap-2 rounded-md border border-status-warn/30 bg-status-warn/10 px-2.5 py-1.5 text-xs text-status-warn">
          {t("chat.list.stale")}
          <button type="button" className="underline" onClick={() => void list.refetch()}>{t("common.retry")}</button>
        </p>
      )}

      {/* The list */}
      <div className="flex-1 overflow-y-auto px-1.5">
        {failedFirst ? (
          <div role="alert" className="px-2 py-4 text-center text-xs">
            <p className="text-status-danger">{t("chat.list.failed")}</p>
            <button type="button" onClick={() => void list.refetch()}
                    className="mt-2 rounded-md border border-border px-3 py-1.5 text-foreground hover:bg-accent max-[767px]:min-h-[44px]">{t("common.retry")}</button>
          </div>
        ) : list.isPending ? (
          <div className="space-y-2 px-1" aria-busy="true">
            {[1, 2, 3].map((i) => (
              <div key={i} className="py-2 px-2 rounded-md">
                <div className="h-3 bg-muted rounded animate-pulse motion-reduce:animate-none w-3/4" />
                <div className="h-2.5 bg-muted rounded animate-pulse motion-reduce:animate-none w-1/2 mt-1.5" />
              </div>
            ))}
          </div>
        ) : rows.length === 0 ? (
          <p className="px-2 py-4 text-center text-xs text-muted-foreground">{emptyText}</p>
        ) : (
          <div className={`space-y-2 pb-2 ${list.isPlaceholderData ? "opacity-60" : ""}`}>
            {groups.map((group) => (
              <div key={group.key}>
                <div className="px-2 pt-2 pb-1 text-[11px] font-semibold text-muted-foreground">{t(`chat.group.${group.key}`)}</div>
                <ul className="space-y-0.5">
                  {group.sessions.map((s) => {
                    const isActive = selectedId === s.session_id;
                    const label = sessionRowLabel(s);
                    const ago = agoParts(s.last_activity_at);
                    const who = visibilityWord(s, isAuthenticated);
                    const doing = activityKey(s, activeStreaming.includes(s.session_id));
                    const kept = !isActive && hasDraft(localStorage, draftKey(boot.data?.deployment_id, currentUserId(), s.session_id));
                    const actions = menuActions(s, isAuthenticated);
                    return (
                      <li key={s.session_id} className={`group relative rounded-lg transition-colors ${isActive ? "bg-muted" : "hover:bg-muted/60"}`}>
                        {renamingId === s.session_id ? (
                          <div className="px-2.5 py-2">
                            <input ref={renameRef} value={renameValue} maxLength={200} aria-label={t("chat.rename")}
                                   onChange={(e) => { setRenameValue(e.target.value); setRenameFailed(false); }}
                                   onBlur={() => { if (!renameFailed) void submitRename(); }}
                                   onKeyDown={(e) => {
                                     if (e.key === "Enter") { e.preventDefault(); void submitRename(); }
                                     if (e.key === "Escape") { e.stopPropagation(); setRenamingId(null); setRenameFailed(false); }
                                   }}
                                   className="w-full rounded border border-border bg-background px-1.5 py-1 text-sm max-[767px]:text-[16px] focus:outline-none focus:ring-1 focus:ring-primary" />
                            {renameFailed && (
                              <p role="alert" className="mt-1 flex items-center justify-between gap-2 text-[11px] text-status-danger">
                                {t("chat.renameFailed")}
                                <button type="button" className="underline" onClick={() => void submitRename()}>{t("common.retry")}</button>
                              </p>
                            )}
                          </div>
                        ) : (
                          <a href={`/app/chat/${s.session_id}`} aria-current={isActive ? "page" : undefined}
                             onClick={(e) => { if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return; e.preventDefault(); onSelect(s.session_id); }}
                             className="block rounded-lg py-2 pl-2.5 pr-9 max-[767px]:pr-12 outline-none focus-visible:ring-2 focus-visible:ring-primary">
                            <span className="flex items-start gap-1.5">
                              {s.starred && (
                                <svg className="mt-0.5 h-3 w-3 flex-shrink-0 text-status-warn" viewBox="0 0 16 16" fill="currentColor" role="img" aria-label={t("chat.starred")}>
                                  <path d="M8 1.5l1.9 4 4.4.5-3.3 3 .9 4.4L8 11.2 4.1 13.4 5 9 1.7 6l4.4-.5z" />
                                </svg>
                              )}
                              <span className={`line-clamp-2 min-w-0 text-[13px] [overflow-wrap:anywhere] ${isActive ? "font-semibold text-foreground" : "text-foreground/90"}`}>{s.name}</span>
                            </span>
                            {/* what it is about · its account · how long ago */}
                            <span className="mt-0.5 block truncate text-[11px] text-muted-foreground">
                              {label.text ? <span className="font-mono">{label.text}</span> : t(label.key!)}
                              {s.context?.account_name && <> · {s.context.account_name}</>}
                              {" · "}{fill(t(ago.key), { n: ago.n })}
                            </span>
                            {/* who sees it · what is going on · a draft kept */}
                            {(who || doing || kept) && (
                              <span className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px] text-muted-foreground">
                                {who && (
                                  <span className="inline-flex items-center gap-1">
                                    <svg className="h-3 w-3" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden>
                                      {who === "workspace"
                                        ? <path d="M5.5 7a2 2 0 1 0 0-4 2 2 0 0 0 0 4zm5.5 0a1.7 1.7 0 1 0 0-3.4A1.7 1.7 0 0 0 11 7zM1.5 13c0-2 1.8-3.3 4-3.3s4 1.3 4 3.3M10.5 9.8c1.9 0 3.5 1.1 3.5 3" />
                                        : <path d="M4.5 7V5a3.5 3.5 0 0 1 7 0v2M3.5 7h9v6.5h-9z" />}
                                    </svg>
                                    {t(`chat.visibility.${who}`)}
                                  </span>
                                )}
                                {doing && <StatusText tone={doing === "chat.activity.generating" ? "info" : doing === "chat.activity.waiting" ? "warn" : "danger"}>{t(doing)}</StatusText>}
                                {kept && <span>{t("chat.draftKept")}</span>}
                              </span>
                            )}
                          </a>
                        )}

                        {/* One menu, always there (a row of hover-only icons could not be reached by touch or keyboard) */}
                        {actions.length > 0 && renamingId !== s.session_id && (
                          <DropdownMenu.Root>
                            <DropdownMenu.Trigger asChild>
                              <button type="button" aria-label={fill(t("chat.menuFor"), { name: s.name })} title={t("chat.menu")}
                                      className="absolute right-1 top-1.5 flex h-7 w-7 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary max-[767px]:h-[44px] max-[767px]:w-[44px]">
                                <svg className="h-4 w-4" viewBox="0 0 16 16" fill="currentColor" aria-hidden><circle cx="3.5" cy="8" r="1.2" /><circle cx="8" cy="8" r="1.2" /><circle cx="12.5" cy="8" r="1.2" /></svg>
                              </button>
                            </DropdownMenu.Trigger>
                            <DropdownMenu.Portal>
                              <DropdownMenu.Content align="end" sideOffset={4}
                                                    className="z-[60] min-w-[170px] rounded-md border border-border bg-card p-1.5 shadow-lg animate-[slideInRight_0.2s_ease-out]">
                                {actions.map((a) => (
                                  <DropdownMenu.Item key={a.id} onSelect={() => void act(s, a.id)}
                                                     className={`${item} ${a.id === "delete" ? "mt-1 border-t border-border pt-2 text-status-danger" : ""}`}>
                                    {t(a.labelKey)}
                                  </DropdownMenu.Item>
                                ))}
                              </DropdownMenu.Content>
                            </DropdownMenu.Portal>
                          </DropdownMenu.Root>
                        )}
                      </li>
                    );
                  })}
                </ul>
              </div>
            ))}
            {list.hasNextPage && (
              <div className="px-1 pt-1">
                <button type="button" onClick={() => void list.fetchNextPage()} disabled={list.isFetchingNextPage}
                        className="w-full rounded-md border border-border px-3 py-1.5 text-xs text-foreground hover:bg-accent disabled:opacity-60 max-[767px]:min-h-[44px]">
                  {list.isFetchingNextPage ? t("chat.list.moreBusy") : t("chat.list.more")}
                </button>
                {list.isFetchNextPageError && <p role="alert" className="mt-1 text-center text-[11px] text-status-danger">{t("chat.list.moreFailed")}</p>}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Archived (or restored) just now: it can be taken back */}
      {undo && (
        <div role="status" className="mx-2 mb-2 flex items-center justify-between gap-2 rounded-md border border-border bg-background px-2.5 py-1.5 text-xs shadow-sm">
          <span className="min-w-0 truncate">{fill(t(undo.archived ? "chat.archivedToast" : "chat.restoredToast"), { name: undo.name })}</span>
          <button type="button" className="flex-shrink-0 font-medium text-primary hover:underline max-[767px]:min-h-[40px]"
                  onClick={() => { const u = undo; setUndo(null); updateMut.mutate({ sessionId: u.sessionId, archived: !u.archived },
                                     { onError: () => setProblem(fill(t("chat.actionFailed"), { name: u.name })) }); }}>
            {t("chat.undo")}
          </button>
        </div>
      )}

      {/* How many: of the view — and how many of them match */}
      <div className="border-t border-border px-3 py-2 text-[11px] text-muted-foreground" role="status">
        {counts ? fill(t(counts.key), counts.vars) : " "}
      </div>
      {dialog}
    </div>
  );
}
