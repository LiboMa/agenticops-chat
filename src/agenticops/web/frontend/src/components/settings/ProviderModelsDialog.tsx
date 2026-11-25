import { useMemo, useState } from "react";
import { ModalFrame } from "@/components/ui/ModalFrame";
import { Switch } from "@/components/ui/Switch";
import { Spinner } from "@/components/ui/Spinner";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import { useLocale } from "@/i18n/LocaleContext";
import { ApiError } from "@/api/client";
import {
  useAddModel, usePatchModel, useProviderModels, useRefreshModels,
  type ProviderModel, type ProviderRow, type Purpose, type Reasoning,
} from "@/hooks/useModelProviders";
import { draftOf, filterModels, modelPatch, priceLabel, toolsState, type ModelDraft } from "@/lib/providerModels";
import { refusalText } from "@/lib/modelRefs";

const input = "w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-primary";
const chip = "rounded px-1.5 py-0.5 text-[11px] font-medium";

/** Settings → Model providers → a provider's models (MVP-2.9.0 N35): search, filter by use, read the provider's list
 *  again, add one by hand, turn one on or off, and open one to correct what it can do — a field an admin set is
 *  marked with a dot and kept over the next refresh. */
export function ProviderModelsDialog({ provider, canEdit, onClose }: { provider: ProviderRow; canEdit: boolean; onClose: () => void }) {
  const { t } = useLocale();
  const q = useProviderModels(provider.name);
  const refresh = useRefreshModels(provider.name);
  const add = useAddModel(provider.name);
  const patch = usePatchModel(provider.name);
  const [query, setQuery] = useState("");
  const [purpose, setPurpose] = useState<"all" | Purpose>("all");
  const [open, setOpen] = useState<string | null>(null);
  const [newId, setNewId] = useState("");
  const [newPurpose, setNewPurpose] = useState<Purpose>("chat");
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const shown = useMemo(() => filterModels(q.data ?? [], { purpose, query }), [q.data, purpose, query]);

  async function doRefresh() {
    setError(null); setMessage(null);
    try {
      const r = await refresh.mutateAsync();
      setMessage(r.error ? t("settings.providers.listFailed").replace("{error}", r.error)
        : t("settings.providers.refreshed").replace("{added}", String(r.added)).replace("{updated}", String(r.updated))
            .replace("{unchanged}", String(r.unchanged)));
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  }

  async function doAdd() {
    if (!newId.trim()) return;
    setError(null); setMessage(null);
    try {
      await add.mutateAsync({ model_id: newId.trim(), purpose: newPurpose });
      setOpen(newId.trim()); setNewId("");
    } catch (e) { setError(e instanceof ApiError ? refusalText(t, e) : String(e)); }
  }

  async function toggle(m: ProviderModel, enabled: boolean) {
    setError(null);
    try { await patch.mutateAsync({ modelId: m.model_id, body: { enabled } }); }
    catch (e) { setError(e instanceof ApiError ? refusalText(t, e) : String(e)); }
  }

  return (
    <ModalFrame title={t("settings.providers.modelsTitle").replace("{name}", provider.display_name || provider.name)}
                onClose={onClose} width="w-[min(860px,100%)]">
      <div className="mt-4 flex flex-wrap items-center gap-2">
        <input type="search" value={query} onChange={(e) => setQuery(e.target.value)} aria-label={t("settings.providers.searchModels")}
               placeholder={t("settings.providers.searchModels")} className={`${input} max-w-xs flex-1`} />
        <select value={purpose} onChange={(e) => setPurpose(e.target.value as "all" | Purpose)} className={`${input} w-auto`}
                aria-label={t("settings.providers.purposeFilter")}>
          <option value="all">{t("settings.providers.purpose.all")}</option>
          <option value="chat">{t("settings.providers.purpose.chat")}</option>
          <option value="embedding">{t("settings.providers.purpose.embedding")}</option>
        </select>
        {canEdit && (
          <button type="button" onClick={() => void doRefresh()} disabled={refresh.isPending}
                  className="ml-auto rounded-md border border-border px-3 py-1.5 text-sm hover:bg-muted disabled:opacity-50">
            {refresh.isPending ? t("settings.providers.refreshing") : t("settings.providers.refreshList")}
          </button>
        )}
      </div>
      {canEdit && (
        <form className="mt-3 flex flex-wrap items-center gap-2" onSubmit={(e) => { e.preventDefault(); void doAdd(); }}>
          <input value={newId} onChange={(e) => setNewId(e.target.value)} aria-label={t("settings.providers.addModelId")}
                 placeholder={t("settings.providers.addModelId")} className={`${input} max-w-xs flex-1 font-mono`} />
          <select value={newPurpose} onChange={(e) => setNewPurpose(e.target.value as Purpose)} className={`${input} w-auto`}
                  aria-label={t("settings.providers.field.purpose")}>
            <option value="chat">{t("settings.providers.purpose.chat")}</option>
            <option value="embedding">{t("settings.providers.purpose.embedding")}</option>
          </select>
          <button type="submit" disabled={!newId.trim() || add.isPending}
                  className="rounded-md border border-border px-3 py-1.5 text-sm hover:bg-muted disabled:opacity-50">
            {t("settings.providers.addModel")}
          </button>
        </form>
      )}
      {message && <p role="status" className="mt-3 text-sm text-muted-foreground">{message}</p>}
      {error && <p role="alert" className="mt-3 text-sm text-destructive [overflow-wrap:anywhere]">{error}</p>}
      <div className="mt-3 max-h-[55vh] overflow-auto rounded-md border border-border">
        {q.isLoading ? <div className="p-6"><Spinner /></div>
          : q.error ? <div className="p-3"><ErrorBanner message={(q.error as Error).message} onRetry={() => q.refetch()} /></div>
          : shown.length === 0 ? (
            <p className="p-6 text-center text-sm text-muted-foreground">
              {(q.data ?? []).length === 0 ? t("settings.providers.noModels") : t("settings.providers.noMatch")}
            </p>
          ) : (
            <ul className="divide-y divide-border">
              {shown.map((m) => (
                <li key={m.model_id}>
                  <ModelRow m={m} canEdit={canEdit} open={open === m.model_id}
                            onToggleOpen={() => setOpen(open === m.model_id ? null : m.model_id)}
                            onEnabled={(v) => void toggle(m, v)}
                            onSave={async (body) => { await patch.mutateAsync({ modelId: m.model_id, body }); setOpen(null); }} />
                </li>
              ))}
            </ul>
          )}
      </div>
    </ModalFrame>
  );
}

function Badges({ m }: { m: ProviderModel }) {
  const { t } = useLocale();
  const tools = toolsState(m);
  const price = priceLabel(m);
  const toolsTone = tools === "yes" ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300"
    : tools === "no" ? "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300" : "bg-muted text-muted-foreground";
  return (
    <span className="flex flex-wrap gap-1">
      {m.purpose === "chat" && <span className={`${chip} ${toolsTone}`}>{t(`settings.providers.tools.${tools}`)}</span>}
      {m.purpose === "embedding" && <span className={`${chip} bg-muted text-muted-foreground`}>{t("settings.providers.purpose.embedding")}</span>}
      {m.supports_images && <span className={`${chip} bg-muted text-muted-foreground`}>{t("settings.providers.badge.images")}</span>}
      {m.supports_documents && <span className={`${chip} bg-muted text-muted-foreground`}>{t("settings.providers.badge.documents")}</span>}
      {m.reasoning !== "none" && <span className={`${chip} bg-muted text-muted-foreground`}>{t("settings.providers.badge.reasoning")}</span>}
      {m.context_window && <span className={`${chip} bg-muted text-muted-foreground`}>{Math.round(m.context_window / 1000)}k</span>}
      <span className={`${chip} ${price ? "bg-muted text-muted-foreground" : "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300"}`}>
        {price ?? t("settings.providers.unpriced")}
      </span>
    </span>
  );
}

function ModelRow({ m, canEdit, open, onToggleOpen, onEnabled, onSave }: {
  m: ProviderModel; canEdit: boolean; open: boolean; onToggleOpen: () => void; onEnabled: (v: boolean) => void;
  onSave: (body: Record<string, unknown>) => Promise<void>;
}) {
  const { t } = useLocale();
  const id = `pm-${m.model_id.replace(/[^A-Za-z0-9_-]/g, "_")}`;
  return (
    <div className={m.enabled ? "" : "opacity-60"}>
      <div className="flex items-start gap-3 px-3 py-2">
        <Switch checked={m.enabled} onCheckedChange={onEnabled} disabled={!canEdit}
                label={`${t("settings.providers.enabled")}: ${m.model_id}`} />
        <button type="button" onClick={onToggleOpen} aria-expanded={open} aria-controls={id}
                className="min-w-0 flex-1 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary rounded">
          <span className="block truncate text-sm font-medium text-foreground">{m.label}</span>
          <span className="block font-mono text-xs text-muted-foreground [overflow-wrap:anywhere]">{m.model_id}{m.source === "manual" ? ` · ${t("settings.providers.manual")}` : ""}</span>
          <span className="mt-1 block"><Badges m={m} /></span>
        </button>
      </div>
      {open && <div id={id}><ModelEditor m={m} canEdit={canEdit} onSave={onSave} /></div>}
    </div>
  );
}

const FIELD_KEY: Record<keyof ModelDraft, string> = {
  label: "label", purpose: "purpose", contextWindow: "context_window", maxOutput: "max_output_tokens", tools: "supports_tools",
  images: "supports_images", documents: "supports_documents", reasoning: "reasoning", priceInput: "price_input",
  priceOutput: "price_output", priceCacheRead: "price_cache_read", priceCacheWrite: "price_cache_write",
};

function ModelEditor({ m, canEdit, onSave }: { m: ProviderModel; canEdit: boolean; onSave: (body: Record<string, unknown>) => Promise<void> }) {
  const { t } = useLocale();
  const [d, setD] = useState<ModelDraft>(() => draftOf(m));
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (patch: Partial<ModelDraft>) => { setD({ ...d, ...patch }); setError(null); };
  const dot = (f: keyof ModelDraft) => m.manual_fields.includes(FIELD_KEY[f])
    ? <span title={t("settings.providers.setByHand")} aria-label={t("settings.providers.setByHand")} className="ml-1 inline-block h-1.5 w-1.5 rounded-full bg-primary align-middle" />
    : null;
  const lbl = (f: keyof ModelDraft, key: string) => (
    <span className="mb-1 block text-xs font-medium text-foreground">{t(`settings.providers.field.${key}`)}{dot(f)}</span>);

  async function save() {
    const body = modelPatch(m, d);
    if ("error" in body) { setError(t("settings.providers.badField").replace("{field}", t(`settings.providers.field.${body.error}`))); return; }
    if (!Object.keys(body).length) return;
    setBusy(true);
    try { await onSave(body); } catch (e) { setError(e instanceof Error ? e.message : String(e)); } finally { setBusy(false); }
  }

  return (
    <fieldset disabled={!canEdit} className="m-0 grid grid-cols-2 gap-3 border-0 bg-muted/40 px-3 py-3 sm:grid-cols-4">
      <label className="col-span-2">{lbl("label", "label")}<input className={input} value={d.label} onChange={(e) => set({ label: e.target.value })} /></label>
      <label>{lbl("purpose", "purpose")}
        <select className={input} value={d.purpose} onChange={(e) => set({ purpose: e.target.value as Purpose })}>
          <option value="chat">{t("settings.providers.purpose.chat")}</option>
          <option value="embedding">{t("settings.providers.purpose.embedding")}</option>
        </select>
      </label>
      <label>{lbl("tools", "tools")}
        <select className={input} value={d.tools} onChange={(e) => set({ tools: e.target.value as ModelDraft["tools"] })}>
          <option value="unknown">{t("settings.providers.toolsChoice.unknown")}</option>
          <option value="yes">{t("settings.providers.toolsChoice.yes")}</option>
          <option value="no">{t("settings.providers.toolsChoice.no")}</option>
        </select>
      </label>
      <label>{lbl("contextWindow", "contextWindow")}<input className={input} inputMode="numeric" value={d.contextWindow} onChange={(e) => set({ contextWindow: e.target.value })} /></label>
      <label>{lbl("maxOutput", "maxOutput")}<input className={input} inputMode="numeric" value={d.maxOutput} onChange={(e) => set({ maxOutput: e.target.value })} /></label>
      <label className="col-span-2">{lbl("reasoning", "reasoning")}
        <select className={input} value={d.reasoning} onChange={(e) => set({ reasoning: e.target.value as Reasoning })}>
          <option value="none">{t("settings.providers.reasoning.none")}</option>
          <option value="openai_effort">{t("settings.providers.reasoning.openai_effort")}</option>
          <option value="anthropic_thinking">{t("settings.providers.reasoning.anthropic_thinking")}</option>
        </select>
      </label>
      <label>{lbl("priceInput", "priceInput")}<input className={input} inputMode="decimal" value={d.priceInput} onChange={(e) => set({ priceInput: e.target.value })} /></label>
      <label>{lbl("priceOutput", "priceOutput")}<input className={input} inputMode="decimal" value={d.priceOutput} onChange={(e) => set({ priceOutput: e.target.value })} /></label>
      <label>{lbl("priceCacheRead", "priceCacheRead")}<input className={input} inputMode="decimal" value={d.priceCacheRead} onChange={(e) => set({ priceCacheRead: e.target.value })} /></label>
      <label>{lbl("priceCacheWrite", "priceCacheWrite")}<input className={input} inputMode="decimal" value={d.priceCacheWrite} onChange={(e) => set({ priceCacheWrite: e.target.value })} /></label>
      <label className="col-span-2 flex items-center gap-2 text-sm"><input type="checkbox" checked={d.images} onChange={(e) => set({ images: e.target.checked })} />{t("settings.providers.field.images")}{dot("images")}</label>
      <label className="col-span-2 flex items-center gap-2 text-sm"><input type="checkbox" checked={d.documents} onChange={(e) => set({ documents: e.target.checked })} />{t("settings.providers.field.documents")}{dot("documents")}</label>
      <p className="col-span-2 text-xs text-muted-foreground sm:col-span-3">{t("settings.providers.priceHint")}</p>
      {canEdit && (
        <div className="col-span-2 flex items-center justify-end gap-2 sm:col-span-1">
          <button type="button" onClick={() => void save()} disabled={busy}
                  className="rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50">
            {t("common.save")}
          </button>
        </div>
      )}
      {error && <p role="alert" className="col-span-full text-sm text-destructive">{error}</p>}
    </fieldset>
  );
}
