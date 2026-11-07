// Attachment images in the browser (2026-11-07): fetched with the Bearer header (never a token in a URL), kept as
// object URLs in one module cache (≤ 4 fetches at a time, the oldest released past 200), plus the local previews of
// files the composer just sent, so a sent message shows its pictures before the server's copies load.
import { useEffect, useState } from "react";
import { getAuthToken } from "@/api/client";

export type BlobVariant = "thumb" | "preview" | "original" | `page-${number}`;

const MAX_ENTRIES = 200;
const MAX_PARALLEL = 4;
const cache = new Map<string, Promise<string>>();
const resolved = new Map<string, string>();
let running = 0;
const waiting: (() => void)[] = [];

async function slot<T>(fn: () => Promise<T>): Promise<T> {
  if (running >= MAX_PARALLEL) await new Promise<void>((r) => waiting.push(r));
  running += 1;
  try {
    return await fn();
  } finally {
    running -= 1;
    waiting.shift()?.();
  }
}

function evict(): void {
  while (cache.size > MAX_ENTRIES) {
    const oldest = cache.keys().next().value as string;
    cache.delete(oldest);
    const url = resolved.get(oldest);
    if (url) URL.revokeObjectURL(url);
    resolved.delete(oldest);
  }
}

export function attachmentBlobUrl(id: string, variant: BlobVariant): Promise<string> {
  const key = `${id}:${variant}`;
  let p = cache.get(key);
  if (!p) {
    p = slot(async () => {
      const headers: Record<string, string> = {};
      const token = getAuthToken();
      if (token) headers.Authorization = `Bearer ${token}`;
      const res = await fetch(`/api/chat/attachments/${id}/content?variant=${variant}`, { headers });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const url = URL.createObjectURL(await res.blob());
      resolved.set(key, url);
      return url;
    });
    p.catch(() => cache.delete(key));   // a failure is not cached: the next view tries again
    cache.set(key, p);
    evict();
  }
  return p;
}

export function useAttachmentBlob(id: string | undefined, variant: BlobVariant): { url?: string; error?: string } {
  const [state, setState] = useState<{ url?: string; error?: string }>(() =>
    id ? { url: resolved.get(`${id}:${variant}`) } : {});
  useEffect(() => {
    if (!id) return;
    let live = true;
    attachmentBlobUrl(id, variant).then((url) => { if (live) setState({ url }); },
                                        (e: Error) => { if (live) setState({ error: e.message }); });
    return () => { live = false; };
  }, [id, variant]);
  return state;
}

// ── local previews (the composer's own files) ────────────────────────────────
const local = new Map<string, string>();

/** An object URL for a local image, kept by the composer's item id (released past MAX_ENTRIES). */
export function localPreviewUrl(localId: string, file: File): string {
  let url = local.get(localId);
  if (!url) {
    url = URL.createObjectURL(file);
    local.set(localId, url);
    while (local.size > MAX_ENTRIES) {
      const [oldId, oldUrl] = local.entries().next().value as [string, string];
      URL.revokeObjectURL(oldUrl);
      local.delete(oldId);
    }
  }
  return url;
}

export function localPreview(localId: string | undefined): string | undefined {
  return localId ? local.get(localId) : undefined;
}
