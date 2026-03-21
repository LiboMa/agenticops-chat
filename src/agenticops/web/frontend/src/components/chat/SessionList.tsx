import { useState, useRef, useEffect } from "react";
import { useChatSessions, useCreateChatSession, useDeleteChatSession, useRenameChatSession } from "@/hooks/useChatSessions";
import { formatShortDate } from "@/lib/formatDate";
import { useConfirm } from "@/components/ui/ConfirmDialog";

interface Props {
  selectedId: string | null;
  onSelect: (sessionId: string) => void;
}

export function SessionList({ selectedId, onSelect }: Props) {
  const { data: sessions, isLoading } = useChatSessions();
  const createMut = useCreateChatSession();
  const deleteMut = useDeleteChatSession();
  const renameMut = useRenameChatSession();
  const { confirm, dialog } = useConfirm();
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const renameRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (renamingId && renameRef.current) {
      renameRef.current.focus();
      renameRef.current.select();
    }
  }, [renamingId]);

  const handleNew = async () => {
    const s = await createMut.mutateAsync(undefined);
    onSelect(s.session_id);
  };

  const handleDelete = async (sessionId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (!(await confirm("Delete this chat session?", { variant: "destructive", confirmText: "Delete" }))) return;
    await deleteMut.mutateAsync(sessionId);
    if (selectedId === sessionId && sessions && sessions.length > 1) {
      const next = sessions.find((s) => s.session_id !== sessionId);
      if (next) onSelect(next.session_id);
    }
  };

  const handleDoubleClick = (sessionId: string, currentName: string) => {
    setRenamingId(sessionId);
    setRenameValue(currentName);
  };

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

  return (
    <div className="w-60 flex-shrink-0 border-r border-border flex flex-col bg-card">
      {/* Header */}
      <div className="p-3 border-b border-border">
        <button
          onClick={handleNew}
          disabled={createMut.isPending}
          className="w-full px-3 py-2 bg-primary hover:bg-primary-700 text-primary-foreground text-sm font-medium rounded-lg transition-colors disabled:opacity-50 flex items-center justify-center gap-2"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
          </svg>
          New Chat
        </button>
      </div>

      {/* Session list */}
      <div className="flex-1 overflow-y-auto">
        {isLoading ? (
          <div className="p-2 space-y-2">
            {[1, 2, 3].map((i) => (
              <div key={i} className="px-3 py-3 rounded-lg">
                <div className="h-4 bg-muted rounded animate-pulse w-3/4" />
                <div className="h-3 bg-muted rounded animate-pulse w-1/2 mt-2" />
              </div>
            ))}
          </div>
        ) : !sessions || sessions.length === 0 ? (
          <div className="p-4 text-center">
            <div className="text-muted-foreground/60 mb-1">
              <svg className="w-8 h-8 mx-auto" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
              </svg>
            </div>
            <p className="text-xs text-muted-foreground">No conversations yet</p>
            <p className="text-xs text-muted-foreground/60 mt-0.5">Click "New Chat" to start</p>
          </div>
        ) : (
          <div className="p-1.5 space-y-0.5">
            {sessions.map((s) => {
              const isSelected = selectedId === s.session_id;
              const isRenaming = renamingId === s.session_id;

              return (
                <div
                  key={s.session_id}
                  onClick={() => onSelect(s.session_id)}
                  onDoubleClick={() => handleDoubleClick(s.session_id, s.name)}
                  className={`group relative px-3 py-2.5 rounded-lg cursor-pointer transition-all ${
                    isSelected
                      ? "bg-primary-50 border border-primary-200"
                      : "hover:bg-accent"
                  }`}
                >
                  {isRenaming ? (
                    <input
                      ref={renameRef}
                      value={renameValue}
                      onChange={(e) => setRenameValue(e.target.value)}
                      onBlur={handleRenameSubmit}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") handleRenameSubmit();
                        if (e.key === "Escape") setRenamingId(null);
                      }}
                      className="w-full text-sm font-medium bg-background border border-border rounded px-1.5 py-0.5 focus:outline-none focus:ring-1 focus:ring-primary"
                      onClick={(e) => e.stopPropagation()}
                    />
                  ) : (
                    <p className={`text-sm font-medium truncate pr-5 ${isSelected ? "text-primary-700" : "text-foreground"}`}>
                      {s.name}
                    </p>
                  )}
                  <div className="flex items-center gap-1.5 mt-1">
                    <span className={`text-[11px] ${isSelected ? "text-primary-600" : "text-muted-foreground"}`}>
                      {s.message_count} msgs
                    </span>
                    <span className="text-muted-foreground/30">&middot;</span>
                    <span className="text-[11px] text-muted-foreground">
                      {formatShortDate(s.last_activity_at)}
                    </span>
                  </div>

                  {/* Delete button */}
                  <button
                    onClick={(e) => handleDelete(s.session_id, e)}
                    className="absolute top-2.5 right-2 opacity-0 group-hover:opacity-100 w-5 h-5 rounded flex items-center justify-center text-muted-foreground hover:text-destructive hover:bg-destructive/10 transition-all"
                    title="Delete session"
                  >
                    <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
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
      <div className="border-t border-border px-3 py-2">
        <p className="text-[10px] text-muted-foreground/50 text-center">
          {sessions?.length ?? 0} session{(sessions?.length ?? 0) !== 1 ? "s" : ""}
        </p>
      </div>
      {dialog}
    </div>
  );
}
