import { useChatSessions, useCreateChatSession, useDeleteChatSession } from "@/hooks/useChatSessions";
import { formatShortDate } from "@/lib/formatDate";

interface Props {
  selectedId: string | null;
  onSelect: (sessionId: string) => void;
}

export function SessionList({ selectedId, onSelect }: Props) {
  const { data: sessions, isLoading } = useChatSessions();
  const createMut = useCreateChatSession();
  const deleteMut = useDeleteChatSession();

  const handleNew = async () => {
    const s = await createMut.mutateAsync(undefined);
    onSelect(s.session_id);
  };

  const handleDelete = async (sessionId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (!window.confirm("Delete this chat session?")) return;
    await deleteMut.mutateAsync(sessionId);
    if (selectedId === sessionId && sessions && sessions.length > 1) {
      const next = sessions.find((s) => s.session_id !== sessionId);
      if (next) onSelect(next.session_id);
    }
  };

  return (
    <div className="w-56 flex-shrink-0 border-r border-slate-200 flex flex-col bg-slate-50">
      <div className="p-3 border-b border-slate-200">
        <button
          onClick={handleNew}
          disabled={createMut.isPending}
          className="w-full px-3 py-2 bg-primary-600 hover:bg-primary-700 text-white text-sm font-medium rounded-lg transition-colors disabled:opacity-50"
        >
          + New Chat
        </button>
      </div>
      <div className="flex-1 overflow-y-auto">
        {isLoading ? (
          <p className="p-3 text-xs text-slate-400">Loading...</p>
        ) : !sessions || sessions.length === 0 ? (
          <p className="p-3 text-xs text-slate-400">No sessions yet</p>
        ) : (
          <div className="p-1 space-y-0.5">
            {sessions.map((s) => (
              <div
                key={s.session_id}
                onClick={() => onSelect(s.session_id)}
                className={`group relative px-3 py-2.5 rounded-lg cursor-pointer transition-colors ${
                  selectedId === s.session_id
                    ? "bg-primary-50 text-primary-700 border border-primary-200"
                    : "text-slate-600 hover:bg-slate-100"
                }`}
              >
                <p className="text-sm font-medium truncate pr-5">{s.name}</p>
                <p className="text-xs text-slate-400 mt-0.5">
                  {s.message_count} msgs &middot; {formatShortDate(s.last_activity_at)}
                </p>
                <button
                  onClick={(e) => handleDelete(s.session_id, e)}
                  className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 text-slate-400 hover:text-red-500 transition-opacity"
                >
                  <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
