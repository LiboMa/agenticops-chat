import { describe, it, expect } from "vitest";
import { buildAccountCredentials, hasStoredSecrets, isSecretField } from "@/lib/accountForm";

// 2026-11-09: a region edit sent `credentials: {role_arn}` and the API replaced the stored credentials with it — the
// account's key pair was lost. The API now merges an edit (credentials/store.merge_credentials): a secret left out is
// kept, a plain field sent as "" is deleted, a field not sent is kept. These cases pin what the form sends.
const AWS = [{ key: "access_key_id" }, { key: "secret_access_key", type: "password" }, { key: "account_id" }];
const GCP = [{ key: "project_id" }, { key: "service_account_key", type: "textarea" }];
const ROLE = "arn:aws:iam::111122223333:role/AgenticOpsRole";

describe("buildAccountCredentials — editing", () => {
  it("sends no key when none was typed, and nothing the mode has no input for", () => {
    expect(buildAccountCredentials({
      method: "assume_role", fields: AWS, isEdit: true,
      values: { role_arn: ROLE, external_id: "ext-1", account_id: "111122223333", kubeconfigs: "{}" },
    })).toEqual({ role_arn: ROLE, external_id: "ext-1" });
  });

  it("sends a cleared plain field as empty, so the API deletes it", () => {
    expect(buildAccountCredentials({
      method: "assume_role", fields: AWS, isEdit: true, values: { role_arn: ROLE, external_id: "" },
    })).toEqual({ role_arn: ROLE, external_id: "" });
  });

  it("sends a typed key", () => {
    expect(buildAccountCredentials({
      method: "assume_role", fields: AWS, isEdit: true,
      values: { role_arn: ROLE, access_key_id: "AKIANEW", secret_access_key: " new-secret " },
    })).toEqual({ role_arn: ROLE, external_id: "", access_key_id: "AKIANEW", secret_access_key: "new-secret" });
  });

  it("access keys only: no role, the provider's plain fields, keys only when typed", () => {
    expect(buildAccountCredentials({
      method: "static_keys", fields: AWS, isEdit: true,
      values: { role_arn: ROLE, access_key_id: "", secret_access_key: "", account_id: "111122223333" },
    })).toEqual({ role_arn: "", external_id: "", account_id: "111122223333" });
  });
});

describe("buildAccountCredentials — a new account", () => {
  it("sends only the filled fields, as before", () => {
    expect(buildAccountCredentials({
      method: "assume_role", fields: AWS, isEdit: false,
      values: { role_arn: ROLE, external_id: "", access_key_id: "AKIA", secret_access_key: "S" },
    })).toEqual({ role_arn: ROLE, access_key_id: "AKIA", secret_access_key: "S" });
    expect(buildAccountCredentials({
      method: "static_keys", fields: AWS, isEdit: false,
      values: { access_key_id: " AKIA ", secret_access_key: "S", account_id: "", role_arn: ROLE },
    })).toEqual({ access_key_id: "AKIA", secret_access_key: "S" });
  });

  it("parses a service account key", () => {
    expect(buildAccountCredentials({
      method: "static_keys", fields: GCP, isEdit: false,
      values: { project_id: "p", service_account_key: '{"type": "service_account"}' },
    })).toEqual({ project_id: "p", service_account_key: { type: "service_account" } });
  });
});

describe("hasStoredSecrets", () => {
  it("is true when the API redacted a stored value", () => {
    expect(hasStoredSecrets({ role_arn: ROLE, _encrypted: "***REDACTED***" })).toBe(true);
    expect(hasStoredSecrets({ role_arn: ROLE })).toBe(false);
    expect(hasStoredSecrets(undefined)).toBe(false);
  });
});

describe("isSecretField", () => {
  it("follows the backend's rule (credentials/store.is_sensitive_key)", () => {
    for (const k of ["access_key_id", "secret_access_key", "client_secret", "service_account_key",
                     "access_key_secret", "session_token", "password"]) {
      expect(isSecretField(k)).toBe(true);
    }
    for (const k of ["role_arn", "external_id", "account_id", "tenant_id", "client_id", "subscription_id",
                     "project_id"]) {
      expect(isSecretField(k)).toBe(false);
    }
  });
});
