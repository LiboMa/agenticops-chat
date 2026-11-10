import { describe, expect, it } from "vitest";
import { EXPIRY_CHOICES, canChooseWrite, curlExample, expiryLabel, keyState, rotateDefaults, scopeKey, writeAllowedForRole } from "@/lib/apiKeys";
import zh from "@/locales/zh.json";

const NOW = Date.parse("2026-11-10T12:00:00Z");
const key = (over: Record<string, unknown> = {}) => ({
  id: 1, name: "k", key_prefix: "aiops_7Hf2kL", permissions: ["read"], is_active: true,
  last_used_at: null, expires_at: null, created_at: "2026-11-10T01:00:00", ...over,
});

/** «My API keys» (MVP-2.8.0). */
describe("keyState — active, expired, revoked", () => {
  it("revoked wins over expired; no expiry is active", () => {
    expect(keyState(key(), NOW)).toBe("active");
    expect(keyState(key({ expires_at: "2026-12-01T00:00:00" }), NOW)).toBe("active");
    expect(keyState(key({ expires_at: "2026-11-09T00:00:00" }), NOW)).toBe("expired");
    expect(keyState(key({ is_active: false, expires_at: "2026-11-09T00:00:00" }), NOW)).toBe("revoked");
  });
});

describe("scopeKey — what a key may do, in words", () => {
  it("read, read-write, and a legacy key that carries admin", () => {
    expect(scopeKey(["read"])).toBe("apiKeys.scope.read");
    expect(scopeKey(["read", "write"])).toBe("apiKeys.scope.write");
    expect(scopeKey(["read", "write", "admin"])).toBe("apiKeys.scope.admin");
  });
});

describe("canChooseWrite — a viewer issues read-only keys", () => {
  it("writers and admins may; a viewer may not; sign-in off: everyone may", () => {
    expect(canChooseWrite({ auth_enabled: true, user: { read_only: false } })).toBe(true);
    expect(canChooseWrite({ auth_enabled: true, user: { read_only: true } })).toBe(false);
    expect(canChooseWrite({ auth_enabled: false, user: null })).toBe(true);
    // the server checks the account's own role in both sign-in modes (services/api_keys.create_key)
    expect(canChooseWrite({ auth_enabled: false, user: { read_only: true } })).toBe(false);
  });
});

describe("the create dialog's choices and the usage example", () => {
  it("30 / 90 / 365 days or never", () => {
    expect(EXPIRY_CHOICES).toEqual([30, 90, 365, null]);
  });
  it("the example calls this site with the key as a Bearer token", () => {
    const ex = curlExample("https://ops.example.com", "aiops_abc");
    expect(ex).toContain("Authorization: Bearer aiops_abc");
    expect(ex).toContain("https://ops.example.com/api/health-issues?limit=5");
  });
});

describe("the expiry choices in words (spec: 30 天 / 90 天 / 1 年 / 永不过期)", () => {
  it("365 days reads as one year, null as never", () => {
    const t = (k: string) => (zh as Record<string, string>)[k] ?? k;
    expect(EXPIRY_CHOICES.map((d) => expiryLabel(d, t))).toEqual(["30 天", "90 天", "1 年", "永不过期"]);
  });
});

describe("updating a key starts from what it was (MVP-2.8.0 user management)", () => {
  const row = (over: Record<string, unknown>) => key({ created_at: "2026-11-01T00:00:00", ...over });
  it("keeps the access, minus write the person may not have", () => {
    expect(rotateDefaults(row({ permissions: ["read", "write"], expires_at: null }), true)).toEqual({ write: true, expiry: null });
    expect(rotateDefaults(row({ permissions: ["read", "write"], expires_at: null }), false)).toEqual({ write: false, expiry: null });
    expect(rotateDefaults(row({ permissions: ["read"], expires_at: null }), true)).toEqual({ write: false, expiry: null });
  });
  it("keeps the expiry when it was one of the choices, else the default 90 days", () => {
    expect(rotateDefaults(row({ expires_at: "2026-12-01T00:00:00" }), true).expiry).toBe(30);
    expect(rotateDefaults(row({ expires_at: "2027-01-30T00:00:00" }), true).expiry).toBe(90);
    expect(rotateDefaults(row({ expires_at: "2027-11-01T00:00:00" }), true).expiry).toBe(365);
    expect(rotateDefaults(row({ expires_at: "2026-12-18T00:00:00" }), true).expiry).toBe(90);   // 47 days
  });
  it("a viewer's keys are read-only", () => {
    expect(writeAllowedForRole("viewer")).toBe(false);
    expect(writeAllowedForRole("writer")).toBe(true);
    expect(writeAllowedForRole("admin")).toBe(true);
  });
});
