import { useState, useRef, useEffect, useMemo } from "react";
import {
  useChatSessions,
  useCreateChatSession,
  useDeleteChatSession,
  useRenameChatSession,
  useUpdateChatSession,
} from "@/hooks/useChatSessions";
import { useLocale } from "@/i18n/LocaleContext";
import { useConfirm } from "@/components/ui/ConfirmDialog";
import { sortSessions, filterArchived } from "@/lib/sortSessions";
import { groupSessions } from "@/lib/groupSessions";
import { useActiveStreamingSessions } from "@/hooks/useSessionStream";

interface Props {
  open: boolean;
  selectedId: string | null;
  onSelect: (id: string) => void;
  onClose: () => void;
}

export function SessionFlyout({ open, selectedId, onSelect, onClose }: Props) {
  const { t } = useLocale();
  const { data: sessions, isLoading } = useChatSessions();
  const createMut = useCreateChatSession();
  const deleteMut = useDeleteChatSession();
  const renameMut = useRenameChatSession();
  const updateMut = useUpdateChatSession();
  const { confirm, dialog } = useConfirm();
  const [search, setSearch] = useState("");
  const searchRef = useRef<HTMLInputElement>(null);
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const renameRef = useRef<HTMLInputElement>(null);
  const [showArchived, setShowArchived] = useState(false);

  // Focus search input when flyout opens
  useEffect(() => {
    if (open && searchRef.current) {
      searchRef.current.focus();
    }
  }, [open]);

  // Focus + select rename input
  useEffect(() => {
    if (renamingId && renameRef.current) {
      renameRef.current.focus();
      renameRef.current.select();
    }
  }, [renamingId]);

  const handleRenameSubmit = async () => {
    const trimmed = renameValue.trim();
    if (renamingId && trimmed) {
      const session = sessions?.find((s) => s.session_id === renamingId);
      if (session && trimmed !== session.name) {
        await renameMut.mutateAsync({ sessionId: renamingId, name: trimmed });
      }
    }
    setRenamingId(null);
  };

  // Sort: pinned → starred → normal (by last_activity_at desc), filter archived, then search
  const filtered = useMemo(() => {
    if (!sessions) return [];
    const visible = filterArchived(sessions, showArchived);
    const sorted = sortSessions(visible);
    if (!search.trim()) return sorted;
    const q = search.toLowerCase();
    return sorted.filter((s) => s.name.toLowerCase().includes(q));
  }, [sessions, search, showArchived]);

  const activeStreaming = useActiveStreamingSessions();
  const groups = useMemo(() => groupSessions(filtered), [filtered]);

  const handleNew = async () => {
    const s = await createMut.mutateAsync(undefined);
    onSelect(s.session_id);
  };

  const handleDelete = async (sessionId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (!(await confirm(t("chat.deleteConfirm"), { variant: "destructive", confirmText: t("common.delete") }))) return;
    await deleteMut.mutateAsync(sessionId);
    if (selectedId === sessionId && sessions && sessions.length > 1) {
      const next = sessions.find((s) => s.session_id !== sessionId);
      if (next) onSelect(next.session_id);
    }
  };

  const handleTogglePin = (sessionId: string, currentPinned: boolean, e: React.MouseEvent) => {
    e.stopPropagation();
    updateMut.mutate({ sessionId, pinned: !currentPinned });
  };

  const handleToggleStar = (sessionId: string, currentStarred: boolean, e: React.MouseEvent) => {
    e.stopPropagation();
    updateMut.mutate({ sessionId, starred: !currentStarred });
  };

  const handleToggleArchive = (sessionId: string, currentArchived: boolean, e: React.MouseEvent) => {
    e.stopPropagation();
    updateMut.mutate({ sessionId, archived: !currentArchived });
  };

  return (
    <div
      className={`
        flex-shrink-0 flex flex-col bg-card border-r border-border
        overflow-hidden w-full h-full
      `}
    >
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

      {/* Search */}
      <div className="px-2 pb-2">
        <input
          ref={searchRef}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder={t("chat.search")}
          className="w-full px-3 py-1.5 text-xs bg-muted border border-transparent rounded-lg text-foreground placeholder-muted-foreground/60 focus:outline-none focus:ring-2 focus:ring-primary-500/40 focus:bg-background focus:border-border transition-colors"
        />
      </div>

      {/* Session list */}
      <div className="flex-1 overflow-y-auto px-1.5">
        {isLoading ? (
          <div className="space-y-2 px-1">
            {[1, 2, 3].map((i) => (
              <div key={i} className="py-2 px-2 rounded-md">
                <div className="h-3 bg-muted rounded animate-pulse w-3/4" />
                <div className="h-2.5 bg-muted rounded animate-pulse w-1/2 mt-1.5" />
              </div>
            ))}
          </div>
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
                        <div className="absolute top-1/2 -translate-y-1/2 right-1 opacity-0 group-hover:opacity-100 focus-within:opacity-100 flex items-center gap-0.5 bg-muted rounded-md px-0.5 transition-opacity">
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
      </div>

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
      {dialog}
    </div>
  );
}
