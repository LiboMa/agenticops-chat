import { useState, useRef, useCallback, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import {
  useSkills,
  useGenerateSkill,
  useSaveDraft,
  useImportSkill,
  useImportSkillSource,
  useSkillImprovements,
  useSkillImprovementHistory,
  useBatchDismissImprovements,
} from "@/hooks/useSkills";
import { ApiError } from "@/api/client";
import { Card, CardBody } from "@/components/ui/Card";
import { Spinner } from "@/components/ui/Spinner";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import { useLocale } from "@/i18n/LocaleContext";
import { detectSkillSource, parseSkillNames, type SkillSourceKind } from "@/lib/skillSource";
import type {
  Skill,
  SkillGenerateResponse,
  SkillImprovementRecord,
  SkillImportSourceResult,
} from "@/api/types";

type Filter = "all" | "published" | "draft";

function SkillStatusBadge({ isDraft }: { isDraft: boolean }) {
  return isDraft ? (
    <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-amber-100 text-amber-700">
      Draft
    </span>
  ) : (
    <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-emerald-100 text-emerald-700">
      Published
    </span>
  );
}

function DomainBadge({ domain }: { domain: string }) {
  return (
    <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-secondary text-muted-foreground">
      {domain}
    </span>
  );
}

/** Marks a skill that arrived via URL / git / zip; hover shows where it came from. */
function ImportedBadge({ sourceUri }: { sourceUri: string | null }) {
  const { t } = useLocale();
  return (
    <span
      title={sourceUri ?? undefined}
      className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-violet-100 text-violet-700"
    >
      {t("skills.imported")}
    </span>
  );
}

/* -- Create Skill Dialog ------------------------------------------- */

function CreateSkillDialog({ onClose }: { onClose: () => void }) {
  const { t } = useLocale();
  const [description, setDescription] = useState("");
  const [generated, setGenerated] = useState<SkillGenerateResponse | null>(null);
  const generateMut = useGenerateSkill();
  const saveMut = useSaveDraft();

  const handleGenerate = () => {
    generateMut.mutate(
      { description },
      { onSuccess: (data) => setGenerated(data) },
    );
  };

  const handleSave = () => {
    if (!generated) return;
    saveMut.mutate(
      {
        name: generated.name,
        description: generated.description,
        content: generated.full_content,
        references: generated.references,
      },
      { onSuccess: () => onClose() },
    );
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/30" onClick={onClose} />
      <div className="relative bg-background rounded-xl shadow-xl w-full max-w-lg mx-4 max-h-[80vh] flex flex-col">
        <div className="px-6 py-4 border-b border-border flex items-center justify-between">
          <h3 className="text-lg font-semibold text-foreground">{t("skills.create")}</h3>
          <button onClick={onClose} className="text-muted-foreground hover:text-foreground text-xl leading-none">&times;</button>
        </div>
        <div className="px-6 py-4 space-y-4 overflow-y-auto flex-1">
          {!generated ? (
            <>
              <div>
                <label className="text-sm font-medium text-foreground block mb-1">
                  Describe the skill you want to create
                </label>
                <textarea
                  className="w-full border border-border rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-primary-500 focus:border-primary-500 outline-none resize-none"
                  rows={4}
                  placeholder="e.g. A skill for troubleshooting Redis cluster issues including replication lag, memory pressure, and failover procedures"
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                />
              </div>
              {generateMut.isError && (
                <div className="text-sm text-red-600 bg-red-50 px-3 py-2 rounded">{generateMut.error.message}</div>
              )}
            </>
          ) : (
            <>
              <div className="space-y-2">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium text-foreground">{generated.name}</span>
                  <DomainBadge domain="draft" />
                </div>
                <p className="text-sm text-muted-foreground">{generated.description}</p>
              </div>
              <div>
                <label className="text-xs text-muted-foreground block mb-1">Content Preview</label>
                <pre className="bg-secondary border border-border rounded-lg p-3 text-xs text-foreground max-h-60 overflow-y-auto whitespace-pre-wrap">
                  {generated.body_preview}
                </pre>
              </div>
              {Object.keys(generated.references).length > 0 && (
                <div>
                  <label className="text-xs text-muted-foreground block mb-1">
                    References ({Object.keys(generated.references).length})
                  </label>
                  <ul className="text-xs text-muted-foreground space-y-0.5">
                    {Object.keys(generated.references).map((r) => (
                      <li key={r}>{r}</li>
                    ))}
                  </ul>
                </div>
              )}
              {saveMut.isError && (
                <div className="text-sm text-red-600 bg-red-50 px-3 py-2 rounded">{saveMut.error.message}</div>
              )}
            </>
          )}
        </div>
        <div className="px-6 py-4 border-t border-border flex justify-end gap-2">
          <button onClick={onClose} className="px-4 py-2 text-sm font-medium text-muted-foreground bg-secondary rounded-lg hover:bg-muted">
            {t("common.cancel")}
          </button>
          {!generated ? (
            <button
              onClick={handleGenerate}
              disabled={!description.trim() || generateMut.isPending}
              className="px-4 py-2 text-sm font-medium text-white bg-primary-600 rounded-lg hover:bg-primary-700 disabled:opacity-50"
            >
              {generateMut.isPending ? "Generating..." : "Generate"}
            </button>
          ) : (
            <button
              onClick={handleSave}
              disabled={saveMut.isPending}
              className="px-4 py-2 text-sm font-medium text-white bg-emerald-600 rounded-lg hover:bg-emerald-700 disabled:opacity-50"
            >
              {saveMut.isPending ? t("skills.saving") : "Save as Draft"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

/* -- Import Dialog ------------------------------------------------- */

type ImportTab = "source" | "file";

// i18n key per detected source kind ("empty" renders no chip).
const SOURCE_KIND_KEY: Record<Exclude<SkillSourceKind, "empty">, string> = {
  git: "skills.importKind.git",
  "archive-url": "skills.importKind.archive-url",
  "skill-md-url": "skills.importKind.skill-md-url",
  url: "skills.importKind.url",
  "unsupported-scheme": "skills.importKind.unsupported-scheme",
  path: "skills.importKind.path",
};

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

/** Existing multipart upload path (.md / .zip) — behaviour unchanged: success closes the dialog. */
function FileImportPane({ onClose }: { onClose: () => void }) {
  const importMut = useImportSkill();
  const fileRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);

  const handleFile = useCallback(
    (file: globalThis.File) => {
      importMut.mutate(file, { onSuccess: () => onClose() });
    },
    [importMut, onClose],
  );

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragOver(false);
      const file = e.dataTransfer.files[0];
      if (file) handleFile(file);
    },
    [handleFile],
  );

  return (
    <div className="px-6 py-6">
      <div
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={handleDrop}
        onClick={() => fileRef.current?.click()}
        className={`border-2 border-dashed rounded-lg p-8 text-center cursor-pointer transition-colors ${
          dragOver ? "border-primary-400 bg-primary-50" : "border-border hover:border-muted-foreground"
        }`}
      >
        <input
          ref={fileRef}
          type="file"
          accept=".md,.zip"
          className="hidden"
          onChange={(e) => { const file = e.target.files?.[0]; if (file) handleFile(file); }}
        />
        {importMut.isPending ? (
          <Spinner label="Importing..." />
        ) : (
          <>
            <p className="text-sm text-muted-foreground">
              Drop a <code>.md</code> or <code>.zip</code> file here, or click to browse
            </p>
            <p className="text-xs text-muted-foreground mt-1">
              ZIP must contain SKILL.md + optional references/*.md
            </p>
          </>
        )}
      </div>
      {importMut.isError && (
        <div className="text-sm text-red-600 bg-red-50 px-3 py-2 rounded mt-3">{importMut.error.message}</div>
      )}
    </div>
  );
}

/** URL / git / archive import. The result is handed up so the dialog can show what landed. */
function SourceImportForm({ onImported }: { onImported: (r: SkillImportSourceResult) => void }) {
  const { t } = useLocale();
  const importMut = useImportSkillSource();
  const [uri, setUri] = useState("");
  const [showNames, setShowNames] = useState(false);
  const [namesText, setNamesText] = useState("");
  const kind = detectSkillSource(uri);

  const submit = () => {
    const trimmed = uri.trim();
    if (!trimmed || importMut.isPending) return;
    const names = parseSkillNames(namesText);
    importMut.mutate(
      { uri: trimmed, names: names.length ? names : undefined },
      { onSuccess: onImported },
    );
  };

  // 403 is the one status with a meaning of its own (import switched off server-side);
  // everything else shows the backend's own `detail` verbatim — it is the truth.
  const errorText = importMut.isError
    ? importMut.error instanceof ApiError && importMut.error.status === 403
      ? t("skills.importDisabled")
      : importMut.error.message
    : null;

  return (
    <div className="px-6 py-5 space-y-4">
      <div>
        <label className="text-sm font-medium text-foreground block mb-1">{t("skills.importSourceLabel")}</label>
        <input
          autoFocus
          type="text"
          value={uri}
          onChange={(e) => setUri(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") submit(); }}
          placeholder={t("skills.importSourcePlaceholder")}
          spellCheck={false}
          className="w-full border border-border rounded-lg px-3 py-2 text-sm font-mono focus:ring-2 focus:ring-primary-500 focus:border-primary-500 outline-none"
        />
        <p className="text-xs text-muted-foreground mt-1">{t("skills.importSourceHelp")}</p>
        {kind !== "empty" && (
          <span className="inline-flex items-center mt-2 px-2 py-0.5 rounded-full text-xs bg-secondary text-muted-foreground">
            {t(SOURCE_KIND_KEY[kind])}
          </span>
        )}
      </div>

      <div>
        <button
          type="button"
          onClick={() => setShowNames((v) => !v)}
          className="text-xs text-muted-foreground hover:text-foreground"
        >
          {showNames ? "▾" : "▸"} {t("skills.importNamesToggle")}
        </button>
        {showNames && (
          <div className="mt-2">
            <input
              type="text"
              value={namesText}
              onChange={(e) => setNamesText(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") submit(); }}
              placeholder={t("skills.importNamesPlaceholder")}
              spellCheck={false}
              className="w-full border border-border rounded-lg px-3 py-2 text-sm font-mono focus:ring-2 focus:ring-primary-500 focus:border-primary-500 outline-none"
            />
            <p className="text-xs text-muted-foreground mt-1">{t("skills.importNamesHelp")}</p>
          </div>
        )}
      </div>

      {errorText && (
        <div className="text-sm text-red-600 bg-red-50 px-3 py-2 rounded break-all">{errorText}</div>
      )}

      <div className="flex items-center justify-end pt-1">
        {importMut.isPending ? (
          <Spinner label={t("skills.importRunning")} />
        ) : (
          <button
            onClick={submit}
            disabled={!uri.trim()}
            className="px-4 py-2 text-sm font-medium text-white bg-primary-600 rounded-lg hover:bg-primary-700 disabled:opacity-50"
          >
            {t("skills.importRun")}
          </button>
        )}
      </div>
    </div>
  );
}

function ResultGroup({
  tone,
  title,
  count,
  children,
}: {
  tone: "emerald" | "amber" | "red";
  title: string;
  count: number;
  children: React.ReactNode;
}) {
  if (count === 0) return null;
  const tones = {
    emerald: "bg-emerald-50 border-emerald-200 text-emerald-800",
    amber: "bg-amber-50 border-amber-200 text-amber-800",
    red: "bg-red-50 border-red-200 text-red-800",
  };
  return (
    <div className={`rounded-lg border ${tones[tone]}`}>
      <div className="px-3 py-1.5 text-xs font-semibold border-b border-inherit">
        {title} ({count})
      </div>
      <ul className="px-3 divide-y divide-border/60">{children}</ul>
    </div>
  );
}

/** What the import did, per skill and with the backend's own reasons — the part worth reading. */
function ImportResultPanel({
  result,
  onAgain,
  onClose,
}: {
  result: SkillImportSourceResult;
  onAgain: () => void;
  onClose: () => void;
}) {
  const { t } = useLocale();
  const navigate = useNavigate();
  const ref = result.source_ref.slice(0, 12);
  const nothingInstalled = result.installed.length === 0;
  const nothingFound =
    nothingInstalled && result.skipped.length === 0 && result.rejected.length === 0;

  return (
    <>
      <div className="px-6 py-5 space-y-4 overflow-y-auto flex-1">
        <div className="text-xs text-muted-foreground break-all">
          <span className="font-mono">{result.source_uri}</span>
          {ref && <span className="ml-2 px-1.5 py-0.5 rounded bg-secondary font-mono">ref={ref}</span>}
        </div>

        {nothingInstalled && (
          <p className="text-sm font-medium text-foreground">
            {t("skills.importNothing")}
            {nothingFound && (
              <span className="block text-xs font-normal text-muted-foreground mt-1">
                {t("skills.importNoneFound")}
              </span>
            )}
          </p>
        )}

        <ResultGroup tone="emerald" title={t("skills.importInstalled")} count={result.installed.length}>
          {result.installed.map((s) => (
            <li key={s.name} className="flex items-center justify-between gap-3 py-1.5">
              <div className="min-w-0">
                <span className="font-medium text-sm text-foreground">{s.name}</span>
                <span className="ml-2 text-xs text-muted-foreground">
                  {s.files} {t("skills.importFiles")} · {formatBytes(s.bytes)}
                </span>
              </div>
              <button
                onClick={() => {
                  onClose();
                  navigate(`/app/skills/${encodeURIComponent(s.name)}`);
                }}
                className="shrink-0 text-xs font-medium text-emerald-700 hover:underline"
              >
                {t("skills.importViewPromote")}
              </button>
            </li>
          ))}
        </ResultGroup>

        <ResultGroup tone="amber" title={t("skills.importSkipped")} count={result.skipped.length}>
          {result.skipped.map((s) => (
            <li key={s.name} className="py-1.5 text-sm">
              <span className="font-medium text-foreground">{s.name}</span>
              <span className="text-muted-foreground"> — {s.reason}</span>
            </li>
          ))}
        </ResultGroup>

        <ResultGroup tone="red" title={t("skills.importRejected")} count={result.rejected.length}>
          {result.rejected.map((s) => (
            <li key={s.name} className="py-1.5 text-sm">
              <span className="font-medium text-foreground">{s.name}</span>
              <span className="text-muted-foreground"> — {s.reason}</span>
            </li>
          ))}
        </ResultGroup>

        <p className="text-xs text-muted-foreground bg-secondary rounded px-3 py-2">
          {t("skills.importDraftNote")}
        </p>
      </div>
      <div className="px-6 py-4 border-t border-border flex justify-end gap-2">
        <button
          onClick={onAgain}
          className="px-4 py-2 text-sm font-medium text-muted-foreground bg-secondary rounded-lg hover:bg-muted"
        >
          {t("skills.importAgain")}
        </button>
        <button
          onClick={onClose}
          className="px-4 py-2 text-sm font-medium text-white bg-primary-600 rounded-lg hover:bg-primary-700"
        >
          {t("skills.importDone")}
        </button>
      </div>
    </>
  );
}

function ImportDialog({ onClose }: { onClose: () => void }) {
  const { t } = useLocale();
  const [tab, setTab] = useState<ImportTab>("source");
  const [result, setResult] = useState<SkillImportSourceResult | null>(null);

  // House rule: popups close on ESC. Closing mid-import is allowed on purpose — the
  // request keeps running server-side and the skills list is invalidated on success.
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/30" onClick={onClose} />
      <div className="relative bg-background rounded-xl shadow-xl w-full max-w-lg mx-4 max-h-[85vh] flex flex-col animate-[slideInRight_0.2s_ease-out]">
        <div className="px-6 py-4 border-b border-border flex items-center justify-between">
          <h3 className="text-lg font-semibold text-foreground">
            {result ? t("skills.importResultTitle") : t("skills.import")}
          </h3>
          <button onClick={onClose} className="text-muted-foreground hover:text-foreground text-xl leading-none">&times;</button>
        </div>
        {result ? (
          <ImportResultPanel result={result} onAgain={() => setResult(null)} onClose={onClose} />
        ) : (
          <>
            <div className="px-6 pt-4">
              <div className="inline-flex gap-1 bg-secondary rounded-lg p-0.5">
                {(["source", "file"] as ImportTab[]).map((k) => (
                  <button
                    key={k}
                    onClick={() => setTab(k)}
                    className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
                      tab === k
                        ? "bg-background text-foreground shadow-sm"
                        : "text-muted-foreground hover:text-foreground"
                    }`}
                  >
                    {t(k === "source" ? "skills.importTabSource" : "skills.importTabFile")}
                  </button>
                ))}
              </div>
            </div>
            {tab === "source" ? (
              <SourceImportForm onImported={setResult} />
            ) : (
              <FileImportPane onClose={onClose} />
            )}
          </>
        )}
      </div>
    </div>
  );
}

/* -- Skill Card ---------------------------------------------------- */

function SkillCard({ skill, onClick }: { skill: Skill; onClick: () => void }) {
  return (
    <Card className="hover:border-primary-200 transition-colors cursor-pointer">
      <button onClick={onClick} className="w-full text-left px-5 py-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="font-medium text-foreground">{skill.name}</span>
            <SkillStatusBadge isDraft={skill.is_draft} />
            <DomainBadge domain={skill.domain} />
            {skill.created_by === "imported" && <ImportedBadge sourceUri={skill.source_uri} />}
          </div>
          <span className="text-xs text-muted-foreground">
            {skill.ref_count} ref{skill.ref_count !== 1 ? "s" : ""}
          </span>
        </div>
        <p className="text-sm text-muted-foreground mt-1 line-clamp-2">{skill.description}</p>
        {skill.tools.length > 0 && (
          <div className="flex flex-wrap gap-1 mt-2">
            {skill.tools.slice(0, 5).map((t) => (
              <span key={t} className="px-1.5 py-0.5 bg-blue-50 text-blue-600 text-xs rounded">
                {t.split(".").pop()}
              </span>
            ))}
            {skill.tools.length > 5 && (
              <span className="text-xs text-muted-foreground">+{skill.tools.length - 5}</span>
            )}
          </div>
        )}
      </button>
    </Card>
  );
}

/* -- Improvement Queue -------------------------------------------- */

function triggerLabel(trigger: string, source: string): string {
  const issueMatch = source.match(/issue:(\d+)/);
  const agentMatch = source.match(/agent:(\w+)/);
  switch (trigger) {
    case "post_resolution":
      return issueMatch ? `After resolving Issue #${issueMatch[1]}` : "Post-resolution";
    case "agent_detected":
      return agentMatch ? `Agent: ${agentMatch[1]}` : "Agent-detected";
    default:
      return "Manual";
  }
}

function TriggerBadge({ trigger, source }: { trigger: string; source: string }) {
  const colors: Record<string, string> = {
    manual: "bg-blue-100 text-blue-700",
    post_resolution: "bg-purple-100 text-purple-700",
    agent_detected: "bg-amber-100 text-amber-700",
    auto: "bg-cyan-100 text-cyan-700",
  };
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${colors[trigger] ?? "bg-secondary text-muted-foreground"}`}>
      {triggerLabel(trigger, source)}
    </span>
  );
}

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    pending: "bg-amber-100 text-amber-700",
    completed: "bg-emerald-100 text-emerald-700",
    failed: "bg-red-100 text-red-700",
  };
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${colors[status] ?? "bg-secondary text-muted-foreground"}`}>
      {status}
    </span>
  );
}

function ImprovementQueue() {
  const [showHistory, setShowHistory] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const pendingQ = useSkillImprovements("pending");
  const historyQ = useSkillImprovementHistory();
  const batchDismiss = useBatchDismissImprovements();
  const records: SkillImprovementRecord[] = showHistory
    ? (historyQ.data ?? [])
    : (pendingQ.data ?? []);

  const total = (pendingQ.data?.length ?? 0) + (historyQ.data?.length ?? 0);
  if (total === 0 && !pendingQ.isLoading) return null;

  const toggleSelect = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const handleBatchDismiss = () => {
    if (selected.size === 0) return;
    batchDismiss.mutate([...selected], {
      onSuccess: () => setSelected(new Set()),
    });
  };

  return (
    <Card>
      <CardBody>
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-medium text-foreground">
            Improvement Queue
            {(pendingQ.data?.length ?? 0) > 0 && (
              <span className="ml-2 inline-flex items-center justify-center w-5 h-5 text-xs font-bold text-white bg-primary-600 rounded-full">
                {pendingQ.data!.length}
              </span>
            )}
          </h3>
          <div className="flex items-center gap-2">
            {selected.size > 0 && !showHistory && (
              <button
                onClick={handleBatchDismiss}
                disabled={batchDismiss.isPending}
                className="px-3 py-1 text-xs font-medium text-red-700 bg-red-100 rounded-lg hover:bg-red-200 disabled:opacity-50 transition-colors"
              >
                {batchDismiss.isPending ? "Dismissing..." : `Dismiss Selected (${selected.size})`}
              </button>
            )}
            <div className="flex gap-1 bg-secondary rounded-lg p-0.5">
              <button
                onClick={() => { setShowHistory(false); setSelected(new Set()); }}
                className={`px-3 py-1 text-xs rounded-md transition-colors ${!showHistory ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"}`}
              >
                Pending
              </button>
              <button
                onClick={() => { setShowHistory(true); setSelected(new Set()); }}
                className={`px-3 py-1 text-xs rounded-md transition-colors ${showHistory ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"}`}
              >
                History
              </button>
            </div>
          </div>
        </div>
        {pendingQ.isLoading ? (
          <Spinner />
        ) : records.length === 0 ? (
          <p className="text-sm text-muted-foreground text-center py-3">
            {showHistory ? "No improvement history yet." : "No pending improvements."}
          </p>
        ) : (
          <div className="space-y-2">
            {records.map((r) => (
              <div key={r.id} className="flex items-start gap-3 p-3 rounded-lg border border-border">
                {!showHistory && (
                  <input
                    type="checkbox"
                    checked={selected.has(r.id)}
                    onChange={() => toggleSelect(r.id)}
                    className="mt-1 h-4 w-4 rounded border-border text-primary-600 focus:ring-primary-500 cursor-pointer"
                  />
                )}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="font-medium text-sm text-foreground">{r.skill_name}</span>
                    <TriggerBadge trigger={r.trigger} source={r.source} />
                    <StatusBadge status={r.status} />
                    {r.confidence != null && (
                      <span className={`text-xs px-1.5 py-0.5 rounded ${
                        r.confidence >= 0.7 ? "bg-red-100 text-red-700" :
                        r.confidence >= 0.4 ? "bg-amber-100 text-amber-700" :
                        "bg-gray-100 text-muted-foreground"
                      }`}>
                        {Math.round(r.confidence * 100)}%
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-muted-foreground line-clamp-2">{r.improvement}</p>
                  <span className="text-xs text-muted-foreground mt-1 block">
                    {new Date(r.created_at).toLocaleString()}
                  </span>
                </div>
              </div>
            ))}
          </div>
        )}
      </CardBody>
    </Card>
  );
}

/* -- Main Skills Page ---------------------------------------------- */

export default function Skills() {
  const { t } = useLocale();
  const navigate = useNavigate();
  const { data: skills, isLoading, error } = useSkills();
  const [filter, setFilter] = useState<Filter>("all");
  const [search, setSearch] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [showImport, setShowImport] = useState(false);

  if (isLoading) return <Spinner label="Loading skills..." />;
  if (error) return <ErrorBanner message={error.message} />;

  const filtered = (skills ?? []).filter((s) => {
    if (filter === "published" && s.is_draft) return false;
    if (filter === "draft" && !s.is_draft) return false;
    if (search) {
      const q = search.toLowerCase();
      return (
        s.name.toLowerCase().includes(q) ||
        s.description.toLowerCase().includes(q) ||
        s.domain.toLowerCase().includes(q)
      );
    }
    return true;
  });

  return (
    <div className="max-w-6xl space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-foreground">
          {t("skills.title")}{" "}
          <span className="text-base font-normal text-muted-foreground">
            ({skills?.length ?? 0})
          </span>
        </h1>
        <div className="flex gap-2">
          <button
            onClick={() => setShowCreate(true)}
            className="px-4 py-2 text-sm font-medium text-white bg-primary-600 rounded-lg hover:bg-primary-700"
          >
            {t("skills.create")}
          </button>
          <button
            onClick={() => setShowImport(true)}
            className="px-4 py-2 text-sm font-medium text-foreground bg-secondary rounded-lg hover:bg-muted"
          >
            {t("skills.import")}
          </button>
        </div>
      </div>

      {/* Filters */}
      <div className="flex items-center gap-4">
        <div className="flex gap-1 bg-secondary rounded-lg p-0.5">
          {(["all", "published", "draft"] as Filter[]).map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
                filter === f
                  ? "bg-background text-foreground shadow-sm"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              {t(`skills.${f}`)}
            </button>
          ))}
        </div>
        <input
          type="text"
          placeholder={t("skills.search")}
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="flex-1 max-w-xs border border-border rounded-lg px-3 py-1.5 text-sm focus:ring-2 focus:ring-primary-500 focus:border-primary-500 outline-none"
        />
      </div>

      {/* Improvement Queue */}
      <ImprovementQueue />

      {/* Skill Cards */}
      {filtered.length === 0 ? (
        <Card>
          <CardBody>
            <p className="text-sm text-muted-foreground text-center py-4">{t("skills.noSkills")}</p>
          </CardBody>
        </Card>
      ) : (
        <div className="grid gap-3">
          {filtered.map((skill) => (
            <SkillCard
              key={skill.name}
              skill={skill}
              onClick={() => navigate(`/app/skills/${encodeURIComponent(skill.name)}`)}
            />
          ))}
        </div>
      )}

      {/* Modals */}
      {showCreate && <CreateSkillDialog onClose={() => setShowCreate(false)} />}
      {showImport && <ImportDialog onClose={() => setShowImport(false)} />}
    </div>
  );
}
