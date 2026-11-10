import { describe, expect, it } from "vitest";
import { EXPIRY_CHOICES, canChooseWrite, curlExample, keyState, scopeKey } from "@/lib/apiKeys";

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
