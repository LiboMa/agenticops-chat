import { useInfiniteQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { ChatMessage, ChatMessagesPage } from "@/api/types";

const PAGE_SIZE = 50;

/**
 * Cursor-paginated chat history. Page 0 is the newest PAGE_SIZE messages;
 * fetchNextPage() loads the immediately-older page via the `before` cursor.
 *
 * Pages arrive newest-window-first, each ordered oldest→newest internally.
 * `messages` flattens them into a single chronological array.
 */
export function useChatMessages(sessionId: string | null) {
  const query = useInfiniteQuery({
    queryKey: ["chat-messages", sessionId],
    enabled: !!sessionId,
    initialPageParam: null as number | null,
    queryFn: ({ pageParam }) => {
      const qs = new URLSearchParams({ limit: String(PAGE_SIZE) });
      if (pageParam != null) qs.set("before", String(pageParam));
      return apiFetch<ChatMessagesPage>(`/chat/sessions/${sessionId}/messages?${qs.toString()}`);
    },
    getNextPageParam: (lastPage) => (lastPage.has_more ? lastPage.next_cursor : undefined),
    staleTime: 30_000,
  });

  // pages[0] = newest window, pages[1] = older, ... → reverse page order, keep
  // each page's internal chronological order, to get a single oldest→newest list.
  const messages: ChatMessage[] = (query.data?.pages ?? [])
    .slice()
    .reverse()
    .flatMap((p) => p.messages);

  return {
    messages,
    fetchOlder: query.fetchNextPage,
    hasOlder: query.hasNextPage,
    isFetchingOlder: query.isFetchingNextPage,
    isLoading: query.isLoading,
  };
}

/**
 * Optimistically append a finished assistant turn (and the user message that
 * was just sent) to the newest page in the cache, so the completed message
 * shows without a refetch. Role-agnostic: appends any ChatMessage to the newest
 * page; seeds an initial page if the cache has none yet (e.g. a freshly created
 * session whose history query hasn't loaded).
 */
export function appendMessageToCache(
  qc: ReturnType<typeof useQueryClient>,
  sessionId: string,
  msg: ChatMessage,
) {
  qc.setQueryData<{ pages: ChatMessagesPage[]; pageParams: unknown[] }>(
    ["chat-messages", sessionId],
    (old) => {
      if (!old || old.pages.length === 0) {
        return {
          pages: [{ messages: [msg], has_more: false, next_cursor: null }],
          pageParams: [null],
        };
      }
      const pages = old.pages.slice();
      // pages[0] is the newest window; append to it (it flattens to the bottom).
      pages[0] = { ...pages[0], messages: [...pages[0].messages, msg] };
      return { ...old, pages };
    },
  );
}

/**
 * Optimistic temp ids for messages not yet persisted server-side. Negative +
 * monotonically decreasing so they (a) never collide with real positive ids
 * and (b) never collide with each other (markdown memo + React keys are id-based).
 */
let _tempId = -1;
export function nextTempId(): number {
  return _tempId--;
}
