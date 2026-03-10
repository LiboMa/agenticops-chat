import { useState, useRef } from "react";

interface Props {
  onSend: (message: string, file?: File) => void;
  onCancel?: () => void;
  disabled?: boolean;
  streaming?: boolean;
  detailLevel?: string;
  onDetailLevelChange?: (level: string) => void;
}

const ACCEPTED_TYPES = ".txt,.log,.md,.json,.yaml,.yml,.csv,.pdf,.docx,.png,.jpg,.jpeg,.py,.sh,.xml,.tf";

export function ChatInput({ onSend, onCancel, disabled, streaming, detailLevel, onDetailLevelChange }: Props) {
  const [input, setInput] = useState("");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleSend = () => {
    const trimmed = input.trim();
    if ((!trimmed && !selectedFile) || disabled) return;
    onSend(trimmed || `Please analyze the attached file`, selectedFile ?? undefined);
    setInput("");
    setSelectedFile(null);
  };

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) setSelectedFile(file);
    e.target.value = "";
  };

  return (
    <div className="border-t border-slate-200 p-4 bg-slate-50">
      {/* File attachment indicator */}
      {selectedFile && (
        <div className="flex items-center gap-2 mb-2 max-w-4xl mx-auto">
          <span className="inline-flex items-center gap-1.5 text-xs bg-primary-50 text-primary-700 px-2.5 py-1 rounded-lg border border-primary-200">
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13" />
            </svg>
            {selectedFile.name}
            <span className="text-primary-400">({(selectedFile.size / 1024).toFixed(1)} KB)</span>
          </span>
          <button
            onClick={() => setSelectedFile(null)}
            className="text-xs text-slate-400 hover:text-red-500 transition-colors"
          >
            Remove
          </button>
        </div>
      )}

      <div className="flex gap-3 max-w-4xl mx-auto">
        {/* Hidden file input */}
        <input
          ref={fileInputRef}
          type="file"
          className="hidden"
          accept={ACCEPTED_TYPES}
          onChange={handleFileSelect}
        />

        {/* Detail level selector */}
        {onDetailLevelChange && (
          <select
            value={detailLevel ?? "medium"}
            onChange={(e) => onDetailLevelChange(e.target.value)}
            disabled={disabled}
            className="self-end text-xs border border-slate-200 rounded-lg px-2 py-2.5 text-slate-600 bg-white focus:outline-none focus:ring-2 focus:ring-primary-500 disabled:opacity-50"
            title="Response detail level"
          >
            <option value="concise">Concise</option>
            <option value="medium">Medium</option>
            <option value="detailed">Detailed</option>
          </select>
        )}

        {/* Paperclip / attach button */}
        <button
          onClick={() => fileInputRef.current?.click()}
          disabled={disabled}
          className="self-end px-2.5 py-2.5 text-slate-400 hover:text-primary-600 disabled:opacity-50 transition-colors rounded-lg hover:bg-slate-100"
          title="Attach file"
        >
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13" />
          </svg>
        </button>

        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              handleSend();
            }
          }}
          placeholder="Ask about AWS resources, health issues, or reports... (use I#42 for issues, R#17 for resources)"
          disabled={disabled}
          rows={2}
          className="flex-1 bg-white border border-slate-200 rounded-lg px-4 py-2.5 text-sm text-slate-900 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-primary-500 focus:border-primary-500 resize-none disabled:opacity-50 transition-shadow"
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
            disabled={(!input.trim() && !selectedFile) || disabled}
            className="px-5 py-2.5 bg-primary-600 hover:bg-primary-700 disabled:bg-slate-100 disabled:text-slate-400 disabled:cursor-not-allowed text-white text-sm font-medium rounded-lg transition-colors self-end"
          >
            Send
          </button>
        )}
      </div>
    </div>
  );
}
