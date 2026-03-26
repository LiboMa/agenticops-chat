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

interface Props {
  open: boolean;
  selectedId: string | null;
  onSelect: (id: string) => void;
  onClose: () => void;
}

/** Tiny relative-time formatter (e.g. "3m ago", "2h ago", "Jan 5"). */
function relativeTime(dateStr: string): string {
  const now = Date.now();
  const then = new Date(dateStr).getTime();
  const diffSec = Math.round((now - then) / 1000);
  if (diffSec < 60) return "just now";
  const diffMin = Math.round(diffSec / 60);
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.round(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  const diffDay = Math.round(diffHr / 24);
  if (diffDay < 7) return `${diffDay}d ago`;
  return new Date(dateStr).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
  });
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
        <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
          {t("chat.sessions")}
        </h3>
        <div className="flex items-center gap-1">
          <button
            onClick={handleNew}
            disabled={createMut.isPending}
            className="w-6 h-6 flex items-center justify-center rounded-md text-muted-foreground hover:text-foreground hover:bg-accent transition-colors disabled:opacity-50"
            title={t("chat.newChat")}
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
            </svg>
          </button>
          <button
            onClick={onClose}
            className="w-6 h-6 flex items-center justify-center rounded-md text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
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
          className="w-full px-2 py-1 text-xs bg-secondary border border-border rounded-md text-foreground placeholder-muted-foreground/50 focus:outline-none focus:ring-1 focus:ring-primary"
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
          <div className="space-y-0.5">
            {filtered.map((s) => {
              const isActive = selectedId === s.session_id;
              return (
                <div
                  key={s.session_id}
                  onClick={() => onSelect(s.session_id)}
                  className={`
                    group relative rounded-md cursor-pointer transition-all
                    ${
                      isActive
                        ? "bg-primary/10 border-l-2 border-primary pl-2 pr-1.5 py-2"
                        : "border-l-2 border-transparent pl-2 pr-1.5 py-2 hover:bg-accent"
                    }
                  `}
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
                    <p
                      onDoubleClick={(e) => {
                        e.stopPropagation();
                        setRenamingId(s.session_id);
                        setRenameValue(s.name);
                      }}
                      className={`text-xs font-medium truncate pr-4 ${
                        isActive ? "text-primary" : "text-foreground"
                      }`}
                    >
                      {s.pinned && <span title={t("chat.pinned")}>📌 </span>}
                      {s.starred && <span title={t("chat.starred")}>⭐ </span>}
                      {s.name}
                    </p>
                  )}
                  <p className="text-[10px] text-muted-foreground mt-0.5">
                    {relativeTime(s.last_activity_at)}
                  </p>

                  {/* Hover action menu */}
                  <div className="absolute top-1.5 right-1 opacity-0 group-hover:opacity-100 flex items-center gap-0.5 transition-all">
                    <button
                      onClick={(e) => handleTogglePin(s.session_id, s.pinned, e)}
                      className="w-4 h-4 rounded flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
                      title={s.pinned ? t("chat.unpin") : t("chat.pin")}
                    >
                      <span className="text-[10px]">{s.pinned ? "📌" : "📍"}</span>
                    </button>
                    <button
                      onClick={(e) => handleToggleStar(s.session_id, s.starred, e)}
                      className="w-4 h-4 rounded flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
                      title={s.starred ? t("chat.unstar") : t("chat.star")}
                    >
                      <span className="text-[10px]">{s.starred ? "⭐" : "☆"}</span>
                    </button>
                    <button
                      onClick={(e) => handleToggleArchive(s.session_id, s.archived, e)}
                      className="w-4 h-4 rounded flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
                      title={s.archived ? t("chat.unarchive") : t("chat.archive")}
                    >
                      <span className="text-[10px]">{s.archived ? "📂" : "📁"}</span>
                    </button>
                    <button
                      onClick={(e) => handleDelete(s.session_id, e)}
                      className="w-4 h-4 rounded flex items-center justify-center text-muted-foreground hover:text-destructive hover:bg-destructive/10 transition-colors"
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
        )}
      </div>

      {/* Footer with archive toggle */}
      <div className="border-t border-border px-2 py-1.5 space-y-1">
        <label className="flex items-center gap-1.5 cursor-pointer">
          <input
            type="checkbox"
            checked={showArchived}
            onChange={(e) => setShowArchived(e.target.checked)}
            className="w-3 h-3 rounded border-border accent-primary"
          />
          <span className="text-[10px] text-muted-foreground">{t("chat.showArchived")}</span>
        </label>
        <p className="text-[10px] text-muted-foreground/50 text-center">
          {sessions?.length ?? 0} session{(sessions?.length ?? 0) !== 1 ? "s" : ""}
        </p>
      </div>
      {dialog}
    </div>
  );
}
