import { describe, expect, it } from "vitest";
import { MutationObserver, QueryClient } from "@tanstack/react-query";
import { createApiKeyOptions, rotateApiKeyOptions } from "@/hooks/useApiKeys";
import { createUserKeyOptions, createUserOptions, resetPasswordOptions, rotateUserKeyOptions } from "@/hooks/useUsers";

/** A secret shown once — a new API key, a new user's or a reset password — is forgotten when its dialog closes:
 *  the page calls `reset()`, and the mutation cache must drop the result then, not keep it for TanStack's default
 *  5 minutes (MVP-2.8.0 final review: the full key was still in the cache after reset). */
async function leftAfterReset(options: object, secret: unknown): Promise<string> {
  const qc = new QueryClient();
  const observer = new MutationObserver(qc, { ...options, mutationFn: async () => secret } as never);
  await observer.mutate({} as never);
  observer.reset();
  await new Promise((r) => setTimeout(r, 20));
  return JSON.stringify(qc.getMutationCache().getAll().map((m) => m.state.data));
}

describe("a secret shown once leaves the cache with its dialog", () => {
  it("a new API key", async () => {
    const qc = new QueryClient();
    expect(await leftAfterReset(createApiKeyOptions(qc), { key: "aiops_SECRET_full_key" })).not.toContain("SECRET");
  });
  it("a key's new value after an update", async () => {
    const qc = new QueryClient();
    expect(await leftAfterReset(rotateApiKeyOptions(qc), { key: "aiops_SECRET_rotated" })).not.toContain("SECRET");
  });
  it("a new user's password and a reset password", async () => {
    const qc = new QueryClient();
    expect(await leftAfterReset(createUserOptions(qc), { user: {}, password: "pw-SECRET" })).not.toContain("SECRET");
    expect(await leftAfterReset(resetPasswordOptions(qc), { password: "pw-SECRET" })).not.toContain("SECRET");
  });
  it("a key an admin issued or updated for someone", async () => {
    const qc = new QueryClient();
    expect(await leftAfterReset(createUserKeyOptions(qc), { key: "aiops_SECRET_for_you" })).not.toContain("SECRET");
    expect(await leftAfterReset(rotateUserKeyOptions(qc), { key: "aiops_SECRET_rotated_for_you" })).not.toContain("SECRET");
  });
});
