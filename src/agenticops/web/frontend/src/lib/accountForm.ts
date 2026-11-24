/** The account form's request body (2026-11-09: a region edit sent `credentials: {role_arn}`, the API replaced the
 *  stored credentials with it, and the account's key pair was lost).
 *
 *  The API merges an edit into what is stored (credentials/store.merge_credentials): a secret left out or empty is
 *  kept — the form never sees one, the API redacts them — a plain field sent as "" is deleted, and a field not sent is
 *  kept (account_id in assume-role mode, kubeconfigs). Removing the stored secrets is its own flag, `clear_secrets`. */

export type AccountFormMethod = "assume_role" | "static_keys";

export interface AccountFormField {
  key: string;
  type?: string;
}

/** What the API shows for a stored secret (web/schemas.AccountResponse). */
export const REDACTED = "***REDACTED***";

/** The assume-role inputs: the role, and an optional base key pair (cross-partition). */
const ASSUME_ROLE_FIELDS: AccountFormField[] = [
  { key: "role_arn" }, { key: "external_id" }, { key: "access_key_id" }, { key: "secret_access_key" },
];

/** A secret field, by the backend's rule (credentials/store.is_sensitive_key). */
export function isSecretField(key: string): boolean {
  return /secret|key|token|password/i.test(key);
}

/** True when the account stores secrets: the API returned at least one value redacted. */
export function hasStoredSecrets(credentials: Record<string, unknown> | undefined | null): boolean {
  return Object.values(credentials ?? {}).some((v) => v === REDACTED);
}

/** The `credentials` to send. A new account: the filled fields only. An edit: also every plain field of this mode
 *  that is empty, as "" (deleted); in access-keys mode the role too — that mode assumes no role. A secret is sent only
 *  when typed, in either case. `fields` = the provider's access-keys fields. */
export function buildAccountCredentials({ method, fields, values, isEdit }: {
  method: AccountFormMethod;
  fields: AccountFormField[];
  values: Record<string, string>;
  isEdit: boolean;
}): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  if (isEdit && method === "static_keys") {
    out.role_arn = "";
    out.external_id = "";
  }
  for (const f of method === "assume_role" ? ASSUME_ROLE_FIELDS : fields) {
    const val = values[f.key]?.trim();
    if (val) {
      out[f.key] = f.key === "service_account_key" ? JSON.parse(val) : val;
    } else if (isEdit && !isSecretField(f.key)) {
      out[f.key] = "";
    }
  }
  return out;
}
