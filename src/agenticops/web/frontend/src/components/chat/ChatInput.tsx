import { useState, useRef, useEffect, useCallback, useMemo } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  FALLBACK_POLICY,
  attachmentErrorReason,
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
import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { ModelSelector } from "./ModelSelector";
import { ComposerAttachment, type RejectedFile } from "./ComposerAttachment";
import { ImageLightbox } from "./ImageLightbox";
import { attachmentBlobUrl, localPreviewUrl } from "@/hooks/useAttachmentBlob";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { shouldSend } from "@/lib/composerKeys";
import { humanSize } from "@/lib/attachments";

interface Props {
  /** → whether the message was taken (S5): false gives the text and the attachments back to the composer */
  onSend: (message: string, attachmentIds: string[], attachments: UploadItem[]) => void | Promise<boolean>;
  onCancel?: () => void;
  disabled?: boolean;
  streaming?: boolean;
  sessionId?: string | null;
  /** S5: put this text in the composer (a starter prompt); a new nonce applies it again. Never sends. */
  prefill?: { text: string; nonce: number } | null;
  /** 2026-11-07: files dropped anywhere on this element are attached (the chat column); default = the composer */
  dropTargetRef?: React.RefObject<HTMLElement>;
  /** a file is being dragged over the drop target — the page draws the hint */
  onDragChange?: (dragging: boolean) => void;
  /** "center": the welcome page's composer, in the middle of the page */
  layout?: "dock" | "center";
}

const PREVIEWABLE = /^image\/(png|jpeg|gif|webp|bmp)$/;

let pasteSeq = 0;

export function ChatInput({ onSend, onCancel, disabled, streaming, sessionId, prefill, dropTargetRef, onDragChange,
                           layout = "dock" }: Props) {
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
  // files the composer refused: shown in the box, in red, with the reason, until removed or the message is sent
  const [rejected, setRejected] = useState<RejectedFile[]>([]);
  const [lightbox, setLightbox] = useState<number | null>(null);
  const coarse = useMediaQuery("(pointer: coarse)");
  // the server's thumbnail when this browser cannot show the file itself: an upload restored after a refresh (no
  // local file), or a HEIC / TIFF picture
  const [thumbs, setThumbs] = useState<Record<string, string>>({});
  useEffect(() => {
    for (const i of items) {
      const local = i.file && /^image\/(png|jpeg|gif|webp|bmp)$/.test(i.file.type);
      if (i.serverId && !local && i.kind === "image" && i.state === "ready" && !thumbs[i.serverId]) {
        const id = i.serverId;
        attachmentBlobUrl(id, "thumb").then((url) => setThumbs((cur) => ({ ...cur, [id]: url })), () => {});
      }
    }
  }, [items, thumbs]);
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
  const imageInputRef = useRef<HTMLInputElement>(null);
  const cameraInputRef = useRef<HTMLInputElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const addFiles = useCallback((incoming: File[], pasted = false) => {
    if (incoming.length === 0) return;
    // a pasted screenshot is "image.png" every time: give it a dated name BEFORE the duplicate check
    const files = pasted ? incoming.map((f) => normalizePastedName(f, new Date(), ++pasteSeq)) : incoming;
    const { accepted, errors } = validateFiles(queue.items(), files, rules);
    if (errors.length > 0) {
      setRejected((cur) => [...cur, ...errors.map((e) => ({
        key: `${Date.now()}-${++pasteSeq}`, name: "name" in e ? e.name : "",
        // a card per file names it already; a count / total refusal has no file name, so it keeps the whole sentence
        text: "name" in e ? attachmentErrorReason(e, t) : attachmentErrorText(e, t) }))]);
    }
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
    setRejected([]);
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
  useEffect(() => { onDragChange?.(isDragging); }, [isDragging, onDragChange]);

  useEffect(() => {
    const el = dropTargetRef?.current ?? containerRef.current;
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
  }, [disabled, addFiles, dropTargetRef]);

  const thumbFor = (i: UploadItem) => (i.file && PREVIEWABLE.test(i.file.type) ? localPreviewUrl(i.localId, i.file)
    : i.serverId && i.kind === "image" && i.state === "ready" ? thumbs[i.serverId] : undefined);
  const readyImages = items.filter((i) => i.kind === "image" && i.state === "ready" && i.serverId);
  const used = items.reduce((sum, i) => sum + i.size, 0);
  const canSend = (!!input.trim() || items.some((i) => i.serverId && (i.state === "ready" || i.state === "failed")))
    && !disabled && !uploading;
  const menuItem = "flex cursor-pointer select-none items-center gap-2 rounded px-2.5 py-1.5 text-sm text-foreground outline-none data-[highlighted]:bg-selected";
  const pick = (ref: React.RefObject<HTMLInputElement>) => () => ref.current?.click();

  return (
    <div ref={containerRef}
         className={layout === "center" ? "w-full" : "px-4 pb-[max(env(safe-area-inset-bottom),0.75rem)] pt-2"}>
      <div className="mx-auto max-w-[760px]">
        <div className={`rounded-3xl border bg-background px-3 pb-2 pt-2.5 shadow-[0_2px_12px_rgba(30,64,175,0.07)] transition-shadow focus-within:ring-2 focus-within:ring-primary-500/30 dark:shadow-[0_2px_12px_rgba(0,0,0,0.4)] ${
          isDragging && !dropTargetRef ? "border-primary ring-2 ring-primary/30" : "border-border"}`}>
          <input ref={fileInputRef} type="file" multiple className="hidden" accept={rules.accept || undefined} onChange={handleFileSelect} />
          <input ref={imageInputRef} type="file" multiple className="hidden" accept="image/*" onChange={handleFileSelect} />
          <input ref={cameraInputRef} type="file" className="hidden" accept="image/*" capture="environment" onChange={handleFileSelect} />

          {(items.length > 0 || rejected.length > 0) && (
            <div className="mb-2 flex flex-wrap gap-2 max-[767px]:flex-nowrap max-[767px]:overflow-x-auto max-[767px]:pb-1">
              {items.map((i) => (
                <ComposerAttachment key={i.localId} item={i} thumbUrl={thumbFor(i)}
                                    onRemove={() => queue.remove(i.localId)} onRetry={() => queue.retry(i.localId)}
                                    onOpen={i.serverId && i.kind === "image" && i.state === "ready"
                                      ? () => setLightbox(readyImages.findIndex((r) => r.localId === i.localId)) : undefined} />
              ))}
              {rejected.map((r) => (
                <ComposerAttachment key={r.key} rejected={r} onRemove={() => setRejected((cur) => cur.filter((x) => x.key !== r.key))} />
              ))}
            </div>
          )}

          <textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onPaste={handlePaste}
            onKeyDown={(e) => {
              if (shouldSend(e.nativeEvent, coarse)) {
                e.preventDefault();
                handleSend();
              }
            }}
            placeholder={t("chat.input.placeholder")}
            disabled={disabled}
            rows={1}
            className="block max-h-52 w-full resize-none overflow-y-auto border-none bg-transparent px-1.5 py-1.5 text-[15px] text-foreground placeholder:text-muted-foreground/60 focus:outline-none disabled:opacity-50"
          />

          <div className="mt-1 flex items-center gap-1.5">
            <DropdownMenu.Root>
              <DropdownMenu.Trigger asChild>
                <button type="button" disabled={disabled} aria-label={t("chat.attach.menu")} title={t("chat.attach.menu")}
                        className="flex h-9 w-9 items-center justify-center rounded-full text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-50 max-[767px]:h-[44px] max-[767px]:w-[44px]">
                  <svg className="h-5 w-5" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden><path d="M10 4v12M4 10h12" /></svg>
                </button>
              </DropdownMenu.Trigger>
              <DropdownMenu.Portal>
                <DropdownMenu.Content side="top" align="start" sideOffset={6}
                                      className="z-50 min-w-[180px] rounded-md border border-border bg-card p-1.5 shadow-lg animate-[slideInRight_0.2s_ease-out]">
                  <DropdownMenu.Item className={menuItem} onSelect={pick(fileInputRef)}>{t("chat.attach.files")}</DropdownMenu.Item>
                  <DropdownMenu.Item className={menuItem} onSelect={pick(imageInputRef)}>{t("chat.attach.images")}</DropdownMenu.Item>
                  {coarse && <DropdownMenu.Item className={menuItem} onSelect={pick(cameraInputRef)}>{t("chat.attach.camera")}</DropdownMenu.Item>}
                </DropdownMenu.Content>
              </DropdownMenu.Portal>
            </DropdownMenu.Root>
            <span className="min-w-0 flex-1 truncate text-[11px] text-muted-foreground">
              {items.length > 0 && t("chat.attach.counter").replace("{n}", String(items.length)).replace("{max}", String(rules.max))
                .replace("{used}", humanSize(used)).replace("{total}", humanSize(rules.maxTotalBytes))}
            </span>
            <ModelSelector sessionId={sessionId ?? null} disabled={disabled || streaming} />
            {streaming ? (
              <button type="button" onClick={onCancel} title={t("chat.stop")} aria-label={t("chat.stop")}
                      className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-foreground text-background hover:opacity-85 max-[767px]:h-[44px] max-[767px]:w-[44px]">
                <span className="h-3 w-3 rounded-[3px] bg-background" />
              </button>
            ) : (
              <button type="button" onClick={handleSend} disabled={!canSend}
                      title={uploading ? t("chat.attach.waitUpload") : t("chat.send")} aria-label={t("chat.send")}
                      className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-primary-600 text-white transition-colors hover:bg-primary-700 disabled:bg-muted disabled:text-muted-foreground/50 max-[767px]:h-[44px] max-[767px]:w-[44px]">
                <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden>
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 10l7-7m0 0l7 7m-7-7v18" />
                </svg>
              </button>
            )}
          </div>
        </div>
      </div>
      {lightbox !== null && readyImages[lightbox] && (
        <ImageLightbox images={readyImages.map((i) => ({ id: i.serverId!, filename: i.name }))} index={lightbox}
                       onIndex={setLightbox} onClose={() => setLightbox(null)} />
      )}
    </div>
  );
}
