import { useState, useRef, useEffect, useMemo } from "react";
import {
  useChatSessions,
  useCreateChatSession,
  useDeleteChatSession,
} from "@/hooks/useChatSessions";
import { useLocale } from "@/i18n/LocaleContext";

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
  const [search, setSearch] = useState("");
  const searchRef = useRef<HTMLInputElement>(null);

  // Focus search input when flyout opens
  useEffect(() => {
    if (open && searchRef.current) {
      searchRef.current.focus();
    }
  }, [open]);

  // Sort by last_activity_at descending and filter by search
  const filtered = useMemo(() => {
    if (!sessions) return [];
    const sorted = [...sessions].sort(
      (a, b) =>
        new Date(b.last_activity_at).getTime() -
        new Date(a.last_activity_at).getTime(),
    );
    if (!search.trim()) return sorted;
    const q = search.toLowerCase();
    return sorted.filter((s) => s.name.toLowerCase().includes(q));
  }, [sessions, search]);

  const handleNew = async () => {
    const s = await createMut.mutateAsync(undefined);
    onSelect(s.session_id);
  };

  const handleDelete = async (sessionId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (!window.confirm(t("chat.deleteConfirm"))) return;
    await deleteMut.mutateAsync(sessionId);
    if (selectedId === sessionId && sessions && sessions.length > 1) {
      const next = sessions.find((s) => s.session_id !== sessionId);
      if (next) onSelect(next.session_id);
    }
  };

  return (
    <div
      className={`
        flex-shrink-0 flex flex-col bg-card border-r border-border
        transition-all duration-200 ease-in-out overflow-hidden
        ${open ? "w-[200px] opacity-100" : "w-0 opacity-0"}
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
                  <p
                    className={`text-xs font-medium truncate pr-4 ${
                      isActive ? "text-primary" : "text-foreground"
                    }`}
                  >
                    {s.name}
                  </p>
                  <p className="text-[10px] text-muted-foreground mt-0.5">
                    {relativeTime(s.last_activity_at)}
                  </p>

                  {/* Delete button */}
                  <button
                    onClick={(e) => handleDelete(s.session_id, e)}
                    className="absolute top-2 right-1 opacity-0 group-hover:opacity-100 w-4 h-4 rounded flex items-center justify-center text-muted-foreground hover:text-destructive hover:bg-destructive/10 transition-all"
                    title={t("common.delete")}
                  >
                    <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                    </svg>
                  </button>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Footer */}
      <div className="border-t border-border px-2 py-1.5">
        <p className="text-[10px] text-muted-foreground/50 text-center">
          {sessions?.length ?? 0} session{(sessions?.length ?? 0) !== 1 ? "s" : ""}
        </p>
      </div>
    </div>
  );
}
