import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { useAccounts } from "@/hooks/useAccounts";
import { useResources } from "@/hooks/useResources";
import { useCreateChange } from "@/hooks/useChanges";
import { useLocale } from "@/i18n/LocaleContext";

interface Props {
  onClose: () => void;
  onCreated: (id: number) => void;
  initial?: Partial<{ title: string; description: string; account_name: string; targets: string[]; requested_change_type: "normal" | "emergency"; justification: string }>;
}

export function NewChangeDialog({ onClose, onCreated, initial }: Props) {
  const { t } = useLocale();
  const accounts = useAccounts();
  const create = useCreateChange();
  const [title, setTitle] = useState(initial?.title ?? "");
  const [description, setDescription] = useState(initial?.description ?? "");
  const [accountName, setAccountName] = useState(initial?.account_name ?? "");
  const [targets, setTargets] = useState<string[]>(initial?.targets ?? []);
  const [search, setSearch] = useState("");
  const [type, setType] = useState<"normal" | "emergency">(initial?.requested_change_type ?? "normal");
  const [justification, setJustification] = useState(initial?.justification ?? "");

  const enabledAccounts = (accounts.data ?? []).filter((a) => a.is_enabled);
  // A copy-as-new whose account has since been disabled: keep the name visible so the sent value matches the field.
  const showInitialAccount = accountName !== "" && !enabledAccounts.some((a) => a.name === accountName);
  const accountId = accounts.data?.find((a) => a.name === accountName)?.id;
  const trimmed = search.trim();
  const matches = useResources({ search: trimmed, account_id: accountId, limit: 20 }, trimmed.length >= 2);

  // ESC in the capture phase (F7): closes only this dialog, and does nothing while a create is in flight —
  // closing mid-request would create the change without navigating to it and would hide the error.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      e.stopPropagation();
      if (!create.isPending) onClose();
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [create.isPending, onClose]);

  const close = () => { if (!create.isPending) onClose(); };
  const addTarget = (v: string) => { const x = v.trim(); if (x && !targets.includes(x)) setTargets([...targets, x]); setSearch(""); };
  const canSubmit = title.trim() !== "" && description.trim() !== "" && !create.isPending;
  const submit = () => {
    if (!canSubmit) return;
    create.mutate(
      { title: title.trim(), description: description.trim(), account_name: accountName || undefined, targets, requested_change_type: type, justification: justification.trim() || undefined },
      { onSuccess: (cr) => onCreated(cr.id) },
    );
  };

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="fixed inset-0 bg-black/40 backdrop-blur-sm" onClick={close} />
      <div role="dialog" aria-modal="true" className="relative bg-card border border-border rounded-xl shadow-2xl w-full max-w-lg mx-4 animate-[slideInRight_0.2s_ease-out]">
        <div className="px-6 py-4 border-b border-border flex items-center justify-between">
          <h2 className="text-lg font-semibold text-foreground">{t("plans.newChange")}</h2>
          <button type="button" onClick={close} className="text-muted-foreground hover:text-foreground">✕</button>
        </div>
        <div className="px-6 py-4 space-y-3 max-h-[70vh] overflow-y-auto">
          <label className="block text-sm"><span className="text-muted-foreground">{t("plans.form.title")}</span>
            <input autoFocus value={title} onChange={(e) => setTitle(e.target.value)} maxLength={300} className="mt-1 w-full border border-border bg-background rounded-lg px-3 py-2 text-sm" /></label>
          <label className="block text-sm"><span className="text-muted-foreground">{t("plans.form.description")}</span>
            <textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={4} className="mt-1 w-full border border-border bg-background rounded-lg px-3 py-2 text-sm" /></label>
          <label className="block text-sm"><span className="text-muted-foreground">{t("plans.form.account")}</span>
            <select value={accountName} onChange={(e) => setAccountName(e.target.value)} className="mt-1 w-full border border-border bg-background rounded-lg px-3 py-2 text-sm">
              <option value="">{t("plans.form.accountAny")}</option>
              {enabledAccounts.map((a) => <option key={a.id} value={a.name}>{a.name} ({a.provider})</option>)}
              {showInitialAccount && <option value={accountName}>{accountName}</option>}
            </select></label>
          <div className="text-sm">
            <span className="text-muted-foreground">{t("plans.form.targets")}</span>
            <div className="mt-1 flex flex-wrap gap-1">
              {targets.map((x) => <span key={x} className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-secondary text-xs font-mono">{x}<button type="button" onClick={() => setTargets(targets.filter((y) => y !== x))}>✕</button></span>)}
            </div>
            <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder={t("plans.form.targetsHint")}
              onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addTarget(search); } }}
              className="mt-1 w-full border border-border bg-background rounded-lg px-3 py-2 text-sm font-mono" />
            {trimmed.length >= 2 && (matches.data?.items.length ?? 0) > 0 && (
              <ul className="mt-1 border border-border rounded-lg divide-y divide-border max-h-40 overflow-y-auto">
                {matches.data!.items.map((r) => (
                  <li key={r.id}><button type="button" onClick={() => addTarget(r.resource_id)} className="w-full text-left px-3 py-1.5 text-xs hover:bg-secondary">
                    <span className="font-mono">{r.resource_id}</span> <span className="text-muted-foreground">{r.resource_type} · {r.resource_name ?? ""} · {r.region}</span></button></li>
                ))}
              </ul>
            )}
          </div>
          <label className="block text-sm"><span className="text-muted-foreground">{t("plans.form.type")}</span>
            <select value={type} onChange={(e) => setType(e.target.value as "normal" | "emergency")} className="mt-1 w-full border border-border bg-background rounded-lg px-3 py-2 text-sm">
              <option value="normal">{t("plans.changeType.normal")}</option>
              <option value="emergency">{t("plans.changeType.emergency")}</option></select></label>
          <label className="block text-sm"><span className="text-muted-foreground">{t("plans.form.justification")}</span>
            <input value={justification} onChange={(e) => setJustification(e.target.value)} className="mt-1 w-full border border-border bg-background rounded-lg px-3 py-2 text-sm" /></label>
          {create.error && <div role="alert" className="text-sm text-red-500">{(create.error as Error).message}</div>}
        </div>
        <div className="px-6 py-4 border-t border-border flex justify-end gap-2">
          <button type="button" onClick={close} className="px-4 py-2 text-sm rounded-lg border border-border text-muted-foreground">{t("common.cancel")}</button>
          <button type="button" onClick={submit} disabled={!canSubmit} className="px-4 py-2 text-sm font-medium rounded-lg bg-primary text-primary-foreground disabled:opacity-50">{t("plans.form.submit")}</button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
