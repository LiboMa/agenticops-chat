import { useState, useRef, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import {
  useSkills,
  useGenerateSkill,
  useSaveDraft,
  useImportSkill,
  useSkillImprovements,
  useSkillImprovementHistory,
  useBatchDismissImprovements,
} from "@/hooks/useSkills";
import { Card, CardBody } from "@/components/ui/Card";
import { Spinner } from "@/components/ui/Spinner";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import { useLocale } from "@/i18n/LocaleContext";
import type { Skill, SkillGenerateResponse, SkillImprovementRecord } from "@/api/types";

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

function ImportDialog({ onClose }: { onClose: () => void }) {
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
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/30" onClick={onClose} />
      <div className="relative bg-background rounded-xl shadow-xl w-full max-w-md mx-4">
        <div className="px-6 py-4 border-b border-border flex items-center justify-between">
          <h3 className="text-lg font-semibold text-foreground">{t("skills.import")}</h3>
          <button onClick={onClose} className="text-muted-foreground hover:text-foreground text-xl leading-none">&times;</button>
        </div>
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
