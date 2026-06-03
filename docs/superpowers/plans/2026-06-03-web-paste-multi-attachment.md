# Web Paste / Drag-Drop + Multi-Attachment Upload — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the web chat composer accept pasted images (`Cmd+V`), drag-dropped files, and multiple attachments per message (max 5, existing accepted types only), end-to-end to the agent.

**Architecture:** A pure, unit-testable `lib/attachments.ts` (extraction + per-type validation + dedup) drives `ChatInput.tsx` (paste/drop UI + multi-badge). The send chain (`chatStream.ts` → `useSessionStream.ts` → `useLazySessionCreate.ts`) changes `file?: File` → `files?: File[]` and appends all files to one `FormData`. The backend `app.py` multipart branch reads `form.getlist("file")` and loops the **already-list-based** classification (`file_images`/`file_documents`/`file_contents`). Preprocessor, `file_reader.py`, and the `ChatMessage` model are untouched.

**Tech Stack:** React 18 + TypeScript + Vite/Vitest (frontend, node test env — no DOM rendering); FastAPI + Starlette `UploadFile` (backend); pytest + TestClient.

**Spec:** `docs/superpowers/specs/2026-06-03-web-paste-multi-attachment-design.md`

### Implementation patterns borrowed from open-webui (code-verified, to avoid known bugs)

This plan adopts open-webui's battle-tested upload UX patterns (their `MessageInput.svelte` /
`Chat.svelte` / `FilesOverlay.svelte`), mapped to React. These prevent real bugs they shipped
fixes for. **No feature scope is added — only the implementation is made robust.**

1. **`dragover`-driven highlight, not dragenter-counter.** `onDragOver` sets `dragging=true`
   every frame (continuous while hovering) → naturally flicker-immune. Gate on
   `e.dataTransfer.types.includes("Files")` so text-selection drags don't trigger it.
2. **`dragleave` contains-guard:** `if (e.currentTarget.contains(e.relatedTarget as Node)) return;`
   — moving the cursor onto a child element does NOT clear the highlight. (This is their fix
   for the Firefox "overlay stuck / flicker" bug #21664.)
3. **Escape + drop always reset** `dragging=false` (no stuck overlay).
4. **Capture-phase listeners + airtight cleanup.** Drag listeners attach to the composer
   container in a `useEffect` with `{ capture: true }`, and the cleanup removes them with the
   **same `{ capture: true }`** options. (Their memory-leak bug #21968 was un-removed
   listeners → page crash on extended use.)
5. **Paste: selective `preventDefault`.** Loop `e.clipboardData.items`, `getAsFile()` for
   `image/*`; `preventDefault()` **only when a file is actually consumed** so normal text
   paste still works.
6. **Single ingress handler.** Drop, paste, and the `<input>` onChange all funnel into one
   `addFiles(File[])` → one place for validation + dedup.
7. **Validate limits BEFORE building FormData** (count + per-type size) — done in
   `validateFiles`.
8. **dataURL previews, never `URL.createObjectURL`.** We don't render image thumbnails this
   phase (filename badges only), so there is nothing to leak — but if a preview is ever added,
   use a FileReader dataURL, not an object URL (avoids revoke bookkeeping / leaks).
9. **Dedup incoming files by `name+size`** before adding to state (their duplicate-upload
   bug #10f06a64). React keys/removal use a stable per-attachment id, **never the array index**
   (their concurrent-removal race, fixed via UUID `tempItemId`).
10. **Allow send with files but empty text** (their dropped-file-context bug #21477) — already
    handled by our fallback-text logic.

---

## Conventions

- **Frontend tests:** from `src/agenticops/web/frontend/`, `npm run test` (vitest `--run`, node env). **No DOM-rendering tests** — match the existing `__tests__/sessionSort.prop.test.ts` style.
- **Frontend type-check / build:** `cd src/agenticops/web/frontend && npx tsc --noEmit && npm run build`.
- **Backend tests:** `.venv/bin/python -m pytest tests/<file> -v` (real SQLite, seed+clean own rows, per `tests/test_chat_api.py`).
- **Backend compile:** `python3 -m py_compile src/agenticops/web/app.py`.
- **Commits:** one per task, `git commit --no-verify` (Code Defender). Do NOT push.
- **`lib/` gitignore caveat:** the repo `.gitignore` ignores `lib/` dirs — new files under `src/.../lib/` need `git add -f` (the existing `chatStream.ts`, `markdownCache.ts` were force-added). `hooks/`, `components/`, `tests/` add normally.
- **Branch:** continue on the current branch.

### Environment fact that shapes the tests (verified)

In the vitest **node** env (Node 25): `File` is a global ✅, but **`DataTransfer` and `ClipboardEvent` are `undefined`**. Therefore the pure extraction functions must accept the **minimal structural shape** they use — NOT the DOM `DataTransfer`/`ClipboardEvent` types — so they can be unit-tested with plain object fixtures. The `ChatInput` handlers pass the real `e.clipboardData` / `e.dataTransfer` (which structurally satisfy the shape) at the call site.

---

## File Structure

**Frontend (create):**
- `src/agenticops/web/frontend/src/lib/attachments.ts` — accepted types, limits, `filesFromPaste`, `filesFromDrop`, `validateFiles`, `maxSizeForFile`, `acceptAttr`.
- `src/agenticops/web/frontend/src/__tests__/attachments.test.ts` — pure-function tests.

**Frontend (modify):**
- `src/agenticops/web/frontend/src/components/chat/ChatInput.tsx` — array state, paste/drop handlers, multi-badge, `onSend(message, files: File[])`.
- `src/agenticops/web/frontend/src/lib/chatStream.ts` — `send(... files?: File[] ...)`, FormData loop.
- `src/agenticops/web/frontend/src/hooks/useSessionStream.ts` — pass `files`, optimistic multi-attachment.
- `src/agenticops/web/frontend/src/hooks/useLazySessionCreate.ts` — `sendFirstMessage(content, files?, detailLevel?)`.
- `src/agenticops/web/frontend/src/pages/Chat.tsx` — welcome `handleWelcomeSend` + normal `onSend` wiring to `files`.

**Backend (modify):**
- `src/agenticops/web/app.py` — multipart branch: `form.getlist("file")` loop; accumulate `attachments` list.

**Backend (test):**
- `tests/test_chat_multi_attachment.py` *(new)* — multipart with 2 files.

---

## Task 1: Pure attachment logic + tests (`lib/attachments.ts`)

**Files:**
- Create: `src/agenticops/web/frontend/src/lib/attachments.ts`
- Create: `src/agenticops/web/frontend/src/__tests__/attachments.test.ts`

- [ ] **Step 1: Write the module**

Create `src/agenticops/web/frontend/src/lib/attachments.ts`:

```typescript
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

const IMAGE_EXTS = ["png", "jpg", "jpeg", "gif", "webp", "bmp"];
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
```

- [ ] **Step 2: Write the failing tests**

Create `src/agenticops/web/frontend/src/__tests__/attachments.test.ts`:

```typescript
import { describe, it, expect } from "vitest";
import {
  filesFromPaste,
  filesFromDrop,
  validateFiles,
  maxSizeForFile,
  acceptAttr,
  fileKey,
  MAX_ATTACHMENTS,
} from "@/lib/attachments";

function file(name: string, size: number): File {
  // node File global accepts (bits, name); override size via a small Blob slice trick.
  const f = new File([new Uint8Array(size)], name);
  return f;
}

describe("attachments", () => {
  it("filesFromPaste extracts image items and ignores text items", () => {
    const img = file("shot.png", 10);
    const clipboard = {
      items: [
        { kind: "string", type: "text/plain", getAsFile: () => null },
        { kind: "file", type: "image/png", getAsFile: () => img },
      ],
    };
    const out = filesFromPaste(clipboard);
    expect(out).toHaveLength(1);
    expect(out[0].name).toBe("shot.png");
  });

  it("filesFromPaste returns [] when no items", () => {
    expect(filesFromPaste({})).toEqual([]);
  });

  it("filesFromDrop returns dropped files", () => {
    const a = file("a.log", 10);
    const b = file("b.json", 10);
    expect(filesFromDrop({ files: [a, b] }).map((f) => f.name)).toEqual(["a.log", "b.json"]);
  });

  it("validateFiles accepts supported types under the size cap", () => {
    const r = validateFiles([], [file("ok.png", 100), file("ok.log", 100)]);
    expect(r.accepted.map((f) => f.name)).toEqual(["ok.png", "ok.log"]);
    expect(r.errors).toEqual([]);
  });

  it("validateFiles rejects unsupported extension", () => {
    const r = validateFiles([], [file("bad.exe", 10)]);
    expect(r.accepted).toEqual([]);
    expect(r.errors[0]).toContain("type not supported");
  });

  it("validateFiles rejects oversize per-type (text 512KB, image 5MB)", () => {
    const bigLog = validateFiles([], [file("big.log", 600 * 1024)]); // > 512KB text cap
    expect(bigLog.accepted).toEqual([]);
    expect(bigLog.errors[0]).toContain("too large");

    const okImg = validateFiles([], [file("pic.png", 600 * 1024)]); // fine under 5MB
    expect(okImg.accepted).toHaveLength(1);
  });

  it("validateFiles caps total at MAX_ATTACHMENTS across existing + incoming", () => {
    const existing = [file("1.png", 10), file("2.png", 10), file("3.png", 10)];
    const incoming = [file("4.png", 10), file("5.png", 10), file("6.png", 10)];
    const r = validateFiles(existing, incoming);
    expect(r.accepted).toHaveLength(MAX_ATTACHMENTS - existing.length); // 2
    expect(r.errors.some((e) => e.includes("too many"))).toBe(true);
  });

  it("maxSizeForFile classifies by extension (matches backend routing)", () => {
    expect(maxSizeForFile("x.png")).toBe(5 * 1024 * 1024);   // image
    expect(maxSizeForFile("x.pdf")).toBe(5 * 1024 * 1024);   // document
    expect(maxSizeForFile("x.txt")).toBe(5 * 1024 * 1024);   // document server-side, NOT 512KB
    expect(maxSizeForFile("x.csv")).toBe(5 * 1024 * 1024);   // document
    expect(maxSizeForFile("x.log")).toBe(512 * 1024);        // else/text branch
    expect(maxSizeForFile("x.json")).toBe(512 * 1024);       // else/text branch
    expect(maxSizeForFile("x.unknown")).toBe(512 * 1024);    // default → smallest
  });

  it("acceptAttr is a dotted comma list", () => {
    expect(acceptAttr).toContain(".png");
    expect(acceptAttr).toContain(".log");
    expect(acceptAttr.startsWith(".")).toBe(true);
  });

  it("validateFiles dedups against existing selection (name+size), silently", () => {
    const existing = [file("shot.png", 100)];
    const r = validateFiles(existing, [file("shot.png", 100), file("other.png", 100)]);
    expect(r.accepted.map((f) => f.name)).toEqual(["other.png"]); // dup skipped
    expect(r.errors).toEqual([]); // no error noise for dedup
  });

  it("validateFiles dedups within the incoming batch", () => {
    const r = validateFiles([], [file("a.png", 100), file("a.png", 100)]);
    expect(r.accepted).toHaveLength(1);
  });

  it("same name but different size is NOT a duplicate", () => {
    const r = validateFiles([file("a.log", 100)], [file("a.log", 200)]);
    expect(r.accepted).toHaveLength(1);
  });

  it("fileKey combines name and size", () => {
    expect(fileKey(file("x.png", 42))).toBe("x.png:42");
  });
});
```

- [ ] **Step 3: Run tests**

Run: `cd /Users/malibo/MyDev/AgenticOps/src/agenticops/web/frontend && npx vitest --run src/__tests__/attachments.test.ts`
Expected: PASS (13 tests).

NOTE on the `file()` helper: `new File([new Uint8Array(size)], name)` produces a File whose
`.size === size`. If for any reason `.size` reads 0 in this node version, fall back to
`new File([new Uint8Array(size)], name)` → it should be `size`; if not, build the blob as
`new File(["x".repeat(size)], name)`. Confirm `.size` is correct first; report if it isn't.

- [ ] **Step 4: Type-check**

Run: `cd /Users/malibo/MyDev/AgenticOps/src/agenticops/web/frontend && npx tsc --noEmit`
Expected: PASS.

- [ ] **Step 5: Commit** (force-add — `lib/` is gitignored)

```bash
cd /Users/malibo/MyDev/AgenticOps
git add -f src/agenticops/web/frontend/src/lib/attachments.ts
git add src/agenticops/web/frontend/src/__tests__/attachments.test.ts
git commit --no-verify -m "feat(web): attachments lib — paste/drop extraction + per-type validation"
```

Verify tracked: `git ls-files src/agenticops/web/frontend/src/lib/attachments.ts` prints the path.

---

## Task 2: Backend — accept multiple files (`form.getlist`)

**Files:**
- Create: `tests/test_chat_multi_attachment.py`
- Modify: `src/agenticops/web/app.py` (multipart branch, lines ~4017-4047)

- [ ] **Step 1: Write the failing test**

Create `tests/test_chat_multi_attachment.py`:

```python
"""Multi-attachment multipart upload: two files in one chat message reach the agent."""

from datetime import datetime, timezone

import pytest
from starlette.testclient import TestClient

from agenticops.web.app import app
from agenticops.models import ChatSession, ChatMessage, get_db_session


@pytest.fixture
def client():
    return TestClient(app)


def test_multipart_two_files_both_attached(client, monkeypatch):
    """POST with 1 png (image branch) + 1 .txt (document branch) → both recorded as
    attachments. (.txt routes through is_document_file server-side, not the text else-branch;
    the assertions hold regardless of branch — the point is BOTH files are captured.)"""
    import agenticops.web.app as webapp

    session_id = "multi-attach-001"
    now = datetime.now(timezone.utc)
    with get_db_session() as db:
        db.add(ChatSession(session_id=session_id, name="Multi",
                           created_at=now, updated_at=now, last_activity_at=now))

    captured = {}

    class _CaptureAgent:
        async def stream_async(self, content):
            captured["content"] = content
            yield {"data": "ok"}

    monkeypatch.setattr(webapp._chat_sessions, "get_or_create", lambda sid: _CaptureAgent())

    # a tiny valid PNG (1x1) + a text file
    png_bytes = bytes.fromhex(
        "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
        "890000000a49444154789c6360000002000154a24f5e0000000049454e44ae426082"
    )
    files = [
        ("file", ("shot.png", png_bytes, "image/png")),
        ("file", ("notes.txt", b"hello log line", "text/plain")),
    ]
    try:
        resp = client.post(
            f"/api/chat/sessions/{session_id}/messages",
            data={"content": "analyze these"},
            files=files,
        )
        assert resp.status_code == 200

        with get_db_session() as db:
            row = db.query(ChatSession).filter(ChatSession.session_id == session_id).first()
            msgs = db.query(ChatMessage).filter(
                ChatMessage.session_id == row.id, ChatMessage.role == "user"
            ).all()
            assert msgs, "user message persisted"
            atts = msgs[-1].attachments or []
            names = sorted(a["filename"] for a in atts)
            assert names == ["notes.txt", "shot.png"], f"both attachments recorded, got {names}"
    finally:
        with get_db_session() as db:
            row = db.query(ChatSession).filter(ChatSession.session_id == session_id).first()
            if row:
                db.query(ChatMessage).filter(ChatMessage.session_id == row.id).delete()
                db.delete(row)
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_chat_multi_attachment.py -v`
Expected: FAIL — only the last file is recorded (current code uses `form.get("file")` →
`attachments` ends up with one entry or wrong count).

- [ ] **Step 3: Rewrite the multipart file-handling block**

In `src/agenticops/web/app.py`, replace the block from `upload = form.get("file")` through
the end of the text/else branch (currently lines ~4017-4047) — i.e. replace:

```python
        upload = form.get("file")

        if upload and hasattr(upload, "filename") and upload.filename:
            from agenticops.chat.file_reader import (
                is_image_file, is_document_file,
                read_upload_image_bytes, read_upload_document_bytes,
                read_upload_bytes,
            )
            raw = await upload.read()

            if is_image_file(upload.filename):
                img_bytes, fmt, error = read_upload_image_bytes(upload.filename, raw)
                if error:
                    raise HTTPException(400, error)
                if img_bytes and fmt:
                    file_images.append((upload.filename, img_bytes, fmt))
                    attachments = [{"filename": upload.filename, "size": len(raw), "type": "image"}]
            elif is_document_file(upload.filename):
                doc_bytes, fmt, name, error = read_upload_document_bytes(upload.filename, raw)
                if error:
                    raise HTTPException(400, error)
                if doc_bytes and fmt and name:
                    file_documents.append((upload.filename, doc_bytes, fmt, name))
                    attachments = [{"filename": upload.filename, "size": len(raw), "type": "document"}]
            else:
                file_text, error = read_upload_bytes(upload.filename, raw)
                if error:
                    raise HTTPException(400, error)
                if file_text:
                    file_contents.append((upload.filename, file_text))
                    attachments = [{"filename": upload.filename, "size": len(raw), "type": "text"}]

        has_file = file_contents or file_images or file_documents
        if not text_content and not has_file:
            raise HTTPException(400, "Message content or file required")
        if not text_content:
            text_content = f"Please analyze the attached file: {upload.filename}"
        user_content = text_content
```

with (loop over all uploaded files; accumulate `attachments`):

```python
        uploads = form.getlist("file")
        valid_uploads = [u for u in uploads if hasattr(u, "filename") and u.filename]

        if valid_uploads:
            from agenticops.chat.file_reader import (
                is_image_file, is_document_file,
                read_upload_image_bytes, read_upload_document_bytes,
                read_upload_bytes,
            )
            attachments = []
            for upload in valid_uploads:
                raw = await upload.read()
                if is_image_file(upload.filename):
                    img_bytes, fmt, error = read_upload_image_bytes(upload.filename, raw)
                    if error:
                        raise HTTPException(400, error)
                    if img_bytes and fmt:
                        file_images.append((upload.filename, img_bytes, fmt))
                        attachments.append({"filename": upload.filename, "size": len(raw), "type": "image"})
                elif is_document_file(upload.filename):
                    doc_bytes, fmt, name, error = read_upload_document_bytes(upload.filename, raw)
                    if error:
                        raise HTTPException(400, error)
                    if doc_bytes and fmt and name:
                        file_documents.append((upload.filename, doc_bytes, fmt, name))
                        attachments.append({"filename": upload.filename, "size": len(raw), "type": "document"})
                else:
                    file_text, error = read_upload_bytes(upload.filename, raw)
                    if error:
                        raise HTTPException(400, error)
                    if file_text:
                        file_contents.append((upload.filename, file_text))
                        attachments.append({"filename": upload.filename, "size": len(raw), "type": "text"})

        has_file = file_contents or file_images or file_documents
        if not text_content and not has_file:
            raise HTTPException(400, "Message content or file required")
        if not text_content:
            _names = ", ".join(a["filename"] for a in (attachments or []))
            text_content = f"Please analyze the attached file(s): {_names}"
        user_content = text_content
```

(`attachments` stays `None` when no files, since it's only set to `[]` inside the
`valid_uploads` branch — preserving the existing JSON-or-null persistence behavior.)

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_chat_multi_attachment.py -v`
Expected: PASS.

- [ ] **Step 5: Run existing chat tests for no regression**

Run: `.venv/bin/python -m pytest tests/test_chat_api.py tests/test_chat_messages_pagination.py -q`
Expected: PASS (no regression; single-file upload still works via the loop).

- [ ] **Step 6: Compile + commit**

```bash
cd /Users/malibo/MyDev/AgenticOps
python3 -m py_compile src/agenticops/web/app.py
git add src/agenticops/web/app.py tests/test_chat_multi_attachment.py
git commit --no-verify -m "feat(api): accept multiple files per chat message (form.getlist + loop)"
```

---

## Task 3: Send chain — `file?: File` → `files?: File[]`

**Files:**
- Modify: `src/agenticops/web/frontend/src/lib/chatStream.ts`
- Modify: `src/agenticops/web/frontend/src/hooks/useSessionStream.ts`
- Modify: `src/agenticops/web/frontend/src/hooks/useLazySessionCreate.ts`

- [ ] **Step 1: chatStream.ts — accept a files array**

In `src/agenticops/web/frontend/src/lib/chatStream.ts`, change the `send` signature and the
FormData construction. Find:

```typescript
  async send(sessionId: string, content: string, file?: File, detailLevel?: string) {
```
change to:
```typescript
  async send(sessionId: string, content: string, files?: File[], detailLevel?: string) {
```

Then find the multipart branch inside `send` (the `if (file) { ... }` block that builds
`FormData` and appends a single `"file"`):

```typescript
      let res: Response;
      if (file) {
        const formData = new FormData();
        formData.append("content", content);
        formData.append("file", file);
        if (detailLevel && detailLevel !== "medium") formData.append("detail_level", detailLevel);
        res = await fetch(`/api/chat/sessions/${sessionId}/messages`, {
          method: "POST", headers: authHeaders, body: formData, signal: controller.signal,
        });
      } else {
```

replace the condition + body with:

```typescript
      let res: Response;
      if (files && files.length > 0) {
        const formData = new FormData();
        formData.append("content", content);
        files.forEach((f) => formData.append("file", f));
        if (detailLevel && detailLevel !== "medium") formData.append("detail_level", detailLevel);
        res = await fetch(`/api/chat/sessions/${sessionId}/messages`, {
          method: "POST", headers: authHeaders, body: formData, signal: controller.signal,
        });
      } else {
```

- [ ] **Step 2: useSessionStream.ts — pass files + optimistic multi-attachment**

In `src/agenticops/web/frontend/src/hooks/useSessionStream.ts`, find the `send` callback:

```typescript
  const send = useCallback(
    (content: string, file?: File, detailLevel?: string) => {
      if (!sessionId) return;
      // Optimistically append the user's message so it shows immediately.
      const userMsg: ChatMessage = {
        id: nextTempId(),
        role: "user",
        content,
        attachments: file ? [{ filename: file.name, size: file.size }] : undefined,
        created_at: new Date().toISOString(),
      };
      appendMessageToCache(qc, sessionId, userMsg);
      void chatStream.send(sessionId, content, file, detailLevel);
    },
    [sessionId, qc],
  );
```

replace with:

```typescript
  const send = useCallback(
    (content: string, files?: File[], detailLevel?: string) => {
      if (!sessionId) return;
      // Optimistically append the user's message so it shows immediately.
      const userMsg: ChatMessage = {
        id: nextTempId(),
        role: "user",
        content,
        attachments: files && files.length > 0
          ? files.map((f) => ({ filename: f.name, size: f.size }))
          : undefined,
        created_at: new Date().toISOString(),
      };
      appendMessageToCache(qc, sessionId, userMsg);
      void chatStream.send(sessionId, content, files, detailLevel);
    },
    [sessionId, qc],
  );
```

- [ ] **Step 3: useLazySessionCreate.ts — files array through the welcome flow**

In `src/agenticops/web/frontend/src/hooks/useLazySessionCreate.ts`, find the
`sendFirstMessage` signature and body:

```typescript
  const sendFirstMessage = useCallback(
    async (content: string, file?: File, detailLevel?: string) => {
```
change to:
```typescript
  const sendFirstMessage = useCallback(
    async (content: string, files?: File[], detailLevel?: string) => {
```

Then find the optimistic user-message seed + the `chatStream.send` call:

```typescript
        const userMsg: ChatMessage = {
          id: nextTempId(),
          role: "user",
          content,
          attachments: file ? [{ filename: file.name, size: file.size }] : undefined,
          created_at: new Date().toISOString(),
        };
        appendMessageToCache(qc, session.session_id, userMsg);
        // Kick off the stream in the store, then navigate. The Chat page binds
        // to the in-flight stream for this session id on mount.
        void chatStream.send(session.session_id, content, file, detailLevel);
```

replace with:

```typescript
        const userMsg: ChatMessage = {
          id: nextTempId(),
          role: "user",
          content,
          attachments: files && files.length > 0
            ? files.map((f) => ({ filename: f.name, size: f.size }))
            : undefined,
          created_at: new Date().toISOString(),
        };
        appendMessageToCache(qc, session.session_id, userMsg);
        // Kick off the stream in the store, then navigate. The Chat page binds
        // to the in-flight stream for this session id on mount.
        void chatStream.send(session.session_id, content, files, detailLevel);
```

- [ ] **Step 4: Type-check (will fail at Chat.tsx/ChatInput callers — expected until Tasks 4-5)**

Run: `cd /Users/malibo/MyDev/AgenticOps/src/agenticops/web/frontend && npx tsc --noEmit`
Expected: errors ONLY at `Chat.tsx` (passes `file` to `sendMessage`/`sendFirstMessage`) and
`ChatInput` usage — these are fixed in Tasks 4-5. If errors appear in any OTHER file, stop
and report. (Do not commit yet — Task 5 commits the frontend together after tsc is clean.)

NOTE: This task intentionally leaves the tree non-compiling until Task 5. If you prefer each
task to compile independently, do Tasks 3+4+5 as one unit before the type-check gate. Either
way, commit only once tsc passes (end of Task 5).

---

## Task 4: `lib/attachments` wired into nothing yet — (folded; no-op placeholder removed)

*(Intentionally omitted — attachments.ts from Task 1 is consumed in Task 5.)*

---

## Task 5: `ChatInput.tsx` paste/drop/multi-file UI + `Chat.tsx` wiring

**Files:**
- Modify: `src/agenticops/web/frontend/src/components/chat/ChatInput.tsx`
- Modify: `src/agenticops/web/frontend/src/pages/Chat.tsx`

- [ ] **Step 1: Rewrite ChatInput.tsx**

Replace the ENTIRE contents of `src/agenticops/web/frontend/src/components/chat/ChatInput.tsx` with:

Patterns from open-webui (see header): `dragover`-driven highlight, `dragleave`
contains-guard, Escape/drop reset, **capture-phase** drag listeners with **matching cleanup**,
selective `preventDefault` on paste, single `addFiles` ingress, UUID-keyed attachment state
(removal by id, never index).

```typescript
import { useState, useRef, useEffect, useCallback } from "react";
import {
  acceptAttr,
  filesFromPaste,
  filesFromDrop,
  validateFiles,
} from "@/lib/attachments";

interface Props {
  onSend: (message: string, files: File[]) => void;
  onCancel?: () => void;
  disabled?: boolean;
  streaming?: boolean;
  detailLevel?: string;
  onDetailLevelChange?: (level: string) => void;
}

// Attachment carries a stable id so removal + React keys never use the array index
// (open-webui bug G: index-based removal races with concurrent adds).
interface Attachment {
  id: string;
  file: File;
}

let _attachSeq = 0;
function nextAttachId(): string {
  // No Math.random/Date.now needed — a module counter is stable + unique per session.
  _attachSeq += 1;
  return `att-${_attachSeq}`;
}

export function ChatInput({ onSend, onCancel, disabled, streaming, detailLevel, onDetailLevelChange }: Props) {
  const [input, setInput] = useState("");
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [attachError, setAttachError] = useState<string | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const addFiles = useCallback((incoming: File[]) => {
    if (incoming.length === 0) return;
    setAttachments((prev) => {
      const existing = prev.map((a) => a.file);
      const { accepted, errors } = validateFiles(existing, incoming);
      setAttachError(errors.length > 0 ? errors.join("; ") : null);
      if (accepted.length === 0) return prev;
      return [...prev, ...accepted.map((f) => ({ id: nextAttachId(), file: f }))];
    });
  }, []);

  const handleSend = () => {
    const trimmed = input.trim();
    if ((!trimmed && attachments.length === 0) || disabled) return;
    const fallback = attachments.length > 0 ? "Please analyze the attached file(s)" : "";
    onSend(trimmed || fallback, attachments.map((a) => a.file));
    setInput("");
    setAttachments([]);
    setAttachError(null);
  };

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) addFiles(Array.from(e.target.files));
    e.target.value = ""; // allow re-selecting the same file
  };

  // Paste: pull image/* items as files; only preventDefault when we actually
  // consume a file, so normal text paste still works (open-webui pattern #5/#6).
  const handlePaste = (e: React.ClipboardEvent<HTMLTextAreaElement>) => {
    const imgs = filesFromPaste(e.clipboardData);
    if (imgs.length > 0) {
      e.preventDefault();
      addFiles(imgs);
    }
  };

  const removeAttachment = (id: string) => {
    setAttachments((prev) => prev.filter((a) => a.id !== id));
  };

  // Drag-drop wired imperatively on the container in CAPTURE phase, with airtight
  // cleanup (open-webui memory-leak bug #21968). dragover re-asserts true every
  // frame (flicker-immune); dragleave uses the contains-guard (Firefox bug #21664);
  // Escape + drop always reset.
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    const onDragOver = (e: DragEvent) => {
      if (disabled) return;
      // Only react to file drags, not text-selection drags.
      if (e.dataTransfer?.types?.includes("Files")) {
        e.preventDefault();
        setIsDragging(true);
      }
    };
    const onDragLeave = (e: DragEvent) => {
      // Moving onto a child element keeps relatedTarget inside the container → ignore.
      if (el.contains(e.relatedTarget as Node)) return;
      setIsDragging(false);
    };
    const onDrop = (e: DragEvent) => {
      e.preventDefault();
      setIsDragging(false);
      if (e.dataTransfer) addFiles(filesFromDrop(e.dataTransfer));
    };
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") setIsDragging(false);
    };

    const opts = { capture: true } as const;
    el.addEventListener("dragover", onDragOver, opts);
    el.addEventListener("dragleave", onDragLeave, opts);
    el.addEventListener("drop", onDrop, opts);
    window.addEventListener("keydown", onKeyDown);
    return () => {
      el.removeEventListener("dragover", onDragOver, opts);
      el.removeEventListener("dragleave", onDragLeave, opts);
      el.removeEventListener("drop", onDrop, opts);
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [disabled, addFiles]);

  return (
    <div
      ref={containerRef}
      className={`border-t border-border p-4 bg-secondary ${isDragging ? "ring-2 ring-primary-500 ring-inset" : ""}`}
    >
      {/* Attachment badges (keyed by stable id, removable by id) */}
      {attachments.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 mb-2 max-w-4xl mx-auto">
          {attachments.map((a) => (
            <span key={a.id} className="inline-flex items-center gap-1.5 text-xs bg-primary-50 text-primary-700 px-2.5 py-1 rounded-lg border border-primary-200">
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13" />
              </svg>
              {a.file.name}
              <span className="text-primary-400">({(a.file.size / 1024).toFixed(1)} KB)</span>
              <button
                onClick={() => removeAttachment(a.id)}
                className="ml-0.5 text-muted-foreground hover:text-red-500 transition-colors"
                title="Remove"
              >
                ✕
              </button>
            </span>
          ))}
        </div>
      )}

      {/* Validation error */}
      {attachError && (
        <div className="max-w-4xl mx-auto mb-2 text-xs text-red-500">{attachError}</div>
      )}

      <div className="flex gap-3 max-w-4xl mx-auto">
        {/* Hidden file input (multiple) */}
        <input
          ref={fileInputRef}
          type="file"
          multiple
          className="hidden"
          accept={acceptAttr}
          onChange={handleFileSelect}
        />

        {/* Detail level selector */}
        {onDetailLevelChange && (
          <select
            value={detailLevel ?? "medium"}
            onChange={(e) => onDetailLevelChange(e.target.value)}
            disabled={disabled}
            className="self-end text-xs border border-border rounded-lg px-2 py-2.5 text-muted-foreground bg-background focus:outline-none focus:ring-2 focus:ring-primary-500 disabled:opacity-50"
            title="Response detail level"
          >
            <option value="concise">Concise</option>
            <option value="medium">Medium</option>
            <option value="detailed">Detailed</option>
          </select>
        )}

        {/* Attach button */}
        <button
          onClick={() => fileInputRef.current?.click()}
          disabled={disabled}
          className="self-end px-2.5 py-2.5 text-muted-foreground hover:text-primary-600 disabled:opacity-50 transition-colors rounded-lg hover:bg-secondary"
          title="Attach file"
        >
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13" />
          </svg>
        </button>

        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onPaste={handlePaste}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
              e.preventDefault();
              handleSend();
            }
          }}
          placeholder="Ask about AWS resources… (paste/drag files, Cmd+Enter to send)"
          disabled={disabled}
          rows={2}
          className="flex-1 bg-background border border-border rounded-lg px-4 py-2.5 text-sm text-foreground placeholder:text-muted-foreground/50 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500 resize-none disabled:opacity-50 transition-shadow"
        />
        {streaming ? (
          <button
            onClick={onCancel}
            className="px-5 py-2.5 bg-red-500 hover:bg-red-600 text-white text-sm font-medium rounded-lg transition-colors self-end"
          >
            Stop
          </button>
        ) : (
          <button
            onClick={handleSend}
            disabled={(!input.trim() && attachments.length === 0) || disabled}
            className="px-5 py-2.5 bg-primary-600 hover:bg-primary-700 disabled:bg-secondary disabled:text-muted-foreground disabled:cursor-not-allowed text-white text-sm font-medium rounded-lg transition-colors self-end"
          >
            Send
          </button>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Update Chat.tsx callers (file → files)**

In `src/agenticops/web/frontend/src/pages/Chat.tsx`:

(a) The welcome handler — find:
```typescript
  const handleWelcomeSend = (content: string, file?: File) => {
    sendFirstMessage(content, file, detailLevel);
  };
```
replace with:
```typescript
  const handleWelcomeSend = (content: string, files: File[]) => {
    sendFirstMessage(content, files, detailLevel);
  };
```

(b) The normal composer — find the `<ChatInput onSend=...>` in the active-session branch:
```typescript
            <ChatInput
              onSend={(msg, file) => sendMessage(msg, file, detailLevel)}
              onCancel={cancel}
```
replace the `onSend` line with:
```typescript
            <ChatInput
              onSend={(msg, files) => sendMessage(msg, files, detailLevel)}
              onCancel={cancel}
```

(c) The welcome composer — find the welcome-mode `<ChatInput onSend={handleWelcomeSend} ...>`.
`handleWelcomeSend` now has signature `(content, files: File[])`, which matches the new
`onSend` prop type — no change needed there beyond (a). Verify it compiles.

- [ ] **Step 3: Type-check (must be clean now)**

Run: `cd /Users/malibo/MyDev/AgenticOps/src/agenticops/web/frontend && npx tsc --noEmit`
Expected: PASS — all `file`→`files` callers reconciled.

- [ ] **Step 4: Full frontend gate**

Run:
```bash
cd /Users/malibo/MyDev/AgenticOps/src/agenticops/web/frontend
npx tsc --noEmit && npm run build && npm run test
```
Expected: tsc clean, build OK, vitest all green (attachments.test.ts + chatStream.test.ts + sessionSort.prop.test.ts).

- [ ] **Step 5: Commit (Tasks 3 + 5 together — the frontend send-chain + UI)**

```bash
cd /Users/malibo/MyDev/AgenticOps
git add src/agenticops/web/frontend/src/lib/chatStream.ts \
        src/agenticops/web/frontend/src/hooks/useSessionStream.ts \
        src/agenticops/web/frontend/src/hooks/useLazySessionCreate.ts \
        src/agenticops/web/frontend/src/components/chat/ChatInput.tsx \
        src/agenticops/web/frontend/src/pages/Chat.tsx
git commit --no-verify -m "feat(web): paste/drag-drop + multi-attachment composer (send chain files[])"
```

---

## Task 6: Verify MessageList renders multiple attachments + docs

**Files:**
- Read/verify: `src/agenticops/web/frontend/src/components/chat/MessageList.tsx`
- Modify: `docs/WORKFLOW.md`

- [ ] **Step 1: Confirm MessageRow maps multi-attachment**

Run:
```bash
cd /Users/malibo/MyDev/AgenticOps
grep -n "attachments.map\|msg.attachments" src/agenticops/web/frontend/src/components/chat/MessageList.tsx
```
Expected: a `.map` over `msg.attachments` already exists (renders N badges). If it maps,
NO code change. If it indexes `[0]` only, update it to `.map` (show the actual change in the
commit). Report which case.

- [ ] **Step 2: Update WORKFLOW.md Chat Preprocessing section**

In `docs/WORKFLOW.md`, find the "## Chat Preprocessing Pipeline" section. Append a short note
after its diagram (before the closing `---`):

```markdown
**Web composer input (v1.1.x):** the chat composer accepts pasted images (`Cmd+V`),
drag-dropped files, and the file picker — up to 5 attachments per message (accepted types
only; per-type size caps mirror `file_reader.py`: 512 KB text / 5 MB image / 5 MB document).
All attachments post as one multipart request (`file` repeated); the backend reads
`form.getlist("file")` and builds Strands ContentBlocks per file.
```

- [ ] **Step 3: Commit docs**

```bash
cd /Users/malibo/MyDev/AgenticOps
git add docs/WORKFLOW.md
# include MessageList.tsx only if Step 1 required a change:
# git add src/agenticops/web/frontend/src/components/chat/MessageList.tsx
git commit --no-verify -m "docs: note web paste/drag-drop + multi-attachment in WORKFLOW"
```

- [ ] **Step 4: Final full verification**

Run:
```bash
cd /Users/malibo/MyDev/AgenticOps
.venv/bin/python -m pytest tests/test_chat_multi_attachment.py tests/test_chat_api.py tests/test_chat_messages_pagination.py -q
cd src/agenticops/web/frontend && npx tsc --noEmit && npm run build && npm run test
```
Expected: backend green, tsc clean, build OK, vitest green.

- [ ] **Step 5: Manual smoke (record results)**

`uvicorn agenticops.web.app:app --reload --port 8000` + `npm run dev`. Verify:
- `Cmd+Shift+4` screenshot → `Cmd+V` in composer → image badge → send → agent sees it.
- Drag 2 files → 2 badges → send → both in the message.
- **Drag a file IN then back OUT** (cursor leaves the window) → highlight clears, NOT stuck
  (open-webui Firefox bug #21664). Test in **Firefox/Safari** specifically.
- **Drag over child elements** (textarea, buttons, badges) → highlight does NOT flicker
  (contains-guard).
- Drop 6 files → 5 accepted + "too many files (max 5)" message.
- Drop a `.exe` → "type not supported", not sent.
- **Paste the same screenshot twice** → only one badge (dedup by name+size, no error).
- Remove the middle of 3 attachments → correct one removed (id-keyed, not index).
- Paste plain text → goes into the textarea (not an attachment).
- Press **Escape** mid-drag → highlight clears.

---

## Self-Review Notes (author)

- **Spec coverage:** paste (T5 handlePaste), drag-drop (T5 capture-phase useEffect + isDragging), multi-attachment array (T1 state→T5 UI→T3 send chain→T2 backend), max 5 (T1 validateFiles), ACCEPTED_TYPES only + client reject (T1 validateFiles + acceptAttr), per-type size caps mirroring file_reader (T1 maxSizeForFile: 512KB/5MB/5MB by true backend routing), backend form.getlist loop (T2), preprocessor/file_reader/model untouched (T2 note), MessageList multi-badge (T6), docs (T6). All spec sections map to a task.
- **open-webui patterns adopted (header list 1-10):** dragover-state (T5 onDragOver), contains-guard dragleave (T5 onDragLeave), Escape+drop reset (T5), capture-phase + matching cleanup (T5 useEffect opts), selective preventDefault paste (T5 handlePaste), single addFiles ingress (T5), validate-before-FormData (T1/T5), dataURL-not-objectURL (N/A — filename badges only this phase, noted), dedup by name+size (T1 validateFiles + tests), id-keyed removal not index (T5 Attachment.id/nextAttachId), allow files+empty-text (T5 fallback). Each guards a real open-webui bug (#21968 leak, #21664 Firefox stuck, #10f06a64 dup, #21477 dropped-file, bug G index-race).
- **Type consistency:** `onSend(message, files: File[])` (ChatInput) ↔ `sendMessage`/`handleWelcomeSend(content, files)` (Chat.tsx) ↔ `useSessionStream.send(content, files?, detailLevel?)` ↔ `chatStream.send(sessionId, content, files?, detailLevel?)` ↔ `sendFirstMessage(content, files?, detailLevel?)`. All `File[]`. `attachments` optimistic shape `{filename,size}` matches `types.ts:577` and backend dict keys (`filename`,`size`,`type` — frontend reads only filename/size). `validateFiles(existing, incoming)`, `filesFromPaste(ClipboardLike)`, `filesFromDrop(DataTransferLike)`, `maxSizeForFile(name)`, `acceptAttr`, `fileKey(f)` — names consistent T1↔T5. ChatInput uses internal `Attachment{id,file}` state (id from module counter `nextAttachId`); `onSend` still receives a plain `File[]` (`attachments.map(a => a.file)`), so the send-chain contract is unchanged.
- **node-env test safety:** pure fns take structural `ClipboardLike`/`DataTransferLike` (not DOM `DataTransfer`, which is undefined in node) — tests use plain object fixtures + `File` global. The drag listeners (which need real DOM events) live in `ChatInput` (not unit-tested — verified via manual smoke), keeping the testable logic pure.
- **Task 4 intentionally void** (numbering kept stable; attachments.ts consumed in T5).
- **Commit grouping:** T3 leaves tree non-compiling by design; T5 commits T3+T5 frontend together after tsc passes (noted in T3 Step 4).
