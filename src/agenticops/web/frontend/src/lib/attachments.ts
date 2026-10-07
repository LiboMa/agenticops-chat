// Chat attachment rules (MVP-2.7.0 S5): they come from the server — GET /api/ui/bootstrap `upload_policy`, built
// from chat/file_reader in the send handler's own dispatch order (image → native document → text fallback) — so the
// composer and the server never disagree. FALLBACK_POLICY mirrors that policy for the moment before bootstrap loads.

export interface UploadPolicy {
  max_files: number; image_max_bytes: number; document_max_bytes: number; text_fallback_max_bytes: number;
  image_extensions: string[]; document_extensions: string[]; text_extensions: string[];
}

const KB = 1024;
const MB = 1024 * 1024;

export const FALLBACK_POLICY: UploadPolicy = {
  max_files: 5, image_max_bytes: 5 * MB, document_max_bytes: 5 * MB, text_fallback_max_bytes: 512 * KB,
  image_extensions: [".gif", ".jpeg", ".jpg", ".png", ".webp"],
  document_extensions: [".csv", ".doc", ".docx", ".html", ".md", ".pdf", ".txt", ".xls", ".xlsx"],
  text_extensions: [".cfg", ".conf", ".hcl", ".ini", ".js", ".json", ".log", ".py", ".sh", ".tf", ".toml", ".ts",
                    ".xml", ".yaml", ".yml"],
};

export interface AttachmentRules {
  max: number;
  accept: string;                       // for <input accept="…">
  maxSizeFor(name: string): number;     // by the type class the server routes it to; unknown → the text cap
  accepted(name: string): boolean;
}

function extOf(name: string): string {
  const i = name.lastIndexOf(".");
  return i >= 0 ? name.slice(i + 1).toLowerCase() : "";
}

const bare = (exts: string[]) => exts.map((e) => e.replace(/^\./, "").toLowerCase());

export function attachmentRules(policy: UploadPolicy): AttachmentRules {
  const images = bare(policy.image_extensions), documents = bare(policy.document_extensions);
  const texts = bare(policy.text_extensions);
  const all = [...images, ...documents, ...texts];
  return {
    max: policy.max_files,
    accept: all.map((e) => `.${e}`).join(","),
    maxSizeFor(name) {
      const ext = extOf(name);
      if (images.includes(ext)) return policy.image_max_bytes;
      if (documents.includes(ext)) return policy.document_max_bytes;
      return policy.text_fallback_max_bytes;
    },
    accepted: (name) => all.includes(extOf(name)),
  };
}

const DEFAULT_RULES = attachmentRules(FALLBACK_POLICY);
export const MAX_ATTACHMENTS = DEFAULT_RULES.max;
export const acceptAttr: string = DEFAULT_RULES.accept;
export const maxSizeForFile = (name: string) => DEFAULT_RULES.maxSizeFor(name);

function humanSize(bytes: number): string {
  return bytes >= MB ? `${Math.round(bytes / MB)} MB` : `${Math.round(bytes / KB)} KB`;
}

/** Why a file was not attached; the composer words it in the user's language (attachmentErrorText). */
export type AttachmentError = { kind: "type"; name: string } | { kind: "size"; name: string; limit: number }
  | { kind: "count"; limit: number };

export function attachmentErrorText(e: AttachmentError, t: (k: string) => string): string {
  const name = "name" in e ? e.name : "";
  const limit = e.kind === "size" ? humanSize(e.limit) : e.kind === "count" ? String(e.limit) : "";
  return t(`chat.attach.${e.kind}`).replace("{name}", name).replace("{limit}", limit);
}

// Minimal structural shapes (NOT the DOM DataTransfer/ClipboardEvent, which are
// undefined in the node test env). The real e.clipboardData / e.dataTransfer
// satisfy these at the call site.
export interface ClipboardLike {
  items?: ArrayLike<{ kind: string; type: string; getAsFile(): File | null }>;
}
export interface DataTransferLike {
  files?: ArrayLike<File>;
}

/** Extract pasted images (image/* items) as Files; ignore text items. */
export function filesFromPaste(clipboard: ClipboardLike): File[] {
  const out: File[] = [];
  const items = clipboard.items;
  if (!items) return out;
  for (let i = 0; i < items.length; i++) {
    const it = items[i];
    if (it.kind === "file" && it.type.startsWith("image/")) {
      const f = it.getAsFile();
      if (f) out.push(f);
    }
  }
  return out;
}

/** Extract dropped files. */
export function filesFromDrop(dt: DataTransferLike): File[] {
  const out: File[] = [];
  const files = dt.files;
  if (!files) return out;
  for (let i = 0; i < files.length; i++) out.push(files[i]);
  return out;
}

/** Stable identity for dedup + React keys (open-webui dedups by name; we add size). */
export function fileKey(f: File): string {
  return `${f.name}:${f.size}`;
}

export interface ValidationResult {
  accepted: File[];
  errors: AttachmentError[];
}

/**
 * Validate incoming files against the existing selection. In order:
 *   - dedup against existing AND within the incoming batch (by name+size)
 *   - reject unsupported extension
 *   - reject oversize (per-type cap)
 *   - reject over-count (MAX_ATTACHMENTS total)
 * Duplicates are silently skipped (no error noise — re-pasting the same screenshot
 * is a common, benign action).
 */
export function validateFiles(existing: File[], incoming: File[], rules: AttachmentRules = DEFAULT_RULES): ValidationResult {
  const accepted: File[] = [];
  const errors: AttachmentError[] = [];
  const seen = new Set(existing.map(fileKey)); // dedup vs current selection + within batch
  let count = existing.length;
  for (const f of incoming) {
    const key = fileKey(f);
    if (seen.has(key)) continue; // duplicate — skip silently
    if (!rules.accepted(f.name)) {
      errors.push({ kind: "type", name: f.name });
      continue;
    }
    const cap = rules.maxSizeFor(f.name);
    if (f.size > cap) {
      errors.push({ kind: "size", name: f.name, limit: cap });
      continue;
    }
    if (count >= rules.max) {
      errors.push({ kind: "count", limit: rules.max });
      break;
    }
    seen.add(key);
    accepted.push(f);
    count++;
  }
  return { accepted, errors };
}
