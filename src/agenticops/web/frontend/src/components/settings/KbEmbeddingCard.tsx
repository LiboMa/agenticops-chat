import { useState } from "react";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Spinner } from "@/components/ui/Spinner";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import { useConfirm } from "@/components/ui/ConfirmDialog";
import { ModelPicker } from "@/components/models/ModelPicker";
import { useLocale } from "@/i18n/LocaleContext";
import { useBootstrap, useReadOnly } from "@/hooks/useBootstrap";
import { useKbEmbedding, useReembed, useSetKbEmbedding } from "@/hooks/useModelProviders";
import { canChangeModels } from "@/lib/permissions";

/** Settings → Knowledge base → «Vector model» (MVP-2.9.0 N35): which model the case search embeds with — a
 *  provider's embedding model, or by default Titan while Bedrock is on — how many vectors are stored and by which
 *  model, and the rebuild that a new model needs (all or nothing; SQLite vector store only). */
export function KbEmbeddingCard() {
  const { t } = useLocale();
  const q = useKbEmbedding();
  const setModel = useSetKbEmbedding();
  const reembed = useReembed();
  const boot = useBootstrap();
  const readOnly = useReadOnly();
  const { confirm, dialog } = useConfirm();
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (q.isLoading) return <Card><CardBody><Spinner /></CardBody></Card>;
  if (q.error) return <Card><CardBody><ErrorBanner message={(q.error as Error).message} onRetry={() => q.refetch()} /></CardBody></Card>;
  if (!q.data) return null;
  const e = q.data;
  const editable = canChangeModels(boot.data) && !readOnly;
  const labelOf = (v: string) => { const label = e.presets.find((p) => p.value === v)?.label; return label && label !== v ? `${label} · ${v}` : v; };

  function change(ref: string) {
    setError(null); setMessage(null);
    setModel.mutate(ref, { onError: (err) => setError((err as Error).message) });
  }

  async function rebuild() {
    setError(null); setMessage(null);
    if (!(await confirm(t("kb.embedding.rebuildConfirm").replace("{model}", labelOf(e.model)),
                        { title: t("kb.embedding.rebuild") }))) return;
    reembed.mutate(undefined, {
      onSuccess: (r) => setMessage(t("kb.embedding.rebuilt").replace("{cases}", String(r.cases)).replace("{vectors}", String(r.vectors))),
      onError: (err) => setError((err as Error).message),
    });
  }

  const inUse = e.source === "none" ? t("kb.embedding.none") : labelOf(e.model);
  return (
    <Card>
      {dialog}
      <CardHeader>
        <div className="min-w-0">
          <h3 className="text-lg font-semibold text-foreground">{t("kb.embedding.title")}</h3>
          <p className="text-xs text-muted-foreground">{t("kb.embedding.subtitle")}</p>
        </div>
      </CardHeader>
      <CardBody className="space-y-3">
        <div className="grid grid-cols-1 gap-3 md:grid-cols-[minmax(0,1fr)_320px]">
          <div className="min-w-0 space-y-1 text-sm">
            <p className="text-foreground [overflow-wrap:anywhere]">{t("kb.embedding.inUse").replace("{model}", inUse)}</p>
            <p className="text-xs text-muted-foreground">
              {t("kb.embedding.stored").replace("{n}", String(e.vectors ?? "—"))
                .replace("{dim}", e.dimension ? String(e.dimension) : "—").replace("{model}", e.vectors ? labelOf(e.indexed_with) : "—")}
            </p>
          </div>
          <ModelPicker value={e.model_ref} presets={e.presets} purpose="embedding" onChange={change}
                       ariaLabel={t("kb.embedding.title")} disabled={!editable || setModel.isPending}
                       emptyOption={{ label: t("kb.embedding.default"), hint: t("kb.embedding.defaultHint") }} />
        </div>
        {e.needs_reembed && (
          <div role="status" className="flex flex-wrap items-center gap-3 rounded-md border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-800 dark:border-amber-700 dark:bg-amber-950/40 dark:text-amber-300">
            <span className="min-w-0 flex-1 [overflow-wrap:anywhere]">
              {t("kb.embedding.needsRebuild").replace("{old}", labelOf(e.indexed_with)).replace("{model}", labelOf(e.model))}
              {!e.can_reembed && ` ${t("kb.embedding.sqliteOnly").replace("{store}", e.store)}`}
            </span>
            {editable && e.can_reembed && (
              <button type="button" onClick={() => void rebuild()} disabled={reembed.isPending}
                      className="rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50">
                {reembed.isPending ? t("kb.embedding.rebuilding") : t("kb.embedding.rebuild")}
              </button>
            )}
          </div>
        )}
        {message && <p role="status" className="text-sm text-muted-foreground">{message}</p>}
        {error && <p role="alert" className="text-sm text-destructive [overflow-wrap:anywhere]">{error}</p>}
      </CardBody>
    </Card>
  );
}
