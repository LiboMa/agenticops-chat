import { useState, useRef, useCallback } from "react";
import {
  useSkills,
  useSkill,
  useGenerateSkill,
  useSaveDraft,
  useImportSkill,
  useDeleteSkill,
} from "@/hooks/useSkills";
import { Card, CardBody } from "@/components/ui/Card";
import { Spinner } from "@/components/ui/Spinner";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import { renderMarkdown } from "@/lib/renderMarkdown";
import type { Skill, SkillGenerateResponse } from "@/api/types";

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
    <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-slate-100 text-slate-600">
      {domain}
    </span>
  );
}

/* ── Skill Detail Panel (slide-over) ─────────────────────────────── */

function SkillDetailPanel({
  skillName,
  onClose,
}: {
  skillName: string;
  onClose: () => void;
}) {
  const { data: skill, isLoading } = useSkill(skillName);
  const deleteMut = useDeleteSkill();
  const [actionError, setActionError] = useState("");

  if (isLoading) return <Spinner label="Loading skill..." />;
  if (!skill) return null;

  const bodyHtml = skill.body_markdown
    ? renderMarkdown(skill.body_markdown)
    : "";

  const handleDelete = () => {
    setActionError("");
    deleteMut.mutate(skill.name, {
      onSuccess: () => onClose(),
      onError: (err) => setActionError(err.message),
    });
  };

  return (
    <div className="fixed inset-0 z-50 flex">
      <div className="absolute inset-0 bg-black/30" onClick={onClose} />
      <div className="relative ml-auto w-full max-w-2xl bg-white shadow-xl overflow-y-auto">
        <div className="sticky top-0 bg-white border-b border-slate-200 px-6 py-4 flex items-center justify-between z-10">
          <div>
            <h2 className="text-lg font-semibold text-slate-900">
              {skill.name}
            </h2>
            <div className="flex items-center gap-2 mt-1">
              <SkillStatusBadge isDraft={skill.is_draft} />
              <DomainBadge domain={skill.domain} />
            </div>
          </div>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-slate-600 text-xl leading-none"
          >
            &times;
          </button>
        </div>

        <div className="px-6 py-4 space-y-4">
          <p className="text-sm text-slate-600">{skill.description}</p>

          {/* Metadata */}
          <div className="grid grid-cols-2 gap-4 text-sm">
            {skill.tools.length > 0 && (
              <div>
                <span className="text-slate-400 block">Tools</span>
                <div className="flex flex-wrap gap-1 mt-1">
                  {skill.tools.map((t) => (
                    <span
                      key={t}
                      className="px-1.5 py-0.5 bg-blue-50 text-blue-700 text-xs rounded"
                    >
                      {t.split(".").pop()}
                    </span>
                  ))}
                </div>
              </div>
            )}
            {skill.references.length > 0 && (
              <div>
                <span className="text-slate-400 block">References</span>
                <ul className="mt-1 space-y-0.5">
                  {skill.references.map((r) => (
                    <li key={r} className="text-xs text-slate-600">
                      {r}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>

          {/* SKILL.md body */}
          {bodyHtml && (
            <div
              className="prose prose-sm max-w-none text-slate-700 border-t border-slate-100 pt-4"
              dangerouslySetInnerHTML={{ __html: bodyHtml }}
            />
          )}

          {actionError && (
            <div className="text-sm text-red-600 bg-red-50 px-3 py-2 rounded">
              {actionError}
            </div>
          )}

          {/* Delete (drafts only) */}
          {skill.is_draft && (
            <div className="border-t border-slate-200 pt-4">
              <button
                onClick={handleDelete}
                disabled={deleteMut.isPending}
                className="px-4 py-2 text-sm font-medium text-red-600 bg-red-50 rounded-lg hover:bg-red-100 disabled:opacity-50"
              >
                {deleteMut.isPending ? "Deleting..." : "Delete Draft"}
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

/* ── Create Skill Dialog ─────────────────────────────────────────── */

function CreateSkillDialog({ onClose }: { onClose: () => void }) {
  const [description, setDescription] = useState("");
  const [generated, setGenerated] = useState<SkillGenerateResponse | null>(
    null,
  );
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
      <div className="relative bg-white rounded-xl shadow-xl w-full max-w-lg mx-4 max-h-[80vh] flex flex-col">
        <div className="px-6 py-4 border-b border-slate-200 flex items-center justify-between">
          <h3 className="text-lg font-semibold text-slate-900">
            Create Skill
          </h3>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-slate-600 text-xl leading-none"
          >
            &times;
          </button>
        </div>

        <div className="px-6 py-4 space-y-4 overflow-y-auto flex-1">
          {!generated ? (
            <>
              <div>
                <label className="text-sm font-medium text-slate-700 block mb-1">
                  Describe the skill you want to create
                </label>
                <textarea
                  className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-primary-500 focus:border-primary-500 outline-none resize-none"
                  rows={4}
                  placeholder="e.g. A skill for troubleshooting Redis cluster issues including replication lag, memory pressure, and failover procedures"
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                />
              </div>
              {generateMut.isError && (
                <div className="text-sm text-red-600 bg-red-50 px-3 py-2 rounded">
                  {generateMut.error.message}
                </div>
              )}
            </>
          ) : (
            <>
              <div className="space-y-2">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium text-slate-700">
                    {generated.name}
                  </span>
                  <DomainBadge domain="draft" />
                </div>
                <p className="text-sm text-slate-600">
                  {generated.description}
                </p>
              </div>
              <div>
                <label className="text-xs text-slate-400 block mb-1">
                  Content Preview
                </label>
                <pre className="bg-slate-50 border border-slate-200 rounded-lg p-3 text-xs text-slate-700 max-h-60 overflow-y-auto whitespace-pre-wrap">
                  {generated.body_preview}
                </pre>
              </div>
              {Object.keys(generated.references).length > 0 && (
                <div>
                  <label className="text-xs text-slate-400 block mb-1">
                    References ({Object.keys(generated.references).length})
                  </label>
                  <ul className="text-xs text-slate-600 space-y-0.5">
                    {Object.keys(generated.references).map((r) => (
                      <li key={r}>{r}</li>
                    ))}
                  </ul>
                </div>
              )}
              {saveMut.isError && (
                <div className="text-sm text-red-600 bg-red-50 px-3 py-2 rounded">
                  {saveMut.error.message}
                </div>
              )}
            </>
          )}
        </div>

        <div className="px-6 py-4 border-t border-slate-200 flex justify-end gap-2">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm font-medium text-slate-600 bg-slate-100 rounded-lg hover:bg-slate-200"
          >
            Cancel
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
              {saveMut.isPending ? "Saving..." : "Save as Draft"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

/* ── Import Dialog ───────────────────────────────────────────────── */

function ImportDialog({ onClose }: { onClose: () => void }) {
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
      <div className="relative bg-white rounded-xl shadow-xl w-full max-w-md mx-4">
        <div className="px-6 py-4 border-b border-slate-200 flex items-center justify-between">
          <h3 className="text-lg font-semibold text-slate-900">
            Import Skill
          </h3>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-slate-600 text-xl leading-none"
          >
            &times;
          </button>
        </div>
        <div className="px-6 py-6">
          <div
            onDragOver={(e) => {
              e.preventDefault();
              setDragOver(true);
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={handleDrop}
            onClick={() => fileRef.current?.click()}
            className={`border-2 border-dashed rounded-lg p-8 text-center cursor-pointer transition-colors ${
              dragOver
                ? "border-primary-400 bg-primary-50"
                : "border-slate-300 hover:border-slate-400"
            }`}
          >
            <input
              ref={fileRef}
              type="file"
              accept=".md,.zip"
              className="hidden"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) handleFile(file);
              }}
            />
            {importMut.isPending ? (
              <Spinner label="Importing..." />
            ) : (
              <>
                <p className="text-sm text-slate-600">
                  Drop a <code>.md</code> or <code>.zip</code> file here, or
                  click to browse
                </p>
                <p className="text-xs text-slate-400 mt-1">
                  ZIP must contain SKILL.md + optional references/*.md
                </p>
              </>
            )}
          </div>
          {importMut.isError && (
            <div className="text-sm text-red-600 bg-red-50 px-3 py-2 rounded mt-3">
              {importMut.error.message}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

/* ── Main Page ───────────────────────────────────────────────────── */

export default function Skills() {
  const { data: skills, isLoading, error } = useSkills();
  const [filter, setFilter] = useState<Filter>("all");
  const [search, setSearch] = useState("");
  const [selectedSkill, setSelectedSkill] = useState<string | null>(null);
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
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-slate-900">
          Skills{" "}
          <span className="text-base font-normal text-slate-400">
            ({skills?.length ?? 0})
          </span>
        </h1>
        <div className="flex gap-2">
          <button
            onClick={() => setShowCreate(true)}
            className="px-4 py-2 text-sm font-medium text-white bg-primary-600 rounded-lg hover:bg-primary-700"
          >
            Create Skill
          </button>
          <button
            onClick={() => setShowImport(true)}
            className="px-4 py-2 text-sm font-medium text-slate-700 bg-slate-100 rounded-lg hover:bg-slate-200"
          >
            Import
          </button>
        </div>
      </div>

      {/* Filters */}
      <div className="flex items-center gap-4">
        <div className="flex gap-1 bg-slate-100 rounded-lg p-0.5">
          {(["all", "published", "draft"] as Filter[]).map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
                filter === f
                  ? "bg-white text-slate-900 shadow-sm"
                  : "text-slate-500 hover:text-slate-700"
              }`}
            >
              {f.charAt(0).toUpperCase() + f.slice(1)}
            </button>
          ))}
        </div>
        <input
          type="text"
          placeholder="Search skills..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="flex-1 max-w-xs border border-slate-300 rounded-lg px-3 py-1.5 text-sm focus:ring-2 focus:ring-primary-500 focus:border-primary-500 outline-none"
        />
      </div>

      {/* Skill Cards */}
      {filtered.length === 0 ? (
        <Card>
          <CardBody>
            <p className="text-sm text-slate-500 text-center py-4">
              No skills found.
            </p>
          </CardBody>
        </Card>
      ) : (
        <div className="grid gap-3">
          {filtered.map((skill) => (
            <SkillCard
              key={skill.name}
              skill={skill}
              onClick={() => setSelectedSkill(skill.name)}
            />
          ))}
        </div>
      )}

      {/* Slide-over detail panel */}
      {selectedSkill && (
        <SkillDetailPanel
          skillName={selectedSkill}
          onClose={() => setSelectedSkill(null)}
        />
      )}

      {/* Modals */}
      {showCreate && (
        <CreateSkillDialog onClose={() => setShowCreate(false)} />
      )}
      {showImport && <ImportDialog onClose={() => setShowImport(false)} />}
    </div>
  );
}

function SkillCard({
  skill,
  onClick,
}: {
  skill: Skill;
  onClick: () => void;
}) {
  return (
    <Card className="hover:border-primary-200 transition-colors cursor-pointer">
      <button onClick={onClick} className="w-full text-left px-5 py-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="font-medium text-slate-900">{skill.name}</span>
            <SkillStatusBadge isDraft={skill.is_draft} />
            <DomainBadge domain={skill.domain} />
          </div>
          <span className="text-xs text-slate-400">
            {skill.ref_count} ref{skill.ref_count !== 1 ? "s" : ""}
          </span>
        </div>
        <p className="text-sm text-slate-500 mt-1 line-clamp-2">
          {skill.description}
        </p>
        {skill.tools.length > 0 && (
          <div className="flex flex-wrap gap-1 mt-2">
            {skill.tools.slice(0, 5).map((t) => (
              <span
                key={t}
                className="px-1.5 py-0.5 bg-blue-50 text-blue-600 text-xs rounded"
              >
                {t.split(".").pop()}
              </span>
            ))}
            {skill.tools.length > 5 && (
              <span className="text-xs text-slate-400">
                +{skill.tools.length - 5}
              </span>
            )}
          </div>
        )}
      </button>
    </Card>
  );
}
