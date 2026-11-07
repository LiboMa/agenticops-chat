// Chat attachment rules (2026-11-07): they come from the server — GET /api/ui/bootstrap `upload_policy`, the upload
// limits in force (settings.yaml defaults + the admins' overrides, chat/upload_config) — so the composer and the
// server never disagree. FALLBACK_POLICY mirrors the defaults for the moment before bootstrap loads.

export type AttachmentKind = "image" | "pdf" | "office" | "text";

export interface UploadPolicy {
  max_files: number;
  max_file_bytes: number;
  max_total_bytes: number;
  /** accepted extensions, lowercase with the dot; "" = a file with no extension */
  extensions: string[];
  kinds: Record<string, AttachmentKind>;
}

const KB = 1024;
const MB = 1024 * 1024;

const KINDS: Record<string, AttachmentKind> = {
  ".png": "image", ".jpg": "image", ".jpeg": "image", ".gif": "image", ".webp": "image", ".bmp": "image",
  ".tif": "image", ".tiff": "image", ".heic": "image", ".heif": "image", ".pdf": "pdf",
  ".docx": "office", ".xlsx": "office", ".xlsm": "office", ".pptx": "office", ".doc": "office", ".xls": "office",
  ...Object.fromEntries([".txt", ".log", ".md", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".sh",
                         ".py", ".js", ".ts", ".csv", ".tsv", ".xml", ".html", ".htm", ".tf", ".hcl", ""]
    .map((e) => [e, "text" as AttachmentKind])),
};

export const FALLBACK_POLICY: UploadPolicy = {
  max_files: 20, max_file_bytes: 50 * MB, max_total_bytes: 200 * MB,
  extensions: Object.keys(KINDS).sort(), kinds: KINDS,
};

export interface AttachmentRules {
  max: number;
  maxFileBytes: number;
  maxTotalBytes: number;
  /** for <input accept="…">; "" (no filter) when files without an extension are allowed — a filter would hide them */
  accept: string;
  accepted(name: string): boolean;
  kindOf(name: string): AttachmentKind;
}

/** The extension the server keys on: lowercase, with the dot; "" when there is none (as Python's suffix). */
export function extOf(name: string): string {
  const base = name.split(/[\\/]/).pop() ?? "";
  const i = base.lastIndexOf(".");
  return i > 0 && i < base.length - 1 ? base.slice(i).toLowerCase() : "";
}

export function attachmentRules(policy: UploadPolicy): AttachmentRules {
  const allowed = new Set(policy.extensions.map((e) => e.toLowerCase()));
  return {
    max: policy.max_files,
    maxFileBytes: policy.max_file_bytes,
    maxTotalBytes: policy.max_total_bytes,
    accept: allowed.has("") ? "" : [...allowed].sort().join(","),
    accepted: (name) => allowed.has(extOf(name)),
    kindOf: (name) => policy.kinds[extOf(name)] ?? KINDS[extOf(name)] ?? "text",
  };
}

export function humanSize(bytes: number): string {
  if (bytes >= MB) return `${Math.round((bytes / MB) * 10) / 10} MB`.replace(".0 MB", " MB");
  return `${Math.max(1, Math.round(bytes / KB))} KB`;
}

/** Why a file was not attached; the composer words it in the user's language (attachmentErrorText). */
export type AttachmentError = { kind: "type"; name: string } | { kind: "size"; name: string; limit: number }
  | { kind: "count"; limit: number } | { kind: "total"; limit: number };

export function attachmentErrorText(e: AttachmentError, t: (k: string) => string): string {
  const name = "name" in e ? e.name : "";
  const limit = e.kind === "size" || e.kind === "total" ? humanSize(e.limit) : e.kind === "count" ? String(e.limit) : "";
  return t(`chat.attach.${e.kind}`).replace("{name}", name).replace("{limit}", limit);
}

// Minimal structural shapes (NOT the DOM DataTransfer/ClipboardEvent, which are undefined in the node test env).
export interface ClipboardLike {
  items?: ArrayLike<{ kind: string; type: string; getAsFile(): File | null }>;
}
export interface DataTransferLike {
  files?: ArrayLike<File>;
}

/** Every pasted file (any type); text items are left to the textarea. */
export function filesFromPaste(clipboard: ClipboardLike): File[] {
  const out: File[] = [];
  const items = clipboard.items;
  if (!items) return out;
  for (let i = 0; i < items.length; i++) {
    const it = items[i];
    if (it.kind === "file") {
      const f = it.getAsFile();
      if (f) out.push(f);
    }
  }
  return out;
}

export function filesFromDrop(dt: DataTransferLike): File[] {
  const out: File[] = [];
  const files = dt.files;
  if (!files) return out;
  for (let i = 0; i < files.length; i++) out.push(files[i]);
  return out;
}

const MIME_EXT: Record<string, string> = {
  "image/png": "png", "image/jpeg": "jpg", "image/gif": "gif", "image/webp": "webp", "image/bmp": "bmp",
  "image/tiff": "tiff", "image/heic": "heic", "image/heif": "heif", "application/pdf": "pdf", "text/plain": "txt",
  "text/html": "html", "text/csv": "csv", "text/tab-separated-values": "tsv", "application/json": "json",
  "text/markdown": "md",
};
const GENERATED_NAME = /^(image|blob|clipboard|pasted)\b/i;
const pad = (n: number) => String(n).padStart(2, "0");

/** A pasted file whose name the user never chose (a screenshot is "image.png" every time) gets
 *  `pasted-YYYYMMDD-HHmmss-<seq>.<ext>`, so two pastes are two files, not one deduped away. */
export function normalizePastedName(file: File, now: Date, seq: number): File {
  if (file.name && !GENERATED_NAME.test(file.name)) return file;
  const ext = MIME_EXT[file.type] ?? (extOf(file.name).slice(1) || "bin");
  const stamp = `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}-` +
    `${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
  return new File([file], `pasted-${stamp}-${seq}.${ext}`, { type: file.type, lastModified: file.lastModified });
}

/** Stable identity for dedup (open-webui dedups by name; we add size). */
export function fileKey(f: { name: string; size: number }): string {
  return `${f.name}:${f.size}`;
}

export interface ValidationResult {
  accepted: File[];
  errors: AttachmentError[];
}

/**
 * Validate incoming files against what is already attached (a restored upload has a name and a size, no File).
 * In order per file: a duplicate (name+size, against existing and within the batch) is skipped silently; then
 * the type, the per-file size, the count and the total size of the message.
 */
export function validateFiles(existing: { name: string; size: number }[], incoming: File[],
                              rules: AttachmentRules): ValidationResult {
  const accepted: File[] = [];
  const errors: AttachmentError[] = [];
  const seen = new Set(existing.map(fileKey));
  let count = existing.length;
  let total = existing.reduce((sum, f) => sum + f.size, 0);
  for (const f of incoming) {
    const key = fileKey(f);
    if (seen.has(key)) continue;
    if (!rules.accepted(f.name)) {
      errors.push({ kind: "type", name: f.name });
      continue;
    }
    if (f.size > rules.maxFileBytes) {
      errors.push({ kind: "size", name: f.name, limit: rules.maxFileBytes });
      continue;
    }
    if (count >= rules.max) {
      errors.push({ kind: "count", limit: rules.max });
      break;
    }
    if (total + f.size > rules.maxTotalBytes) {
      errors.push({ kind: "total", limit: rules.maxTotalBytes });
      continue;
    }
    seen.add(key);
    accepted.push(f);
    count++;
    total += f.size;
  }
  return { accepted, errors };
}

/** A server reason code (file_too_large, encrypted, model_no_images, …) in the user's language; an unknown one as is. */
export function attachmentReasonText(code: string | null | undefined, t: (k: string) => string): string {
  if (!code) return "";
  const key = `chat.attach.reason.${code}`;
  const text = t(key);
  return text === key ? code : text;
}
