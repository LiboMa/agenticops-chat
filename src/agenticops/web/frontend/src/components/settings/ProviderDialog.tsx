import { useState } from "react";
import { ModalFrame } from "@/components/ui/ModalFrame";
import { useLocale } from "@/i18n/LocaleContext";
import { ApiError } from "@/api/client";
import {
  useCreateProvider, useRefreshModels, useTestProvider, useUpdateProvider,
  type PlatformPreset, type ProbeResult, type ProviderRow,
} from "@/hooks/useModelProviders";
import {
  createBody, emptyForm, formFromRow, patchFromForm, validateProviderForm,
  type FormProblem, type ProviderForm, type ProviderKind,
} from "@/lib/providerForm";
import { ProbeSteps } from "./ProbeSteps";

const input = "w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-primary disabled:opacity-60";
const label = "mb-1 block text-sm font-medium text-foreground";
const hint = "mt-1 text-xs text-muted-foreground";

/** Settings → Model providers → add or edit one (MVP-2.9.0 N35). Adding: pick the platform (its address and
 *  protocol are filled in), then the form; «Save and test» stores it, reads its model list and runs the connection
 *  test, all in this dialog — a key is only ever sent once, so the test runs on what was stored. Editing: the key
 *  field is empty and an empty field keeps the stored key. */
export function ProviderDialog({ presets, row, onClose }: {
  presets: PlatformPreset[];
  /** the provider being edited; none = a new one */
  row?: ProviderRow;
  onClose: () => void;
}) {
  const { t } = useLocale();
  const [preset, setPreset] = useState<PlatformPreset | null>(
    row ? presets.find((p) => p.preset === row.preset) ?? null : null);
  const [form, setForm] = useState<ProviderForm | null>(row ? formFromRow(row) : null);
  const [problem, setProblem] = useState<FormProblem | null>(null);
  const [clearKey, setClearKey] = useState(false);
  const [testModel, setTestModel] = useState("");
  const [saved, setSaved] = useState<string | null>(null);   // the name, once a new provider is stored
  const [result, setResult] = useState<ProbeResult | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const create = useCreateProvider();
  const update = useUpdateProvider();
  const test = useTestProvider();
  const refresh = useRefreshModels(saved ?? row?.name ?? "");
  const busy = create.isPending || update.isPending || test.isPending || refresh.isPending;
  const title = row ? t("settings.providers.editTitle").replace("{name}", row.name) : t("settings.providers.addTitle");

  if (!form) {
    return (
      <ModalFrame title={title} onClose={onClose} width="w-[min(720px,100%)]">
        <p className="mt-2 text-sm text-muted-foreground">{t("settings.providers.pickPlatform")}</p>
        <ul className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {presets.map((p) => (
            <li key={p.preset}>
              <button type="button" onClick={() => { setPreset(p); setForm(emptyForm(p)); }}
                      className="h-full w-full rounded-lg border border-border bg-background p-3 text-left hover:border-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary">
                <span className="block text-sm font-semibold text-foreground">{p.label}</span>
                <span className="mt-0.5 block text-xs text-muted-foreground">
                  {t(`settings.providers.kind.${p.kind}`)}{p.needs_key ? ` · ${t("settings.providers.needsKey")}` : ""}
                </span>
                <span className="mt-2 block text-xs text-muted-foreground">{p.notes}</span>
              </button>
            </li>
          ))}
        </ul>
      </ModalFrame>
    );
  }

  const needsKey = preset?.needs_key ?? false;
  const set = (patch: Partial<ProviderForm>) => { setForm({ ...form, ...patch }); setProblem(null); };
  const fieldError = (field: FormProblem["field"]) =>
    problem?.field === field ? <p role="alert" className="mt-1 text-xs text-destructive">{t(`settings.providers.problem.${problem.reason}`)}</p> : null;

  async function save() {
    if (!form) return;
    const found = validateProviderForm(form, { isNew: !row, needsKey, hasStoredKey: !!row?.has_api_key && !clearKey });
    if (found) { setProblem(found); return; }
    setError(null); setNote(null); setResult(null);
    try {
      if (row) {
        const body = patchFromForm(row, form, { clearKey });
        if (Object.keys(body).length) await update.mutateAsync({ name: row.name, body });
        onClose();
        return;
      }
      await create.mutateAsync(createBody(form));
      setSaved(form.name);
      await runTest(form.name);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  }

  async function runTest(name: string) {
    // the model list first (a fresh provider has none): the test then names its first chat model, or the one typed
    const listed = await refresh.mutateAsync().catch(() => null);
    if (listed?.error) setNote(t("settings.providers.listFailed").replace("{error}", listed.error));
    try {
      setResult(await test.mutateAsync({ name, modelId: testModel.trim() || undefined }));
    } catch (e) {
      setNote(e instanceof ApiError && e.code === "no_model" ? t("settings.providers.noModelYet")
        : e instanceof Error ? e.message : String(e));
    }
  }

  if (saved) {
    return (
      <ModalFrame title={title} onClose={onClose} width="w-[min(560px,100%)]">
        <p role="status" className="mt-3 text-sm text-foreground">{t("settings.providers.savedTesting").replace("{name}", saved)}</p>
        {busy && <p className="mt-2 text-sm text-muted-foreground">{t("settings.providers.testing")}</p>}
        {result && <ProbeSteps result={result} />}
        {note && <p className="mt-3 text-sm text-amber-700 dark:text-amber-300">{note}</p>}
        <div className="mt-5 flex justify-end gap-2">
          <button type="button" disabled={busy} onClick={() => { setResult(null); setNote(null); void runTest(saved); }}
                  className="rounded-md border border-border px-3 py-2 text-sm hover:bg-muted disabled:opacity-50">
            {t("settings.providers.testAgain")}
          </button>
          <button type="button" onClick={onClose} className="rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90">
            {t("settings.providers.done")}
          </button>
        </div>
      </ModalFrame>
    );
  }

  return (
    <ModalFrame title={title} onClose={onClose} width="w-[min(600px,100%)]" keepOnOutside>
      <form className="mt-4 space-y-4" onSubmit={(e) => { e.preventDefault(); void save(); }} noValidate>
        {!row && preset && (
          <p className="text-sm text-muted-foreground">
            {preset.label}
            <button type="button" onClick={() => { setForm(null); setPreset(null); }} className="ml-2 text-primary hover:underline">
              {t("settings.providers.changePlatform")}
            </button>
          </p>
        )}
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div>
            <label htmlFor="pv-name" className={label}>{t("settings.providers.field.name")}</label>
            <input id="pv-name" className={`${input} font-mono`} value={form.name} disabled={!!row} autoComplete="off"
                   onChange={(e) => set({ name: e.target.value.trim().toLowerCase() })} placeholder="local-llm" />
            {row ? <p className={hint}>{t("settings.providers.nameFixed")}</p> : <p className={hint}>{t("settings.providers.nameHint")}</p>}
            {fieldError("name")}
          </div>
          <div>
            <label htmlFor="pv-display" className={label}>{t("settings.providers.field.displayName")}</label>
            <input id="pv-display" className={input} value={form.displayName} onChange={(e) => set({ displayName: e.target.value })}
                   placeholder={preset?.label ?? ""} />
          </div>
        </div>
        <div>
          <label htmlFor="pv-url" className={label}>{t("settings.providers.field.baseUrl")}</label>
          <input id="pv-url" className={`${input} font-mono`} value={form.baseUrl} inputMode="url" autoComplete="off"
                 onChange={(e) => set({ baseUrl: e.target.value })} placeholder="http://localhost:4000/v1" />
          <p className={hint}>{t(`settings.providers.urlHint.${form.kind}`)}</p>
          {fieldError("baseUrl")}
        </div>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div>
            <label htmlFor="pv-kind" className={label}>{t("settings.providers.field.kind")}</label>
            <select id="pv-kind" className={input} value={form.kind} onChange={(e) => set({ kind: e.target.value as ProviderKind })}>
              <option value="openai_compatible">{t("settings.providers.kind.openai_compatible")}</option>
              <option value="anthropic_compatible">{t("settings.providers.kind.anthropic_compatible")}</option>
            </select>
          </div>
          <div>
            <label htmlFor="pv-timeout" className={label}>{t("settings.providers.field.timeout")}</label>
            <input id="pv-timeout" className={input} value={form.timeout} inputMode="numeric" onChange={(e) => set({ timeout: e.target.value })} />
            {fieldError("timeout")}
          </div>
        </div>
        <div>
          <label htmlFor="pv-key" className={label}>
            {t("settings.providers.field.apiKey")}{!needsKey && <span className="ml-1 font-normal text-muted-foreground">{t("settings.providers.optional")}</span>}
          </label>
          <input id="pv-key" type="password" className={`${input} font-mono`} value={form.apiKey} autoComplete="new-password"
                 disabled={clearKey} onChange={(e) => set({ apiKey: e.target.value })}
                 placeholder={row?.has_api_key ? t("settings.providers.keySaved") : ""} />
          {row?.has_api_key && (
            <label className="mt-2 flex items-center gap-2 text-sm text-foreground">
              <input type="checkbox" checked={clearKey} onChange={(e) => { setClearKey(e.target.checked); setProblem(null); }} />
              {t("settings.providers.clearKey")}
            </label>
          )}
          {fieldError("apiKey")}
        </div>
        <div>
          <label htmlFor="pv-headers" className={label}>
            {t("settings.providers.field.headers")}<span className="ml-1 font-normal text-muted-foreground">{t("settings.providers.optional")}</span>
          </label>
          <textarea id="pv-headers" rows={2} className={`${input} font-mono`} value={form.headersText}
                    onChange={(e) => set({ headersText: e.target.value })} placeholder="HTTP-Referer: https://ops.example.com" />
          <p className={hint}>{t("settings.providers.headersHint")}</p>
          {fieldError("headers")}
        </div>
        {!row && (
          <div>
            <label htmlFor="pv-test-model" className={label}>
              {t("settings.providers.field.testModel")}<span className="ml-1 font-normal text-muted-foreground">{t("settings.providers.optional")}</span>
            </label>
            <input id="pv-test-model" className={`${input} font-mono`} value={testModel} autoComplete="off"
                   onChange={(e) => setTestModel(e.target.value)} placeholder="qwen3:32b" />
            <p className={hint}>{t("settings.providers.testModelHint")}</p>
          </div>
        )}
        {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
        <div className="flex justify-end gap-2 pt-1">
          <button type="button" onClick={onClose} className="rounded-md border border-border px-3 py-2 text-sm hover:bg-muted">
            {t("common.cancel")}
          </button>
          <button type="submit" disabled={busy}
                  className="rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50">
            {row ? t("common.save") : t("settings.providers.saveAndTest")}
          </button>
        </div>
      </form>
    </ModalFrame>
  );
}
