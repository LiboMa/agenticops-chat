import { useQuery } from "@tanstack/react-query";
import { apiFetch, getAuthToken } from "@/api/client";
import { currentUserId, type Home } from "@/lib/home";
import { canViewSettings, isReadOnly } from "@/lib/permissions";
import type { UploadPolicy } from "@/lib/attachments";

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
  /** S6: the export formats this server can produce (html always) */
  report_export_formats?: string[];
  /** 2026-11-07: the upload limits in force (yaml defaults + admin overrides) — lib/attachments */
  upload_policy: UploadPolicy;
  preferences: UiPreferences;
  /** read_only: a viewer account — the server refuses its writes, the UI offers none */
  user: { id: number; email: string; name: string | null; is_admin: boolean; read_only?: boolean; can_view_settings?: boolean };
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

/** A viewer (read-only account): hide write controls. False while the bootstrap loads — the server still refuses. */
export function useReadOnly(): boolean {
  return isReadOnly(useBootstrap().data);
}

/** Whether Settings is offered (writers; a viewer only with settings_read — then read-only). */
export function useCanViewSettings(): boolean {
  return canViewSettings(useBootstrap().data);
}
