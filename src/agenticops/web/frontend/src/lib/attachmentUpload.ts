// Upload-on-attach (2026-11-07): a picked, dropped or pasted file is uploaded at once — POST /api/chat/attachments,
// one file per request, three at a time, with progress — then polled until the server has processed it. A message
// is sent with the ids of the uploads that finished (ready, or failed: the model is told why it cannot read it).
import { getAuthToken } from "@/api/client";
import type { MessageAttachment } from "@/api/types";
import type { AttachmentKind } from "@/lib/attachments";

export type UploadState = "queued" | "uploading" | "processing" | "ready" | "failed";

export interface UploadItem {
  localId: string;
  file?: File;            // absent for an upload restored from a draft
  name: string;
  size: number;
  kind?: AttachmentKind;
  serverId?: string;
  progress: number;       // 0–100, upload bytes
  state: UploadState;
  reason?: string;        // a server code (file_too_large, encrypted, …) or network / timeout
  meta?: Record<string, unknown>;
}

/** The slice of XMLHttpRequest the queue uses (tests give a fake). */
export interface XhrLike {
  open(method: string, url: string): void;
  setRequestHeader(name: string, value: string): void;
  send(body: unknown): void;
  abort(): void;
  status: number;
  responseText: string;
  upload: { onprogress: ((e: { loaded: number; total: number; lengthComputable: boolean }) => void) | null };
  onload: (() => void) | null;
  onerror: (() => void) | null;
  onabort: (() => void) | null;
}

export type FetchJson = (path: string, init?: { method?: string }) => Promise<{ status: number; body: any }>;

export interface UploadQueueOptions {
  concurrency?: number;
  token?: () => string | null;
  onChange?: (items: UploadItem[]) => void;
  xhr?: () => XhrLike;
  fetchJson?: FetchJson;
  pollMs?: number;
  pollTimeoutMs?: number;
  /** a limit refusal (413 / 415 / 422 / 507): the composer refetches the policy, it may have changed */
  onLimitError?: () => void;
}

const LIMIT_STATUSES = new Set([413, 415, 422, 507]);
let seq = 0;

export const defaultFetchJson: FetchJson = async (path, init) => {
  const headers: Record<string, string> = {};
  const token = getAuthToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(`/api${path}`, { method: init?.method ?? "GET", headers });
  const body = res.status === 204 ? null : await res.json().catch(() => null);
  return { status: res.status, body };
};

function codeOf(body: any): string | undefined {
  if (!body || typeof body !== "object") return undefined;
  return body.code ?? (typeof body.detail === "object" ? body.detail?.code : undefined);
}

export class UploadQueue {
  private list: UploadItem[] = [];
  private live = new Map<string, XhrLike>();
  private listeners = new Set<(items: UploadItem[]) => void>();
  private readonly opts: Required<Omit<UploadQueueOptions, "onLimitError">> & Pick<UploadQueueOptions, "onLimitError">;

  constructor(opts: UploadQueueOptions) {
    this.opts = {
      concurrency: 3, token: getAuthToken, onChange: () => {}, xhr: () => new XMLHttpRequest() as unknown as XhrLike,
      fetchJson: defaultFetchJson, pollMs: 1000, pollTimeoutMs: 130_000, ...opts,
    };
  }

  items(): UploadItem[] { return this.list.slice(); }

  /** ids to send: every upload the server has finished with (a failed one tells the model why it is unreadable) */
  readyIds(): string[] {
    return this.list.filter((i) => i.serverId && (i.state === "ready" || i.state === "failed")).map((i) => i.serverId!);
  }

  busy(): boolean { return this.list.some((i) => i.state === "queued" || i.state === "uploading" || i.state === "processing"); }

  add(files: File[]): void {
    for (const f of files) {
      seq += 1;
      this.list.push({ localId: `up-${seq}`, file: f, name: f.name, size: f.size, progress: 0, state: "queued" });
    }
    this.emit();
    this.pump();
  }

  remove(localId: string): void {
    const item = this.list.find((i) => i.localId === localId);
    if (!item) return;
    this.list = this.list.filter((i) => i.localId !== localId);
    this.live.get(localId)?.abort();
    this.live.delete(localId);
    if (item.serverId) void this.opts.fetchJson(`/chat/attachments/${item.serverId}`, { method: "DELETE" });
    this.emit();
    this.pump();
  }

  retry(localId: string): void {
    const item = this.list.find((i) => i.localId === localId);
    if (!item || item.state !== "failed" || !item.file) return;
    this.patch(localId, { state: "queued", progress: 0, reason: undefined, serverId: undefined });
    this.pump();
  }

  /** Forget everything without deleting on the server — the message that carried them was sent. */
  clear(): void {
    this.live.forEach((x) => { x.onload = x.onerror = x.onabort = null; });
    this.live.clear();
    this.list = [];
    this.emit();
  }

  /** Bring back uploads a draft kept (by server id); one the server no longer has is dropped. */
  async restore(serverIds: string[]): Promise<void> {
    for (const id of serverIds) {
      if (this.list.some((i) => i.serverId === id)) continue;
      const { status, body } = await this.opts.fetchJson(`/chat/attachments/${id}`);
      if (status !== 200 || !body) continue;
      seq += 1;
      const item: UploadItem = { localId: `up-${seq}`, name: body.filename, size: body.size, kind: body.kind,
                                 serverId: id, progress: 100, state: body.status, reason: body.reason ?? undefined,
                                 meta: body.meta };
      this.list.push(item);
      this.emit();
      if (item.state === "processing") void this.poll(item.localId, id);
    }
  }

  /** Follow the items (the composer that shows this queue now); → unsubscribe. */
  listen(fn: (items: UploadItem[]) => void): () => void {
    this.listeners.add(fn);
    return () => { this.listeners.delete(fn); };
  }

  /** Hand the finished items to a send (the tray empties, nothing is deleted); putBack if the send was refused. */
  take(): UploadItem[] {
    const taken = this.list.filter((i) => i.state === "ready" || i.state === "failed");
    this.list = this.list.filter((i) => !taken.includes(i));
    this.emit();
    return taken;
  }

  putBack(items: UploadItem[]): void {
    const have = new Set(this.list.map((i) => i.localId));
    this.list = [...items.filter((i) => !have.has(i.localId)), ...this.list];
    this.emit();
  }

  private emit(): void {
    const items = this.items();
    this.opts.onChange(items);
    this.listeners.forEach((fn) => fn(items));
  }

  private patch(localId: string, changes: Partial<UploadItem>): void {
    let changed = false;
    this.list = this.list.map((i) => (i.localId === localId ? ((changed = true), { ...i, ...changes }) : i));
    if (changed) this.emit();
  }

  private pump(): void {
    const running = this.list.filter((i) => i.state === "uploading").length;
    let slots = this.opts.concurrency - running;
    for (const item of this.list) {
      if (slots <= 0) break;
      if (item.state === "queued" && item.file) {
        slots -= 1;
        this.start(item);
      }
    }
  }

  private start(item: UploadItem): void {
    const xhr = this.opts.xhr();
    this.live.set(item.localId, xhr);
    this.patch(item.localId, { state: "uploading", progress: 0 });
    const done = (changes: Partial<UploadItem>) => {
      this.live.delete(item.localId);
      this.patch(item.localId, changes);
      this.pump();
    };
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable && e.total > 0) this.patch(item.localId, { progress: Math.round((e.loaded / e.total) * 100) });
    };
    xhr.onload = () => {
      let body: any = null;
      try { body = JSON.parse(xhr.responseText); } catch { /* not JSON */ }
      if (xhr.status === 201 && body?.id) {
        const state: UploadState = body.status === "ready" || body.status === "failed" ? body.status : "processing";
        done({ serverId: body.id, kind: body.kind, progress: 100, state, reason: body.reason ?? undefined });
        if (state === "processing") void this.poll(item.localId, body.id);
        return;
      }
      if (LIMIT_STATUSES.has(xhr.status)) this.opts.onLimitError?.();
      done({ state: "failed", reason: codeOf(body) ?? `http_${xhr.status}` });
    };
    xhr.onerror = () => done({ state: "failed", reason: "network" });
    xhr.onabort = () => this.live.delete(item.localId);
    xhr.open("POST", "/api/chat/attachments");
    const token = this.opts.token();
    if (token) xhr.setRequestHeader("Authorization", `Bearer ${token}`);
    const form = new FormData();
    form.append("file", item.file!, item.name);
    xhr.send(form);
  }

  private async poll(localId: string, serverId: string): Promise<void> {
    const deadline = Date.now() + this.opts.pollTimeoutMs;
    while (Date.now() < deadline) {
      await new Promise((r) => setTimeout(r, this.opts.pollMs));
      if (!this.list.some((i) => i.localId === localId)) return;   // removed meanwhile
      const { status, body } = await this.opts.fetchJson(`/chat/attachments/${serverId}`);
      if (status !== 200) {
        this.patch(localId, { state: "failed", reason: codeOf(body) ?? `http_${status}` });
        return;
      }
      if (body.status === "ready" || body.status === "failed") {
        this.patch(localId, { state: body.status, reason: body.reason ?? undefined, kind: body.kind ?? undefined,
                              meta: body.meta });
        return;
      }
    }
    this.patch(localId, { state: "failed", reason: "timeout" });
  }
}

/** The attachments of a message as it is shown before the server's copy arrives (its local preview, by localId). */
export function optimisticAttachments(items: UploadItem[]): (MessageAttachment & { localId: string })[] | undefined {
  if (items.length === 0) return undefined;
  return items.map((i) => ({ id: i.serverId, filename: i.name, size: i.size, kind: i.kind, localId: i.localId }));
}
