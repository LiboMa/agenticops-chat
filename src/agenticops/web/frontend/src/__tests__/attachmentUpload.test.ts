import { describe, it, expect, vi } from "vitest";
import { UploadQueue, type UploadItem, type XhrLike } from "@/lib/attachmentUpload";

class FakeXhr implements XhrLike {
  static made: FakeXhr[] = [];
  method = ""; url = ""; headers: Record<string, string> = {}; body: unknown = null; aborted = false; sent = false;
  status = 0; responseText = "";
  upload: { onprogress: ((e: { loaded: number; total: number; lengthComputable: boolean }) => void) | null } =
    { onprogress: null };
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onabort: (() => void) | null = null;
  constructor() { FakeXhr.made.push(this); }
  open(method: string, url: string) { this.method = method; this.url = url; }
  setRequestHeader(k: string, v: string) { this.headers[k] = v; }
  send(body: unknown) { this.body = body; this.sent = true; }
  abort() { this.aborted = true; this.onabort?.(); }
  respond(status: number, body: unknown) { this.status = status; this.responseText = JSON.stringify(body); this.onload?.(); }
}

const tick = () => new Promise((r) => setTimeout(r, 15));
const file = (name: string, size = 10) => new File([new Uint8Array(size)], name);

function setup(states: Record<string, { status: number; body: unknown }[]> = {}) {
  FakeXhr.made = [];
  const calls: { path: string; method: string }[] = [];
  const snapshots: UploadItem[][] = [];
  const onLimitError = vi.fn();
  const fetchJson = vi.fn(async (path: string, init?: { method?: string }) => {
    calls.push({ path, method: init?.method ?? "GET" });
    const id = path.split("/").pop() as string;
    const queue = states[id];
    const next = queue && queue.length > 1 ? queue.shift()! : queue?.[0];
    return next ?? { status: 200, body: { id, status: "ready", filename: "x", size: 1, kind: "text" } };
  });
  const q = new UploadQueue({ token: () => "tok", onChange: (items) => snapshots.push(items),
                               xhr: () => new FakeXhr(), fetchJson, pollMs: 1, onLimitError });
  return { q, calls, snapshots, onLimitError, fetchJson };
}

describe("UploadQueue (2026-11-07: upload on attach, then poll until processed)", () => {
  it("concurrency is 3", async () => {
    const { q } = setup();
    q.add(["a.txt", "b.txt", "c.txt", "d.txt", "e.txt"].map((n) => file(n)));
    expect(FakeXhr.made.filter((x) => x.sent)).toHaveLength(3);
    expect(FakeXhr.made[0].url).toBe("/api/chat/attachments");
    expect(FakeXhr.made[0].headers.Authorization).toBe("Bearer tok");
    FakeXhr.made[0].respond(201, { id: "s1", status: "processing", filename: "a.txt", size: 10, kind: "text" });
    expect(FakeXhr.made.filter((x) => x.sent)).toHaveLength(4);
    expect(q.items().map((i) => i.state)).toEqual(["processing", "uploading", "uploading", "uploading", "queued"]);
  });

  it("reports progress, then polls processing until ready", async () => {
    const { q, calls } = setup({ s1: [{ status: 200, body: { id: "s1", status: "processing" } },
                                      { status: 200, body: { id: "s1", status: "ready", filename: "a.pdf", size: 10,
                                                             kind: "pdf", meta: { pages: 2 } } }] });
    q.add([file("a.pdf")]);
    FakeXhr.made[0].upload.onprogress?.({ loaded: 50, total: 100, lengthComputable: true });
    expect(q.items()[0]).toMatchObject({ state: "uploading", progress: 50 });
    expect(q.busy()).toBe(true);
    FakeXhr.made[0].respond(201, { id: "s1", status: "processing", filename: "a.pdf", size: 10, kind: "pdf" });
    await tick();
    expect(q.items()[0]).toMatchObject({ state: "ready", serverId: "s1", progress: 100, kind: "pdf" });
    expect(q.readyIds()).toEqual(["s1"]);
    expect(q.busy()).toBe(false);
    expect(calls.filter((c) => c.path === "/chat/attachments/s1").length).toBeGreaterThanOrEqual(2);
  });

  it("a failed processing result is kept with its reason and can still be sent", async () => {
    const { q } = setup({ s1: [{ status: 200, body: { id: "s1", status: "failed", reason: "encrypted" } }] });
    q.add([file("locked.pdf")]);
    FakeXhr.made[0].respond(201, { id: "s1", status: "processing", filename: "locked.pdf", size: 10, kind: "pdf" });
    await tick();
    expect(q.items()[0]).toMatchObject({ state: "failed", reason: "encrypted", serverId: "s1" });
    expect(q.readyIds()).toEqual(["s1"]);
  });

  it("remove aborts and deletes", async () => {
    const { q, calls } = setup();
    q.add([file("a.txt"), file("b.txt")]);
    const [a, b] = q.items();
    q.remove(a.localId);
    expect(FakeXhr.made[0].aborted).toBe(true);
    FakeXhr.made[1].respond(201, { id: "s2", status: "processing", filename: "b.txt", size: 10, kind: "text" });
    await tick();
    q.remove(b.localId);
    await tick();
    expect(calls).toContainEqual({ path: "/chat/attachments/s2", method: "DELETE" });
    expect(q.items()).toEqual([]);
  });

  it("413 invalidates bootstrap and keeps the server's code as the reason", () => {
    const { q, onLimitError } = setup();
    q.add([file("big.pdf")]);
    FakeXhr.made[0].respond(413, { detail: "too big", code: "file_too_large" });
    expect(q.items()[0]).toMatchObject({ state: "failed", reason: "file_too_large" });
    expect(onLimitError).toHaveBeenCalledTimes(1);
    expect(q.readyIds()).toEqual([]);
  });

  it("retry uploads a failed file again", () => {
    const { q } = setup();
    q.add([file("a.txt")]);
    FakeXhr.made[0].onerror?.();
    expect(q.items()[0]).toMatchObject({ state: "failed", reason: "network" });
    q.retry(q.items()[0].localId);
    expect(FakeXhr.made).toHaveLength(2);
    expect(q.items()[0].state).toBe("uploading");
  });

  it("restore drops missing ids", async () => {
    const { q } = setup({ gone: [{ status: 404, body: { code: "not_found" } }],
                          kept: [{ status: 200, body: { id: "kept", status: "ready", filename: "r.xlsx", size: 99,
                                                        kind: "office" } }] });
    await q.restore(["gone", "kept"]);
    expect(q.items().map((i) => [i.serverId, i.name, i.size, i.state])).toEqual([["kept", "r.xlsx", 99, "ready"]]);
    expect(q.readyIds()).toEqual(["kept"]);
  });

  it("clear forgets every item without deleting on the server (they were sent)", async () => {
    const { q, calls } = setup();
    q.add([file("a.txt")]);
    FakeXhr.made[0].respond(201, { id: "s1", status: "ready", filename: "a.txt", size: 10, kind: "text" });
    await tick();
    q.clear();
    expect(q.items()).toEqual([]);
    expect(calls.some((c) => c.method === "DELETE")).toBe(false);
  });
});
