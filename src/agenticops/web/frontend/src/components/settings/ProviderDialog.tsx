import { useState } from "react";
import { ModalFrame } from "@/components/ui/ModalFrame";
import { useLocale } from "@/i18n/LocaleContext";
import { ApiError } from "@/api/client";
import {
  useCreateProvider, useRefreshModels, useTestDraft, useTestProvider, useUpdateProvider,
  type PlatformPreset, type ProbeResult, type ProviderRow,
} from "@/hooks/useModelProviders";
import {
  connectionChanged, connectionKey, createBody, draftBody, emptyForm, formFromRow, patchFromForm, saveMode, testNotes,
  validateProviderForm,
  type FormProblem, type ProviderForm, type ProviderKind, type TestNote,
} from "@/lib/providerForm";
import { ProbeSteps } from "./ProbeSteps";

import { fillPlaceholders } from "@/lib/placeholders";
/** A preset's words in the page's language; the server's English when there is no translation. */
function presetText(t: (k: string) => string, p: PlatformPreset, what: "label" | "notes"): string {
  const key = `settings.providers.preset.${p.preset}.${what}`;
  const text = t(key);
  return text === key ? p[what] : text;
}

const input = "w-full rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-primary disabled:opacity-60";
const label = "mb-1 block text-sm font-medium text-foreground";
const hint = "mt-1 text-xs text-muted-foreground";

/** Settings → Model providers → add or edit one (MVP-2.9.0 N35). Adding: pick the platform (its address and
 *  protocol are filled in), then the form. «Test connection» tests what the form holds before anything is stored
 *  (review of 2.9.0: the design's «保存之前可以先点「测试连接」»): a new provider, or an edit of its protocol / address /
 *  key / headers, is saved only after a test — switched off when the test failed. Saving a new one then reads its
 *  model list and runs the stored test. Editing: the key field is empty and an empty field keeps the stored key. */
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
  const [notes, setNotes] = useState<TestNote[]>([]);
  const [error, setError] = useState<string | null>(null);
  const create = useCreateProvider();
  const update = useUpdateProvider();
  const test = useTestProvider();
  const draft = useTestDraft();
  const [draftResult, setDraftResult] = useState<ProbeResult | null>(null);
  const [testedKey, setTestedKey] = useState<string | null>(null);
  const [savedOff, setSavedOff] = useState(false);
  const refresh = useRefreshModels(row?.name ?? "");
  const busy = create.isPending || update.isPending || test.isPending || refresh.isPending || draft.isPending;
  const title = row ? fillPlaceholders(t("settings.providers.editTitle"), { name: row.name }) : t("settings.providers.addTitle");

  if (!form) {
    return (
      <ModalFrame title={title} onClose={onClose} width="w-[min(720px,100%)]">
        <p className="mt-2 text-sm text-muted-foreground">{t("settings.providers.pickPlatform")}</p>
        <p className="mt-1 text-xs text-muted-foreground">{t("settings.providers.dataNotice")}</p>
        <ul className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {presets.map((p) => (
            <li key={p.preset}>
              <button type="button" onClick={() => { setPreset(p); setForm(emptyForm(p)); }}
                      className="h-full w-full rounded-lg border border-border bg-background p-3 text-left hover:border-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary">
                <span className="block text-sm font-semibold text-foreground">{presetText(t, p, "label")}</span>
                <span className="mt-0.5 block text-xs text-muted-foreground">
                  {t(`settings.providers.kind.${p.kind}`)}{p.needs_key ? ` · ${t("settings.providers.needsKey")}` : ""}
                </span>
                <span className="mt-2 block text-xs text-muted-foreground">{presetText(t, p, "notes")}</span>
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

  const currentKey = connectionKey(form, clearKey);
  const mode = saveMode({ changed: connectionChanged(row ?? null, form, clearKey), testedKey, currentKey,
                          result: draftResult });

  async function testDraft() {
    if (!form) return;
    const found = validateProviderForm(form, { isNew: !row, needsKey, hasStoredKey: !!row?.has_api_key && !clearKey });
    if (found) { setProblem(found); return; }
    setError(null); setDraftResult(null);
    try {
      setDraftResult(await draft.mutateAsync(draftBody(form, row ?? null, { clearKey, modelId: testModel })));
      setTestedKey(currentKey);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  }

  async function save() {
    if (!form || mode === "needs_test") return;
    const found = validateProviderForm(form, { isNew: !row, needsKey, hasStoredKey: !!row?.has_api_key && !clearKey });
    if (found) { setProblem(found); return; }
    setError(null); setNotes([]); setResult(null);
    const off = mode === "save_disabled";      // a provider whose test failed is never stored switched on
    try {
      if (row) {
        const body = patchFromForm(row, form, { clearKey });
        if (off) body.enabled = false;
        if (Object.keys(body).length) await update.mutateAsync({ name: row.name, body });
        onClose();
        return;
      }
      await create.mutateAsync({ ...createBody(form), enabled: !off });
      setSaved(form.name);
      setSavedOff(off);
      if (!off) await runTest(form.name);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  }

  async function runTest(name: string) {
    // the model list first (a fresh provider has none): the test then names its first chat model, or the one typed
    const listed = await refresh.mutateAsync(name).catch((e: unknown) => ({ error: e instanceof Error ? e.message : String(e) }));
    let failure: { code?: string; message: string } | null = null;
    try {
      setResult(await test.mutateAsync({ name, modelId: testModel.trim() || undefined }));
    } catch (e) {
      failure = { code: e instanceof ApiError ? e.code : undefined, message: e instanceof Error ? e.message : String(e) };
    }
    setNotes(testNotes(listed?.error ?? null, failure));   // both, when the list failed and the test had no model
  }

  if (saved) {
    return (
      <ModalFrame title={title} onClose={onClose} width="w-[min(560px,100%)]">
        <p role="status" className="mt-3 text-sm text-foreground">
          {fillPlaceholders(t(savedOff ? "settings.providers.savedDisabled" : "settings.providers.savedTesting"), { name: saved })}
        </p>
        {busy && <p className="mt-2 text-sm text-muted-foreground">{t("settings.providers.testing")}</p>}
        {result && <ProbeSteps result={result} />}
        {notes.map((n, i) => (
          <p key={i} className="mt-3 text-sm text-amber-700 dark:text-amber-300 [overflow-wrap:anywhere]">
            {"text" in n ? n.text : fillPlaceholders(t(n.key), { error: n.error ?? "" })}
          </p>
        ))}
        <div className="mt-5 flex justify-end gap-2">
          {!savedOff && <button type="button" disabled={busy} onClick={() => { setResult(null); setNotes([]); void runTest(saved); }}
                  className="rounded-md border border-border px-3 py-2 text-sm hover:bg-muted disabled:opacity-50">
            {t("settings.providers.testAgain")}
          </button>}
          <button type="button" onClick={onClose} className="rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90">
            {t("settings.providers.done")}
          </button>
        </div>
      </ModalFrame>
    );
  }

  return (
    <ModalFrame title={title} onClose={onClose} width="w-[min(600px,100%)]" keepOnOutside>
      <form className="mt-4 space-y-4" onSubmit={(e) => { e.preventDefault(); void (mode === "needs_test" ? testDraft() : save()); }} noValidate>
        {!row && preset && (
          <p className="text-sm text-muted-foreground">
            {presetText(t, preset, "label")}
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
                   placeholder={preset ? presetText(t, preset, "label") : ""} />
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
        {(!row || mode !== "save_plain") && (
          <div>
            <label htmlFor="pv-test-model" className={label}>
              {t("settings.providers.field.testModel")}<span className="ml-1 font-normal text-muted-foreground">{t("settings.providers.optional")}</span>
            </label>
            <input id="pv-test-model" className={`${input} font-mono`} value={testModel} autoComplete="off"
                   onChange={(e) => setTestModel(e.target.value)} placeholder="qwen3:32b" />
            <p className={hint}>{t("settings.providers.testModelHint")}</p>
          </div>
        )}
        {draftResult && testedKey === currentKey && <ProbeSteps result={draftResult} />}
        {mode === "needs_test" && <p className="text-sm text-muted-foreground">{t("settings.providers.testFirst")}</p>}
        {mode === "save_disabled" && (
          <p role="status" className="text-sm text-amber-700 dark:text-amber-300">{t("settings.providers.testFailedSaveOff")}</p>
        )}
        {error && <p role="alert" className="text-sm text-destructive [overflow-wrap:anywhere]">{error}</p>}
        <div className="flex flex-wrap justify-end gap-2 pt-1">
          <button type="button" onClick={onClose} className="rounded-md border border-border px-3 py-2 text-sm hover:bg-muted">
            {t("common.cancel")}
          </button>
          {(mode === "save" || mode === "save_disabled") && (
            <button type="button" disabled={busy} onClick={() => void testDraft()}
                    className="rounded-md border border-border px-3 py-2 text-sm hover:bg-muted disabled:opacity-50">
              {t("settings.providers.testAgain")}
            </button>
          )}
          <button type="submit" disabled={busy}
                  className="rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50">
            {draft.isPending ? t("settings.providers.testing")
              : mode === "needs_test" ? t("settings.providers.testConnection")
              : mode === "save_disabled" ? t("settings.providers.saveDisabled") : t("common.save")}
          </button>
        </div>
      </form>
    </ModalFrame>
  );
}
