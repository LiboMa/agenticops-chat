# Design: Web Chat Paste / Drag-Drop + Multi-Attachment Upload (Phase 1)

**Date:** 2026-06-03
**Status:** Approved design → ready for implementation plan
**Context:** First phase of a multi-part chat-UX improvement effort (compared against
open-webui). Later phases (out of scope here): IM image support (Feishu + Slack), the
open-webui-inspired tool-call detail / copy-button / regenerate wins, and voice (deferred —
Claude on Bedrock does not accept audio; would require AWS Transcribe/Polly).

## Problem

The web chat composer (`ChatInput.tsx`) only supports attaching a file via the 📎 file
picker, and only **one** file per message. There is no paste (`Cmd+V`) or drag-drop, so a
Mac user who screenshots an error (`Cmd+Shift+4`) cannot paste it into chat — they must
save to disk and pick it. Operators frequently want to drop several screenshots / a log +
a config into one message.

Verified current state:
- `ChatInput.tsx` has **no** `onPaste` / `onDrop` handler — only a hidden `<input type=file>` (single `selectedFile: File | null`).
- The **backend image/document link already works**: `file_reader.py` has `read_upload_image_bytes` / `read_upload_document_bytes` (5 MB image / document caps, Strands-supported formats `png/jpg/jpeg/gif/webp/bmp`), and `app.py` already builds Strands ContentBlocks from uploads.
- The backend already uses **lists** internally — `file_contents`, `file_images`, `file_documents` are all `list[...]` in the `app.py` multipart branch; it only ever appends one element because it reads a single `form.get("file")`.

So this is mostly a **frontend** change (add paste/drop + multi-file UI) plus a small
**backend** change (read `form.getlist("file")` and loop). The preprocessor, file_reader,
ChatMessage model, SSE protocol, concurrency, and pagination are **untouched**.

## Goals (user-decided)

- **Paste** (`Cmd+V`): pasted image → attachment; pasted text → normal textarea behavior.
- **Drag-drop**: drop files onto the composer → attachments, with a drag-over highlight.
- **Multiple attachments per message** (user chose array model over single-file).
- **Max 5 attachments per message** (guard against dropping a whole folder).
- **Accept only existing `ACCEPTED_TYPES`** (txt/log/md/json/yaml/yml/csv/pdf/docx/png/jpg/jpeg/py/sh/xml/tf). Unsupported types are **rejected client-side** with an inline message — request not sent.

## Non-goals (YAGNI / deferred)

- IM (Feishu/Slack) image handling — **Phase 2**.
- Voice / audio (STT/TTS) — deferred (needs Transcribe/Polly; Claude doesn't take audio).
- open-webui tool-call detail panel, copy button, regenerate, syntax highlight — separate phases.
- Changing the SSE wire protocol, preprocessor, file_reader, or ChatMessage schema.

## Architecture

Three change units (+ tests). Each has one clear responsibility.

### Unit 1 — Attachment selection logic (pure, testable)

**New file:** `src/agenticops/web/frontend/src/lib/attachments.ts`

Pure functions extracted so the ergonomics are unit-testable without DOM rendering
(matching the existing `sessionSort.prop.test.ts` node-env style):

```
ACCEPTED_EXTENSIONS: string[]           // single source, shared with ChatInput accept=""
MAX_ATTACHMENTS = 5

// Per-type size caps — MUST mirror file_reader.py exactly so client-side
// validation matches the backend (else a file passes the client and 400s server-side):
//   text   (txt/log/md/json/yaml/yml/csv/py/sh/xml/tf): 512 KB   (file_reader MAX_FILE_SIZE)
//   image  (png/jpg/jpeg/gif/webp/bmp):                 5 MB     (MAX_IMAGE_SIZE)
//   document (pdf/docx):                                5 MB     (MAX_DOCUMENT_SIZE)
maxSizeForFile(name: string): number    // returns the right cap by extension class

filesFromPaste(clipboard: DataTransfer): File[]   // image/* items → File; ignore text
filesFromDrop(dataTransfer: DataTransfer): File[]  // dropped files
validateFiles(existing: File[], incoming: File[]): { accepted: File[]; errors: string[] }
   // rejects: unsupported extension, size > maxSizeForFile(name), would exceed MAX_ATTACHMENTS
```

`validateFiles` returns accepted files + human-readable error strings (e.g.
`"unsupported.exe: type not supported"`, `"app.log: too large (max 512 KB)"`,
`"too many files (max 5)"`). The three caps mirror `file_reader.py` (`MAX_FILE_SIZE`=512 KB
text, `MAX_IMAGE_SIZE`=5 MB, `MAX_DOCUMENT_SIZE`=5 MB) so client validation never disagrees
with the server.

### Unit 2 — Composer UI (`ChatInput.tsx`)

- State: `selectedFile: File | null` → `selectedFiles: File[]`.
- `onPaste` on the textarea: `filesFromPaste(e.clipboardData)`; if any images found,
  `e.preventDefault()` and add via `validateFiles`; pasted plain text falls through to
  default textarea insertion.
- `onDrop` / `onDragOver` / `onDragLeave` on the composer container: `filesFromDrop`, add
  via `validateFiles`; `isDragging` state drives a highlight ring.
- Render N attachment badges (filename + size + per-badge remove ✕), reusing the existing
  badge styling; show validation errors inline (red text, transient).
- `accept` on the hidden input + the `multiple` attribute (picker can also select several).
- `onSend(message, files)` — prop signature `file?: File` → `files: File[]`.

### Unit 3 — Send path (frontend) + endpoint (backend)

**Frontend send chain** (signatures change `file?: File` → `files?: File[]`):
- `chatStream.send(sessionId, content, files?, detailLevel?)` — build `FormData`, loop
  `files.forEach(f => formData.append("file", f))` (same field name, multiple values).
- `useSessionStream.send` — pass `files`; optimistic user bubble `attachments` becomes a
  multi-element array (`ChatMessage.attachments` is already a list type).
- `useLazySessionCreate.sendFirstMessage(content, files?, detailLevel?)` — same.

**Backend** (`app.py` multipart branch only):
- `form.get("file")` → `form.getlist("file")`; loop each upload through the **existing**
  `is_image_file` / `is_document_file` / else-text classification into the **already-list**
  `file_images` / `file_documents` / `file_contents`.
- `attachments` accumulates one dict per file (already a JSON list on `ChatMessage`).
- `preprocess_message` already accepts these lists → **no change**. `file_reader.py` → **no change**. `ChatMessage` model → **no change**.

### Frontend display (`MessageList.tsx`)

`MessageRow` already maps `msg.attachments` as badges — it works for N today; just confirm
the optimistic + persisted multi-attachment arrays render. Minimal/no change.

## Data Flow

```
paste image / drop files
  → filesFromPaste/Drop → validateFiles → ChatInput.selectedFiles[]
  → onSend(msg, files[])
  → chatStream: FormData(content + file×N) → POST /api/chat/sessions/{id}/messages (multipart)
  → app.py form.getlist("file") loop → file_images[]/file_documents[]/file_contents[]
  → preprocess_message (already list-aware) → Strands ContentBlocks → agent.stream_async
```

## Error Handling

- **Client-side first**: `validateFiles` rejects unsupported type / oversize / over-count
  before any request; errors shown inline; only valid files are sent.
- **Server-side backstop**: each upload still runs through `read_upload_image_bytes` /
  `read_upload_document_bytes`, which return errors → existing `HTTPException(400)`. Per-file,
  so one bad file reports specifically.
- **Partial selection**: if 3 of 5 dropped files are valid, the 3 are accepted and the
  invalid ones reported; user decides whether to send.
- Empty content + ≥1 attachment is allowed (existing behavior: auto-fills "analyze the
  attached file"); generalize the placeholder to plural when >1.

## Testing

**Frontend (vitest, node env — no DOM rendering, matches existing style):**
- `attachments.test.ts`: `filesFromPaste` extracts `image/*` and ignores text items;
  `filesFromDrop` returns dropped files; `validateFiles` — accepts supported types, rejects
  unsupported extension, rejects oversize, caps at MAX_ATTACHMENTS, dedups against existing.
  (Construct `File`/`DataTransfer`-like fixtures; these exist in the vitest/node globals.)

**Backend (pytest):**
- `POST /api/chat/sessions/{id}/messages` multipart with **two** files (1 png + 1 .txt):
  assert both land in `attachments` (len 2) and a mocked agent receives enriched content
  with both blocks. Follow the `tests/test_chat_api.py` TestClient + seed/cleanup pattern.
  (Reuse a `_BoomAgent`-style monkeypatch on `_chat_sessions.get_or_create` to capture the
  `enriched_content` passed to `stream_async`.)

**Manual:** Mac `Cmd+Shift+4` screenshot → `Cmd+V` into composer → image badge appears →
send → agent sees it. Drag 2 files in → 2 badges → send. Drop 6 files → 5 accepted + "max 5"
message. Drop a `.exe` → rejected inline.

## Scope Guardrails

- **Touched:** `lib/attachments.ts` (new), `ChatInput.tsx`, `chatStream.ts`,
  `useSessionStream.ts`, `useLazySessionCreate.ts`, `MessageList.tsx` (verify only),
  `api/types.ts` (prop/types), `app.py` (multipart loop), + `attachments.test.ts` (new),
  + backend pagination/chat test file (add multi-file case).
- **Untouched:** SSE protocol, `preprocessor.py`, `file_reader.py`, `ChatMessage` model,
  concurrency (`chatStream` core loop), pagination, IM gateways, voice.
- **One source of truth** for accepted types + limits lives in `lib/attachments.ts`; the
  `<input accept>` string derives from it (no duplicate list).

## Documentation (per CLAUDE.md rule 7)

After implementation, update `docs/WORKFLOW.md` (Chat Preprocessing Pipeline section — note
paste/drop + multi-attachment) and reference in the next release notes.
