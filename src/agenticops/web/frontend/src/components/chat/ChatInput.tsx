import { useState, useRef, useEffect, useCallback, useMemo } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  FALLBACK_POLICY,
  attachmentErrorText,
  attachmentRules,
  filesFromPaste,
  filesFromDrop,
  normalizePastedName,
  validateFiles,
} from "@/lib/attachments";
import { UploadQueue, type UploadItem } from "@/lib/attachmentUpload";
import { bootstrapKey, useBootstrap } from "@/hooks/useBootstrap";
import { useLocale } from "@/i18n/LocaleContext";
import { draftKey, loadDraft, saveDraft, sessionQueues } from "@/lib/chatDrafts";
import { currentUserId } from "@/lib/home";
import { ModelSelector } from "./ModelSelector";
import { AttachmentTray } from "./AttachmentTray";

interface Props {
  /** → whether the message was taken (S5): false gives the text and the attachments back to the composer */
  onSend: (message: string, attachmentIds: string[], attachments: UploadItem[]) => void | Promise<boolean>;
  onCancel?: () => void;
  disabled?: boolean;
  streaming?: boolean;
  sessionId?: string | null;
  /** S5: put this text in the composer (a starter prompt); a new nonce applies it again. Never sends. */
  prefill?: { text: string; nonce: number } | null;
}

let pasteSeq = 0;

export function ChatInput({ onSend, onCancel, disabled, streaming, sessionId, prefill }: Props) {
  const { t } = useLocale();
  const qc = useQueryClient();
  // what the server accepts (bootstrap upload_policy — the upload limits in force), so composer and server agree
  const boot = useBootstrap();
  const policy = boot.data?.upload_policy ?? FALLBACK_POLICY;
  const rules = useMemo(() => attachmentRules(policy), [policy]);
  // S5: the draft belongs to this installation, user and chat ("new" = the welcome composer)
  const filesKey = sessionId ?? "new";
  const key = draftKey(boot.data?.deployment_id, currentUserId(), filesKey);
  const [input, setInput] = useState(() => loadDraft(localStorage, key).text);
  // 2026-11-07: attachments upload the moment they are attached; each chat keeps its queue in memory
  const queue = useMemo(() => sessionQueues.get(filesKey, () => new UploadQueue({
    onLimitError: () => { void qc.invalidateQueries({ queryKey: bootstrapKey() }); },
  })), [filesKey, qc]);
  const [items, setItems] = useState<UploadItem[]>(() => queue.items());
  useEffect(() => {
    setItems(queue.items());
    return queue.listen(setItems);
  }, [queue]);
  const [attachError, setAttachError] = useState<string | null>(null);
  const loadedKey = useRef<string | null>(null);

  // Switching chats (or the bootstrap arriving with the installation id) loads that chat's draft; its uploads come
  // back from the server when this tab no longer has them (a refresh)
  useEffect(() => {
    if (loadedKey.current === key) return;
    loadedKey.current = key;
    const d = loadDraft(localStorage, key);
    setInput(d.text);
    if (queue.items().length === 0 && d.attachmentIds.length > 0) void queue.restore(d.attachmentIds);
  }, [key, queue]);

  useEffect(() => {
    if (!prefill) return;
    setInput(prefill.text);
    textareaRef.current?.focus();
  }, [prefill]);

  // Every edit is kept: the text and the server ids of the uploads
  useEffect(() => {
    if (loadedKey.current !== key) return;
    saveDraft(localStorage, key, { text: input, attachmentIds: items.filter((i) => i.serverId).map((i) => i.serverId!) });
  }, [input, items, key]);
  const [isDragging, setIsDragging] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const addFiles = useCallback((incoming: File[], pasted = false) => {
    if (incoming.length === 0) return;
    // a pasted screenshot is "image.png" every time: give it a dated name BEFORE the duplicate check
    const files = pasted ? incoming.map((f) => normalizePastedName(f, new Date(), ++pasteSeq)) : incoming;
    const { accepted, errors } = validateFiles(queue.items(), files, rules);
    setAttachError(errors.length > 0 ? errors.map((e) => attachmentErrorText(e, t)).join("; ") : null);
    if (accepted.length > 0) queue.add(accepted);
  }, [queue, rules, t]);

  // Auto-grow the textarea up to its max height (open-webui-style), then scroll.
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  }, [input]);

  const uploading = items.some((i) => i.state === "queued" || i.state === "uploading" || i.state === "processing");
  const handleSend = () => {
    const trimmed = input.trim();
    const ids = queue.readyIds();
    if ((!trimmed && ids.length === 0) || disabled || uploading) return;
    const sentText = input;
    const taken = queue.take();
    const content = trimmed || `Please analyze the attached file(s): ${taken.map((i) => i.name).join(", ")}`;
    const result = onSend(content, ids, taken);
    setInput("");
    setAttachError(null);
    saveDraft(localStorage, key, { text: "", attachmentIds: [] });
    // S5: the draft is gone only once the server took the message — a refused send gives it back
    if (result instanceof Promise) {
      void result.then((ok) => {
        if (ok) return;
        queue.putBack(taken);
        if (loadedKey.current === key) setInput((cur) => cur || sentText);
      });
    }
  };

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) addFiles(Array.from(e.target.files));
    e.target.value = ""; // allow re-selecting the same file
  };

  // Paste: every pasted file (any type); only preventDefault when we take a file, so a text paste still works
  const handlePaste = (e: React.ClipboardEvent<HTMLTextAreaElement>) => {
    const files = filesFromPaste(e.clipboardData);
    if (files.length > 0) {
      e.preventDefault();
      addFiles(files, true);
    }
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
      <AttachmentTray items={items} rules={rules} onRemove={(id) => queue.remove(id)} onRetry={(id) => queue.retry(id)} />

      {attachError && (
        <div className="max-w-[760px] mx-auto mb-2 text-xs text-red-500">{attachError}</div>
      )}

      <div className="max-w-[760px] mx-auto">
        <div className="flex items-center gap-1.5 rounded-3xl border border-border bg-background shadow-[0_2px_12px_rgba(30,64,175,0.07)] dark:shadow-[0_2px_12px_rgba(0,0,0,0.4)] px-2 py-1.5 focus-within:ring-2 focus-within:ring-primary-500/30 transition-shadow">
          {/* Hidden file input (multiple) */}
          <input
            ref={fileInputRef}
            type="file"
            multiple
            className="hidden"
            accept={rules.accept || undefined}
            onChange={handleFileSelect}
          />

          {/* Per-session model selector */}
          <ModelSelector sessionId={sessionId ?? null} disabled={disabled || streaming} />

          {/* Attach button */}
          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={disabled}
            className="self-center w-8 h-8 flex items-center justify-center rounded-full text-muted-foreground hover:text-primary-600 hover:bg-muted disabled:opacity-50 transition-colors"
            title={t("chat.attach.button")} aria-label={t("chat.attach.button")}
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13" />
            </svg>
          </button>

          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onPaste={handlePaste}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                e.preventDefault();
                handleSend();
              }
            }}
            placeholder={t("chat.input.placeholder")}
            disabled={disabled}
            rows={1}
            className="flex-1 bg-transparent border-none px-2 py-2 text-sm text-foreground placeholder:text-muted-foreground/50 focus:outline-none resize-none disabled:opacity-50 max-h-40 overflow-y-auto"
          />
          {streaming ? (
            <button
              onClick={onCancel}
              className="self-center w-9 h-9 flex items-center justify-center bg-red-500 hover:bg-red-600 text-white rounded-full transition-colors flex-shrink-0"
              title={t("chat.stop")} aria-label={t("chat.stop")}
            >
              <span className="w-3 h-3 bg-white rounded-sm" />
            </button>
          ) : (
            <button
              onClick={handleSend}
              disabled={(!input.trim() && items.length === 0) || disabled || uploading}
              className="self-center w-9 h-9 flex items-center justify-center bg-primary-600 hover:bg-primary-700 disabled:bg-muted disabled:text-muted-foreground/40 text-white rounded-full transition-colors flex-shrink-0"
              title={t("chat.send")} aria-label={t("chat.send")}
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 10l7-7m0 0l7 7m-7-7v18" />
              </svg>
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
