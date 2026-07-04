import { useState, useRef, useEffect, useCallback } from "react";
import {
  acceptAttr,
  filesFromPaste,
  filesFromDrop,
  validateFiles,
} from "@/lib/attachments";
import { ModelSelector } from "./ModelSelector";

interface Props {
  onSend: (message: string, files: File[]) => void;
  onCancel?: () => void;
  disabled?: boolean;
  streaming?: boolean;
  sessionId?: string | null;
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

export function ChatInput({ onSend, onCancel, disabled, streaming, sessionId }: Props) {
  const [input, setInput] = useState("");
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [attachError, setAttachError] = useState<string | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

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

  // Auto-grow the textarea up to its max height (open-webui-style), then scroll.
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  }, [input]);

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

      <div className="max-w-4xl mx-auto">
        <div className="flex items-center gap-1.5 rounded-3xl border border-border bg-background shadow-[0_2px_12px_rgba(30,64,175,0.07)] dark:shadow-[0_2px_12px_rgba(0,0,0,0.4)] px-2 py-1.5 focus-within:ring-2 focus-within:ring-primary-500/30 transition-shadow">
          {/* Hidden file input (multiple) */}
          <input
            ref={fileInputRef}
            type="file"
            multiple
            className="hidden"
            accept={acceptAttr}
            onChange={handleFileSelect}
          />

          {/* Per-session model selector */}
          <ModelSelector sessionId={sessionId ?? null} disabled={disabled || streaming} />

          {/* Attach button */}
          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={disabled}
            className="self-center w-8 h-8 flex items-center justify-center rounded-full text-muted-foreground hover:text-primary-600 hover:bg-muted disabled:opacity-50 transition-colors"
            title="Attach file"
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
            placeholder="Ask about AWS resources… (paste/drag files, Cmd+Enter to send)"
            disabled={disabled}
            rows={1}
            className="flex-1 bg-transparent border-none px-2 py-2 text-sm text-foreground placeholder:text-muted-foreground/50 focus:outline-none resize-none disabled:opacity-50 max-h-40 overflow-y-auto"
          />
          {streaming ? (
            <button
              onClick={onCancel}
              className="self-center w-9 h-9 flex items-center justify-center bg-red-500 hover:bg-red-600 text-white rounded-full transition-colors flex-shrink-0"
              title="Stop"
            >
              <span className="w-3 h-3 bg-white rounded-sm" />
            </button>
          ) : (
            <button
              onClick={handleSend}
              disabled={(!input.trim() && attachments.length === 0) || disabled}
              className="self-center w-9 h-9 flex items-center justify-center bg-primary-600 hover:bg-primary-700 disabled:bg-muted disabled:text-muted-foreground/40 text-white rounded-full transition-colors flex-shrink-0"
              title="Send"
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
