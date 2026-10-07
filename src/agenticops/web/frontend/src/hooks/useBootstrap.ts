import { useQuery } from "@tanstack/react-query";
import { apiFetch, getAuthToken } from "@/api/client";
import { currentUserId, type Home } from "@/lib/home";

export interface UiPreferences {
  revision: number;
  locale: "zh" | "en";
  home: Home;
  last_route: string | null;
  nav_groups_open: ("tools" | "administration")[];
}

/** GET /api/ui/bootstrap (contract workspace-ui-1 + the 2.7.0 user / auth_enabled / version fields). */
export interface UiBootstrap {
  contract_version: string;
  deployment_id: string;
  user_id: number;
  locale: "zh" | "en";
  features: Record<string, boolean>;
  upload_policy: {
    max_files: number; image_max_bytes: number; document_max_bytes: number; text_fallback_max_bytes: number;
    image_extensions: string[]; document_extensions: string[]; text_extensions: string[];
  };
  preferences: UiPreferences;
  user: { id: number; email: string; name: string | null; is_admin: boolean };
  auth_enabled: boolean;
  version: string;
}

/** Keyed by the signed-in user, so signing in as someone else never shows the previous user's preferences. */
export const bootstrapKey = () => ["ui-bootstrap", currentUserId()] as const;

export function useBootstrap() {
  return useQuery({
    queryKey: bootstrapKey(),
    queryFn: () => apiFetch<UiBootstrap>("/ui/bootstrap"),
    enabled: !!getAuthToken(),
    staleTime: 5 * 60_000,
    retry: false,
  });
}
