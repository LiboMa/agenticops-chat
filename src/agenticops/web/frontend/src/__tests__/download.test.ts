import { describe, it, expect, vi, beforeEach } from "vitest";
import { filenameFromDisposition } from "@/lib/download";
import { apiDownload, ApiError } from "@/api/client";

beforeEach(() => {
  (globalThis as any).localStorage = {
    store: { aiops_token: "tok" } as Record<string, string>,
    getItem(k: string) { return this.store[k] ?? null; }, setItem(k: string, v: string) { this.store[k] = v; },
    removeItem(k: string) { delete this.store[k]; },
  };
});

describe("downloads (MVP-2.7.0 S6)", () => {
  it("reads the file name from Content-Disposition", () => {
    expect(filenameFromDisposition('attachment; filename="AgenticOps_R3_v1_zh-en.html"')).toBe("AgenticOps_R3_v1_zh-en.html");
    expect(filenameFromDisposition("attachment; filename*=UTF-8''%E6%97%A5%E6%8A%A5.html")).toBe("日报.html");
    expect(filenameFromDisposition(null)).toBeNull();
    expect(filenameFromDisposition("inline")).toBeNull();
  });
  it("downloads with the Bearer header — never a token in the URL", async () => {
    const fetchMock = vi.fn(async (_url: string, _init: RequestInit) => new Response("<html></html>", {
      status: 200, headers: { "Content-Disposition": 'attachment; filename="r.html"', "Content-Type": "text/html" } }));
    vi.stubGlobal("fetch", fetchMock);
    const out = await apiDownload("/reports/3/export?version=1&language=en");
    expect(out.filename).toBe("r.html");
    expect(await out.blob.text()).toBe("<html></html>");
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/reports/3/export?version=1&language=en");
    expect(url).not.toContain("tok");
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer tok");
  });
  it("a refused download throws with the server's code", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(
      JSON.stringify({ detail: { detail: "The zh rendering is missing", code: "rendering_not_ready" } }), { status: 409 })));
    const err = await apiDownload("/reports/3/export?version=1&language=zh").catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(409);
    expect(err.code).toBe("rendering_not_ready");
  });
});

describe("apiFetch keeps a UiError's code (S6)", () => {
  it("a {detail, code} body gives the message and the code", async () => {
    const { apiFetch } = await import("@/api/client");
    vi.stubGlobal("fetch", vi.fn(async () => new Response(
      JSON.stringify({ detail: { detail: "still sending", code: "publish_in_flight" } }), { status: 409 })));
    const err = (await apiFetch("/reports/1/publish", { method: "POST" }).catch((e) => e)) as { status: number; message: string; code?: string };
    expect([err.status, err.message, err.code]).toEqual([409, "still sending", "publish_in_flight"]);
  });
});
