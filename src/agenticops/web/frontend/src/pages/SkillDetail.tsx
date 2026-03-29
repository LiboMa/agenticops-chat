import { useState } from "react";
import { useParams, Link, useNavigate } from "react-router-dom";
import { Card, CardBody } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Spinner } from "@/components/ui/Spinner";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import { renderMarkdown } from "@/lib/renderMarkdown";
import { useLocale } from "@/i18n/LocaleContext";
import {
  useSkill,
  useUpdateSkill,
  useDeleteSkill,
  useReviewSkill,
  usePromoteSkill,
  useImproveSkill,
} from "@/hooks/useSkills";

/* -- Tab type ----------------------------------------------------- */

type Tab = "view" | "edit" | "review";

/* -- Improve Dialog ----------------------------------------------- */

function ImproveDialog({
  skillName,
  onClose,
  onSuccess,
}: {
  skillName: string;
  onClose: () => void;
  onSuccess: () => void;
}) {
  const [improvement, setImprovement] = useState("");
  const improveMut = useImproveSkill();

  const handleSubmit = () => {
    improveMut.mutate(
      { name: skillName, improvement },
      { onSuccess: () => { onSuccess(); onClose(); } },
    );
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/30" onClick={onClose} />
      <div className="relative bg-background rounded-xl shadow-xl w-full max-w-lg mx-4">
        <div className="px-6 py-4 border-b border-border flex items-center justify-between">
          <h3 className="text-lg font-semibold text-foreground">Improve Skill</h3>
          <button onClick={onClose} className="text-muted-foreground hover:text-foreground text-xl leading-none">&times;</button>
        </div>
        <div className="px-6 py-4 space-y-4">
          <div>
            <label className="text-sm font-medium text-foreground block mb-1">
              What should be improved?
            </label>
            <textarea
              className="w-full border border-border rounded-lg px-3 py-2 text-sm focus:ring-2 focus:ring-primary-500 focus:border-primary-500 outline-none resize-none"
              rows={4}
              placeholder="e.g. Add troubleshooting steps for connection timeout errors, improve the decision tree for memory pressure scenarios"
              value={improvement}
              onChange={(e) => setImprovement(e.target.value)}
            />
          </div>
          {improveMut.isError && (
            <div className="text-sm text-red-600 bg-red-50 px-3 py-2 rounded">
              {improveMut.error.message}
            </div>
          )}
        </div>
        <div className="px-6 py-4 border-t border-border flex justify-end gap-2">
          <button onClick={onClose} className="px-4 py-2 text-sm font-medium text-muted-foreground bg-secondary rounded-lg hover:bg-muted">
            Cancel
          </button>
          <button
            onClick={handleSubmit}
            disabled={!improvement.trim() || improveMut.isPending}
            className="px-4 py-2 text-sm font-medium text-white bg-primary-600 rounded-lg hover:bg-primary-700 disabled:opacity-50"
          >
            {improveMut.isPending ? "Improving..." : "Improve with LLM"}
          </button>
        </div>
      </div>
    </div>
  );
}

/* -- Delete Confirm Dialog ---------------------------------------- */

function DeleteConfirmDialog({
  skillName,
  onClose,
  onConfirm,
  deleting,
}: {
  skillName: string;
  onClose: () => void;
  onConfirm: () => void;
  deleting: boolean;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-background rounded-lg shadow-lg w-full max-w-sm p-6">
        <h3 className="text-lg font-semibold text-foreground mb-2">Delete Draft</h3>
        <p className="text-sm text-muted-foreground mb-4">
          Are you sure you want to delete <strong>{skillName}</strong>? This action cannot be undone.
        </p>
        <div className="flex justify-end gap-2">
          <button onClick={onClose} className="px-4 py-2 text-sm text-foreground border border-border rounded-lg hover:bg-secondary">
            Cancel
          </button>
          <button
            onClick={onConfirm}
            disabled={deleting}
            className="px-4 py-2 text-sm text-white bg-red-600 rounded-lg hover:bg-red-500 disabled:opacity-50"
          >
            {deleting ? "Deleting..." : "Delete"}
          </button>
        </div>
      </div>
    </div>
  );
}

/* -- Main Page ---------------------------------------------------- */

export default function SkillDetail() {
  const { t } = useLocale();
  const { name } = useParams<{ name: string }>();
  const navigate = useNavigate();
  const decodedName = decodeURIComponent(name ?? "");

  const { data: skill, isLoading, error, refetch } = useSkill(decodedName);
  const updateMut = useUpdateSkill();
  const deleteMut = useDeleteSkill();
  const reviewMut = useReviewSkill();
  const promoteMut = usePromoteSkill();

  const [tab, setTab] = useState<Tab>("view");
  const [editContent, setEditContent] = useState<string | null>(null);
  const [showImprove, setShowImprove] = useState(false);
  const [showDelete, setShowDelete] = useState(false);
  const [actionMsg, setActionMsg] = useState("");

  if (isLoading) return <Spinner label="Loading skill..." />;
  if (error) return <ErrorBanner message={(error as Error).message} onRetry={() => refetch()} />;
  if (!skill) return null;

  const bodyHtml = skill.body_markdown ? renderMarkdown(skill.body_markdown) : "";

  const handleStartEdit = () => {
    setEditContent(skill.body_markdown ?? "");
    setTab("edit");
  };

  const handleSaveEdit = () => {
    if (editContent === null) return;
    setActionMsg("");
    updateMut.mutate(
      { name: decodedName, content: editContent },
      {
        onSuccess: () => {
          setActionMsg("Saved successfully");
          setTab("view");
          setEditContent(null);
          refetch();
        },
      },
    );
  };

  const handleReview = () => {
    setActionMsg("");
    reviewMut.mutate(decodedName, {
      onSuccess: () => setTab("review"),
    });
  };

  const handlePromote = () => {
    setActionMsg("");
    promoteMut.mutate(decodedName, {
      onSuccess: () => {
        setActionMsg("Promoted to published");
        refetch();
      },
    });
  };

  const handleDelete = () => {
    deleteMut.mutate(decodedName, {
      onSuccess: () => navigate("/app/skills"),
    });
  };

  const tabClass = (v: Tab) =>
    `px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
      tab === v
        ? "border-primary-600 text-primary-600"
        : "border-transparent text-muted-foreground hover:text-foreground hover:border-border"
    }`;

  return (
    <div className="space-y-6 max-w-4xl mx-auto">
      {/* Back link */}
      <Link
        to="/app/skills"
        className="inline-flex items-center text-sm text-muted-foreground hover:text-foreground transition-colors"
      >
        <svg className="h-4 w-4 mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
        </svg>
        Back to Skills
      </Link>

      {/* Header card */}
      <Card>
        <CardBody>
          <div className="flex items-center justify-between mb-4">
            <div>
              <div className="flex items-center gap-3">
                <h1 className="text-2xl font-semibold text-foreground">{skill.name}</h1>
                {skill.is_draft ? (
                  <Badge className="bg-amber-100 text-amber-700">Draft</Badge>
                ) : (
                  <Badge className="bg-emerald-100 text-emerald-700">Published</Badge>
                )}
                <Badge className="bg-secondary text-muted-foreground">{skill.domain}</Badge>
              </div>
              <p className="text-sm text-muted-foreground mt-1">{skill.description}</p>
            </div>
            <div className="flex gap-2">
              {skill.is_draft && (
                <>
                  <button
                    onClick={() => setShowImprove(true)}
                    className="px-3 py-1.5 text-sm font-medium text-foreground bg-secondary rounded-lg hover:bg-muted"
                  >
                    Improve
                  </button>
                  <button
                    onClick={handleReview}
                    disabled={reviewMut.isPending}
                    className="px-3 py-1.5 text-sm font-medium text-foreground bg-secondary rounded-lg hover:bg-muted disabled:opacity-50"
                  >
                    {reviewMut.isPending ? "Loading..." : "Review"}
                  </button>
                  <button
                    onClick={handlePromote}
                    disabled={promoteMut.isPending}
                    className="px-3 py-1.5 text-sm font-medium text-white bg-emerald-600 rounded-lg hover:bg-emerald-700 disabled:opacity-50"
                  >
                    {promoteMut.isPending ? "Promoting..." : "Promote"}
                  </button>
                </>
              )}
            </div>
          </div>

          {/* Metadata row */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
            {skill.tools.length > 0 && (
              <div>
                <span className="text-muted-foreground block mb-1">Tools</span>
                <div className="flex flex-wrap gap-1">
                  {skill.tools.map((tool) => (
                    <span key={tool} className="px-1.5 py-0.5 bg-blue-50 text-blue-700 text-xs rounded">
                      {tool.split(".").pop()}
                    </span>
                  ))}
                </div>
              </div>
            )}
            {skill.references.length > 0 && (
              <div>
                <span className="text-muted-foreground block mb-1">References</span>
                <ul className="space-y-0.5">
                  {skill.references.map((r) => (
                    <li key={r} className="text-xs text-muted-foreground">{r}</li>
                  ))}
                </ul>
              </div>
            )}
            <div>
              <span className="text-muted-foreground block mb-1">Ref Count</span>
              <span>{skill.ref_count}</span>
            </div>
          </div>

          {/* Status messages */}
          {actionMsg && (
            <div className="mt-3 text-sm text-emerald-700 bg-emerald-50 px-3 py-2 rounded">
              {actionMsg}
            </div>
          )}
          {(updateMut.isError || deleteMut.isError || reviewMut.isError || promoteMut.isError) && (
            <div className="mt-3 text-sm text-red-600 bg-red-50 px-3 py-2 rounded">
              {(updateMut.error ?? deleteMut.error ?? reviewMut.error ?? promoteMut.error)?.message}
            </div>
          )}
        </CardBody>
      </Card>

      {/* Tabs */}
      <div className="border-b border-border flex gap-0">
        <button className={tabClass("view")} onClick={() => setTab("view")}>
          View
        </button>
        {skill.is_draft && (
          <button className={tabClass("edit")} onClick={handleStartEdit}>
            Edit
          </button>
        )}
        {reviewMut.data && (
          <button className={tabClass("review")} onClick={() => setTab("review")}>
            Review
          </button>
        )}
      </div>

      {/* Tab content */}
      {tab === "view" && (
        <Card>
          <CardBody>
            {bodyHtml ? (
              <div
                className="prose prose-sm max-w-none text-foreground"
                dangerouslySetInnerHTML={{ __html: bodyHtml }}
              />
            ) : (
              <p className="text-sm text-muted-foreground">No content.</p>
            )}
          </CardBody>
        </Card>
      )}

      {tab === "edit" && editContent !== null && (
        <Card>
          <CardBody>
            <textarea
              className="w-full border border-border rounded-lg px-3 py-2 text-sm font-mono focus:ring-2 focus:ring-primary-500 focus:border-primary-500 outline-none resize-y"
              rows={24}
              style={{ minHeight: "400px" }}
              value={editContent}
              onChange={(e) => setEditContent(e.target.value)}
            />
            <div className="flex justify-end gap-2 mt-4">
              <button
                onClick={() => { setTab("view"); setEditContent(null); }}
                className="px-4 py-2 text-sm text-foreground border border-border rounded-lg hover:bg-secondary"
              >
                {t("common.cancel")}
              </button>
              <button
                onClick={handleSaveEdit}
                disabled={updateMut.isPending}
                className="px-4 py-2 text-sm text-white bg-primary-600 rounded-lg hover:bg-primary-700 disabled:opacity-50"
              >
                {updateMut.isPending ? "Saving..." : t("common.save")}
              </button>
            </div>
          </CardBody>
        </Card>
      )}

      {tab === "review" && reviewMut.data && (
        <Card>
          <CardBody>
            <div className="mb-4">
              <Badge className="bg-blue-100 text-blue-700">{reviewMut.data.diff_summary}</Badge>
              {reviewMut.data.is_new && (
                <Badge className="ml-2 bg-amber-100 text-amber-700">New Skill</Badge>
              )}
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <h3 className="text-sm font-medium text-foreground mb-2">Draft</h3>
                <pre className="bg-secondary border border-border rounded-lg p-3 text-xs text-foreground max-h-96 overflow-y-auto whitespace-pre-wrap">
                  {reviewMut.data.draft_content}
                </pre>
              </div>
              <div>
                <h3 className="text-sm font-medium text-foreground mb-2">Published</h3>
                {reviewMut.data.published_content ? (
                  <pre className="bg-secondary border border-border rounded-lg p-3 text-xs text-foreground max-h-96 overflow-y-auto whitespace-pre-wrap">
                    {reviewMut.data.published_content}
                  </pre>
                ) : (
                  <p className="text-sm text-muted-foreground italic">No published version</p>
                )}
              </div>
            </div>
            {skill.is_draft && (
              <div className="flex justify-end gap-2 mt-4">
                <button
                  onClick={handlePromote}
                  disabled={promoteMut.isPending}
                  className="px-4 py-2 text-sm text-white bg-emerald-600 rounded-lg hover:bg-emerald-700 disabled:opacity-50"
                >
                  {promoteMut.isPending ? "Promoting..." : "Promote to Published"}
                </button>
              </div>
            )}
          </CardBody>
        </Card>
      )}

      {/* Delete (draft only) */}
      {skill.is_draft && (
        <div className="flex justify-end">
          <button
            onClick={() => setShowDelete(true)}
            className="px-4 py-2 text-sm font-medium text-red-600 bg-red-50 rounded-lg hover:bg-red-100"
          >
            Delete Draft
          </button>
        </div>
      )}

      {/* Modals */}
      {showImprove && (
        <ImproveDialog
          skillName={decodedName}
          onClose={() => setShowImprove(false)}
          onSuccess={() => refetch()}
        />
      )}
      {showDelete && (
        <DeleteConfirmDialog
          skillName={decodedName}
          onClose={() => setShowDelete(false)}
          onConfirm={handleDelete}
          deleting={deleteMut.isPending}
        />
      )}
    </div>
  );
}
