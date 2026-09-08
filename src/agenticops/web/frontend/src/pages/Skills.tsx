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
import {
  Archive,
  ChevronRight,
  FileText,
  Folder,
  GitBranch,
  Link,
  TriangleAlert,
  Upload,
  X,
  type LucideIcon,
} from "lucide-react";
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
type ImportStatus = "installed" | "skipped" | "rejected";

// The leading slot of the source field shows what the server will treat the input as —
// an address bar reading its own scheme. "empty" is the resting state before typing.
const SOURCE_KIND_ICON: Record<SkillSourceKind, LucideIcon> = {
  git: GitBranch,
  "archive-url": Archive,
  "skill-md-url": FileText,
  url: Link,
  path: Folder,
  "unsupported-scheme": TriangleAlert,
  empty: Link,
};
// Kinds whose label alone does not tell the user what happens next get one extra sentence.
const SOURCE_KIND_NOTE: Partial<Record<SkillSourceKind, string>> = {
  url: "skills.importKindNote.url",
  "skill-md-url": "skills.importKindNote.skill-md-url",
  path: "skills.importKindNote.path",
  "unsupported-scheme": "skills.importKindNote.unsupported-scheme",
};

const FOCUS_RING =
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500 focus-visible:ring-offset-2 focus-visible:ring-offset-background";
const BTN_PRIMARY = `inline-flex items-center gap-2 rounded-lg bg-primary-600 px-4 py-2 text-sm font-medium text-white hover:bg-primary-700 disabled:cursor-not-allowed disabled:opacity-50 ${FOCUS_RING}`;
const BTN_SECONDARY = `inline-flex items-center rounded-lg border border-border bg-background px-4 py-2 text-sm font-medium text-foreground hover:bg-secondary ${FOCUS_RING}`;
const BTN_SECONDARY_SM = `inline-flex shrink-0 items-center rounded-md border border-border bg-background px-2.5 py-1 text-xs font-medium text-foreground hover:bg-secondary ${FOCUS_RING}`;

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

function InlineSpinner() {
  return (
    <svg className="h-3.5 w-3.5 animate-spin motion-reduce:animate-none" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
    </svg>
  );
}

/** What went wrong, then the server's own words. Border only — tinted fills break in dark mode. */
function ErrorNote({ title, detail }: { title: string; detail: string }) {
  return (
    <div role="alert" className="flex gap-2.5 rounded-lg border border-red-300 px-3 py-2.5 dark:border-red-900">
      <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0 text-red-600 dark:text-red-400" aria-hidden="true" />
      <div className="min-w-0 text-sm">
        <p className="font-medium text-foreground">{title}</p>
        <p className="mt-0.5 break-all text-muted-foreground">{detail}</p>
      </div>
    </div>
  );
}

/** Existing multipart upload path (.md / .zip) — behaviour unchanged: success closes the dialog. */
function FileImportPane({ onClose }: { onClose: () => void }) {
  const { t } = useLocale();
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
    <>
      <div className="space-y-3 px-6 py-5">
        <div
          role="button"
          tabIndex={0}
          aria-label={t("skills.importDropHint")}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              fileRef.current?.click();
            }
          }}
          onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
          onDragLeave={() => setDragOver(false)}
          onDrop={handleDrop}
          onClick={() => fileRef.current?.click()}
          className={`flex cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border border-dashed px-6 py-10 text-center transition-colors ${FOCUS_RING} ${
            dragOver ? "border-primary-500 bg-secondary" : "border-border hover:border-muted-foreground"
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
            <>
              <span className="text-muted-foreground"><InlineSpinner /></span>
              <p className="text-sm text-muted-foreground">{t("skills.importUploading")}</p>
            </>
          ) : (
            <>
              <Upload className="h-5 w-5 text-muted-foreground" aria-hidden="true" />
              <p className="text-sm text-foreground">{t("skills.importDropHint")}</p>
              <p className="text-xs text-muted-foreground">{t("skills.importDropSub")}</p>
            </>
          )}
        </div>
        {importMut.isError && (
          <ErrorNote title={t("skills.importErrorTitle")} detail={importMut.error.message} />
        )}
      </div>
    </>
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
  const KindIcon = SOURCE_KIND_ICON[kind];
  const warn = kind === "unsupported-scheme";
  const noteKey = SOURCE_KIND_NOTE[kind];

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
    <>
      <div className="space-y-5 px-6 py-5">
        <div>
          <label htmlFor="skill-import-source" className="sr-only">
            {t("skills.importSourceLabel")}
          </label>
          <div
            className={`flex items-stretch rounded-lg border bg-background transition-colors focus-within:border-primary-500 focus-within:ring-1 focus-within:ring-primary-500 ${
              warn ? "border-amber-400 dark:border-amber-600" : "border-border"
            }`}
          >
            <div
              aria-hidden="true"
              className={`flex select-none items-center gap-1.5 border-r pl-3 pr-2.5 text-xs ${
                warn
                  ? "border-amber-400 text-amber-700 dark:border-amber-600 dark:text-amber-400"
                  : "border-border text-muted-foreground"
              }`}
            >
              <KindIcon className="h-4 w-4" />
              <span className="hidden whitespace-nowrap sm:inline">{t(`skills.importKind.${kind}`)}</span>
            </div>
            <input
              id="skill-import-source"
              autoFocus
              type="text"
              autoComplete="off"
              spellCheck={false}
              value={uri}
              onChange={(e) => setUri(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") submit(); }}
              placeholder={t("skills.importSourcePlaceholder")}
              className="min-w-0 flex-1 bg-transparent px-3 py-2.5 font-mono text-sm text-foreground outline-none placeholder:font-sans placeholder:text-muted-foreground"
            />
          </div>
          {/* The slot is decorative for AT; the same information is announced here. */}
          <p className="sr-only" aria-live="polite">{t(`skills.importKind.${kind}`)}</p>
          <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
            {noteKey ? t(noteKey) : t("skills.importSourceHelp")}
          </p>
        </div>

        <div className="border-t border-border pt-3">
          <button
            type="button"
            aria-expanded={showNames}
            onClick={() => setShowNames((v) => !v)}
            className={`flex w-full items-center justify-between rounded-md py-1.5 text-sm text-foreground hover:text-primary-600 ${FOCUS_RING}`}
          >
            <span>
              {t("skills.importNamesToggle")}
              <span className="text-muted-foreground"> {t("skills.importNamesOptional")}</span>
            </span>
            <ChevronRight
              aria-hidden="true"
              className={`h-4 w-4 text-muted-foreground transition-transform motion-reduce:transition-none ${showNames ? "rotate-90" : ""}`}
            />
          </button>
          {showNames && (
            <div className="mt-2 space-y-1.5">
              <input
                type="text"
                autoComplete="off"
                spellCheck={false}
                value={namesText}
                onChange={(e) => setNamesText(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") submit(); }}
                placeholder={t("skills.importNamesPlaceholder")}
                className="w-full rounded-lg border border-border bg-background px-3 py-2 font-mono text-sm text-foreground outline-none placeholder:font-sans placeholder:text-muted-foreground focus:border-primary-500 focus:ring-1 focus:ring-primary-500"
              />
              <p className="text-xs text-muted-foreground">{t("skills.importNamesHelp")}</p>
            </div>
          )}
        </div>

        {errorText && <ErrorNote title={t("skills.importErrorTitle")} detail={errorText} />}
      </div>

      {/* The subtitle already says everything lands as a draft; the footer only speaks while working. */}
      <div className="flex items-center justify-between gap-4 border-t border-border px-6 py-4">
        <p className="text-xs text-muted-foreground" aria-live="polite">
          {importMut.isPending ? t("skills.importRunning") : ""}
        </p>
        <button onClick={submit} disabled={!uri.trim() || importMut.isPending} className={BTN_PRIMARY}>
          {importMut.isPending && <InlineSpinner />}
          {t("skills.importRun")}
        </button>
      </div>
    </>
  );
}

/** One mark per outcome; colour lives here and in the status word, nowhere else. */
function StatusMark({ status }: { status: ImportStatus }) {
  if (status === "installed") {
    return <span aria-hidden="true" className="mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full bg-emerald-500" />;
  }
  if (status === "skipped") {
    return <span aria-hidden="true" className="mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full border-2 border-amber-500" />;
  }
  return <X aria-hidden="true" strokeWidth={3} className="mt-1 h-3 w-3 shrink-0 text-red-500" />;
}

const STATUS_TEXT: Record<ImportStatus, string> = {
  installed: "text-emerald-700 dark:text-emerald-400",
  skipped: "text-amber-700 dark:text-amber-400",
  rejected: "text-red-700 dark:text-red-400",
};

/** The manifest: one list, every package the source contained, each with its outcome and
 *  the server's reason. Reading it top to bottom answers "what happened to my import". */
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
  const sep = t("skills.listSeparator");

  const rows: { status: ImportStatus; name: string; meta?: string; reason?: string }[] = [
    ...result.installed.map((s) => ({
      status: "installed" as const,
      name: s.name,
      meta: `${s.files} ${t("skills.importFiles")}${sep}${formatBytes(s.bytes)}`,
    })),
    ...result.skipped.map((s) => ({ status: "skipped" as const, name: s.name, reason: s.reason })),
    ...result.rejected.map((s) => ({ status: "rejected" as const, name: s.name, reason: s.reason })),
  ];
  const tally = (
    [
      [result.installed.length, "skills.importTallyInstalled"],
      [result.skipped.length, "skills.importTallySkipped"],
      [result.rejected.length, "skills.importTallyRejected"],
    ] as [number, string][]
  ).filter(([n]) => n > 0);

  return (
    <>
      <div className="flex-1 overflow-y-auto px-6 py-5">
        {rows.length === 0 ? (
          <div className="py-6 text-center">
            <p className="text-sm font-medium text-foreground">{t("skills.importNothing")}</p>
            <p className="mt-1 text-xs text-muted-foreground">{t("skills.importNoneFound")}</p>
          </div>
        ) : (
          <>
            {/* A single row already says everything the tally would; it earns its place from two on. */}
            {rows.length > 1 && (
              <p className="mb-3 text-sm text-foreground">
                {tally.map(([n, key], i) => (
                  <span key={key}>
                    {i > 0 && sep}
                    <span className="font-semibold tabular-nums">{n}</span> {t(key)}
                  </span>
                ))}
              </p>
            )}
            <ul className="divide-y divide-border border-t border-border">
              {rows.map((r) => (
                <li key={`${r.status}:${r.name}`} className="flex items-start gap-3 py-3">
                  <StatusMark status={r.status} />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-baseline justify-between gap-3">
                      <span className="truncate text-sm font-medium text-foreground">{r.name}</span>
                      {r.meta && (
                        <span className="shrink-0 text-xs tabular-nums text-muted-foreground">{r.meta}</span>
                      )}
                    </div>
                    <p className={`mt-0.5 text-xs ${STATUS_TEXT[r.status]}`}>
                      {t(`skills.importStatus.${r.status}`)}
                    </p>
                    {r.reason && <p className="mt-0.5 break-words text-xs text-muted-foreground">{r.reason}</p>}
                  </div>
                  {r.status === "installed" && (
                    <button
                      onClick={() => {
                        onClose();
                        navigate(`/app/skills/${encodeURIComponent(r.name)}`);
                      }}
                      className={BTN_SECONDARY_SM}
                    >
                      {t("skills.importViewPromote")}
                    </button>
                  )}
                </li>
              ))}
            </ul>
          </>
        )}
      </div>
      <div className="flex items-center justify-between gap-4 border-t border-border px-6 py-4">
        <p className="text-xs text-muted-foreground">{t("skills.importDraftNote")}</p>
        <div className="flex shrink-0 gap-2">
          <button onClick={onAgain} className={BTN_SECONDARY}>{t("skills.importAgain")}</button>
          <button onClick={onClose} className={BTN_PRIMARY}>{t("skills.importDone")}</button>
        </div>
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

  const shortRef = result ? result.source_ref.slice(0, 12) : "";

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="skill-import-title"
      className="fixed inset-0 z-50 flex items-center justify-center"
    >
      <div className="absolute inset-0 bg-black/30" onClick={onClose} />
      <div className="relative mx-4 flex max-h-[85vh] w-full max-w-xl flex-col rounded-xl bg-background shadow-xl animate-[slideInRight_0.2s_ease-out] motion-reduce:animate-none">
        <div className="flex items-start justify-between gap-4 px-6 pb-4 pt-5">
          <div className="min-w-0">
            <h3 id="skill-import-title" className="text-base font-semibold text-foreground">
              {result ? t("skills.importResultTitle") : t("skills.importTitle")}
            </h3>
            {result ? (
              <p className="mt-1 break-all text-xs text-muted-foreground">
                <span className="font-mono text-foreground">{result.source_uri}</span>
                {shortRef && (
                  <span className="ml-2">
                    ref <span className="font-mono">{shortRef}</span>
                  </span>
                )}
              </p>
            ) : (
              <p className="mt-1 text-sm leading-relaxed text-muted-foreground">{t("skills.importSubtitle")}</p>
            )}
          </div>
          <button
            onClick={onClose}
            aria-label={t("common.cancel")}
            className={`-mr-2 -mt-1 shrink-0 rounded-md p-1.5 text-muted-foreground hover:bg-secondary hover:text-foreground ${FOCUS_RING}`}
          >
            <X className="h-4 w-4" aria-hidden="true" />
          </button>
        </div>
        {result ? (
          <ImportResultPanel result={result} onAgain={() => setResult(null)} onClose={onClose} />
        ) : (
          <>
            <div className="px-6">
              <div role="tablist" className="grid grid-cols-2 rounded-lg bg-secondary p-0.5">
                {(["source", "file"] as ImportTab[]).map((k) => (
                  <button
                    key={k}
                    role="tab"
                    aria-selected={tab === k}
                    onClick={() => setTab(k)}
                    className={`rounded-md py-1.5 text-xs font-medium transition-colors ${FOCUS_RING} ${
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
