import { QueryClient } from "@tanstack/react-query";

/** The app's one query cache — a module so non-component code (preference writes on pagehide) can reach it. */
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});
