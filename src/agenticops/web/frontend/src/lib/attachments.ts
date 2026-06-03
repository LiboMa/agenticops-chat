// Single source of truth for chat attachment types + limits (mirrors backend
// file_reader.py caps so client validation never disagrees with the server).

export const MAX_ATTACHMENTS = 5;

// Per-extension-class size caps — MUST match how app.py routes each upload
// through file_reader.py (verified against the live classification):
//   image    (is_image_file)    → MAX_IMAGE_SIZE     5 MB
//   document (is_document_file) → MAX_DOCUMENT_SIZE  5 MB  ← txt/md/csv land HERE
//   text/else (read_upload_bytes) → MAX_FILE_SIZE    512 KB
// NOTE: .txt/.md/.csv are DOCUMENTS server-side (5 MB), NOT the 512 KB text path.
// Only log/json/yaml/yml/py/sh/xml/tf fall through to the 512 KB else-branch.
const KB = 1024;
const MB = 1024 * 1024;
const MAX_TEXT_SIZE = 512 * KB;
const MAX_IMAGE_SIZE = 5 * MB;
const MAX_DOCUMENT_SIZE = 5 * MB;

const IMAGE_EXTS = ["png", "jpg", "jpeg", "gif", "webp"];
// Document branch server-side (is_document_file): 5 MB cap.
const DOCUMENT_EXTS = ["pdf", "docx", "txt", "md", "csv"];
// Else/text branch server-side (read_upload_bytes): 512 KB cap.
const TEXT_EXTS = ["log", "json", "yaml", "yml", "py", "sh", "xml", "tf"];

export const ACCEPTED_EXTENSIONS: string[] = [...IMAGE_EXTS, ...DOCUMENT_EXTS, ...TEXT_EXTS];

/** value for an <input accept="..."> attribute, derived from ACCEPTED_EXTENSIONS. */
export const acceptAttr: string = ACCEPTED_EXTENSIONS.map((e) => `.${e}`).join(",");

function extOf(name: string): string {
  const i = name.lastIndexOf(".");
  return i >= 0 ? name.slice(i + 1).toLowerCase() : "";
}

/** Size cap for a file by its extension class. Unknown → text cap (smallest). */
export function maxSizeForFile(name: string): number {
  const ext = extOf(name);
  if (IMAGE_EXTS.includes(ext)) return MAX_IMAGE_SIZE;
  if (DOCUMENT_EXTS.includes(ext)) return MAX_DOCUMENT_SIZE;
  return MAX_TEXT_SIZE;
}

function isAccepted(name: string): boolean {
  return ACCEPTED_EXTENSIONS.includes(extOf(name));
}

function humanSize(bytes: number): string {
  return bytes >= MB ? `${Math.round(bytes / MB)} MB` : `${Math.round(bytes / KB)} KB`;
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
  errors: string[];
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
export function validateFiles(existing: File[], incoming: File[]): ValidationResult {
  const accepted: File[] = [];
  const errors: string[] = [];
  const seen = new Set(existing.map(fileKey)); // dedup vs current selection + within batch
  let count = existing.length;
  for (const f of incoming) {
    const key = fileKey(f);
    if (seen.has(key)) continue; // duplicate — skip silently
    if (!isAccepted(f.name)) {
      errors.push(`${f.name}: type not supported`);
      continue;
    }
    const cap = maxSizeForFile(f.name);
    if (f.size > cap) {
      errors.push(`${f.name}: too large (max ${humanSize(cap)})`);
      continue;
    }
    if (count >= MAX_ATTACHMENTS) {
      errors.push(`too many files (max ${MAX_ATTACHMENTS})`);
      break;
    }
    seen.add(key);
    accepted.push(f);
    count++;
  }
  return { accepted, errors };
}
