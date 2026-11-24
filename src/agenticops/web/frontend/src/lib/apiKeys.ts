import type { ApiKeyRow, UserRole } from "@/api/types";
import { parseApiDate } from "@/lib/formatDate";
import type { isReadOnly } from "@/lib/permissions";

/** «My API keys» and the admin's view (MVP-2.8.0). The server decides scope and who may (services/api_keys);
 *  these only shape what the pages show. */

export type KeyState = "active" | "expired" | "revoked";

/** Revoked wins over expired; a key without an expiry stays active until revoked. */
export function keyState(row: Pick<ApiKeyRow, "is_active" | "expires_at">, now: number): KeyState {
  if (!row.is_active) return "revoked";
  const exp = parseApiDate(row.expires_at);
  return exp && exp.getTime() <= now ? "expired" : "active";
}

/** What a key may do in words: read only, read-write, or — a legacy key from before 2.8.0 — read-write + admin. */
export function scopeKey(permissions: string[]): string {
  if (permissions.includes("admin")) return "apiKeys.scope.admin";
  return permissions.includes("write") ? "apiKeys.scope.write" : "apiKeys.scope.read";
}

type BootLike = Parameters<typeof isReadOnly>[0];

/** A viewer issues read-only keys (the server refuses write: scope_exceeds_role) — in both sign-in modes, since the
 *  server checks the account's own role, not whether sign-in is on (so not `isReadOnly`, which is sign-in-on only). */
export function canChooseWrite(boot: BootLike): boolean {
  return !boot?.user?.read_only;
}

/** The create dialog's expiries, in days; null = never. Default 90. */
export const EXPIRY_CHOICES: (number | null)[] = [30, 90, 365, null];
export const DEFAULT_EXPIRY = 90;

/** A choice in words: «30 天», «1 年» (365 days), «永不过期». */
export function expiryLabel(days: number | null, t: (k: string) => string): string {
  if (days === null) return t("apiKeys.expiry.never");
  if (days === 365) return t("apiKeys.expiry.year");
  return t("apiKeys.expiry.days").replace("{n}", String(days));
}

/** How to use the key — a call to this site with it as the Bearer token. */
export function curlExample(origin: string, key: string): string {
  return `curl -H "Authorization: Bearer ${key}" \\\n  ${origin}/api/health-issues?limit=5`;
}

/** A viewer's keys are read-only — whoever issues them (MVP-2.8.0: an admin issues keys for others too). */
export function writeAllowedForRole(role: UserRole): boolean {
  return role !== "viewer";
}

const DAY = 86_400_000;

/** «更新密钥» starts from what the key was: its access (minus write the person may not have) and its expiry — the same
 *  number of days when that was one of the choices, else the default; a key that never expired stays so. */
export function rotateDefaults(row: Pick<ApiKeyRow, "permissions" | "expires_at" | "created_at">,
                               canWrite: boolean): { write: boolean; expiry: number | null } {
  const write = canWrite && row.permissions.includes("write");
  const exp = parseApiDate(row.expires_at);
  if (!exp) return { write, expiry: null };
  const made = parseApiDate(row.created_at);
  const days = made ? Math.round((exp.getTime() - made.getTime()) / DAY) : NaN;
  return { write, expiry: EXPIRY_CHOICES.includes(days) ? days : DEFAULT_EXPIRY };
}
