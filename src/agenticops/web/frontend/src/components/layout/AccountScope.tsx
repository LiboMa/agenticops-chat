import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useAccounts } from "@/hooks/useAccounts";
import { useAuth } from "@/hooks/useAuth";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { useLocale } from "@/i18n/LocaleContext";
import { adoptAccountParam, scopeKey, scopeMode, validScope, type ScopeMode } from "@/lib/accountScope";
import { SPLIT_MEDIA } from "@/lib/caseQueue";

interface AccountScopeValue {
  accountId: number | null;          // null = All accounts
  setAccountId: (id: number | null) => void;
  mode: ScopeMode;
  accountName: string | null;
}

const Ctx = createContext<AccountScopeValue>({ accountId: null, setAccountId: () => {}, mode: "notApplied", accountName: null });

const read = (key: string): string | null => {
  try { return localStorage.getItem(key); } catch { return null; }
};

/** The top bar's account scope (lib/accountScope): per user in localStorage, checked against the account list. */
export function AccountScopeProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const key = scopeKey(user?.user_id);
  const accounts = useAccounts();
  const location = useLocation();
  const navigate = useNavigate();
  const wide = useMediaQuery(SPLIT_MEDIA);
  const mode = scopeMode(location.pathname, wide);
  const [stored, setStored] = useState<number | null>(() => validScope(read(key), undefined));

  useEffect(() => { setStored(validScope(read(key), undefined)); }, [key]);  // another user signed in

  const setAccountId = (id: number | null) => {
    setStored(id);
    try {
      if (id == null) localStorage.removeItem(key);
      else localStorage.setItem(key, String(id));
    } catch { /* private mode: the scope lasts this tab */ }
  };

  // An old link's own account filter sets the scope once and leaves the URL; the notice rides on that entry
  useEffect(() => {
    if (mode !== "active") return;
    const adopted = adoptAccountParam(location.search);
    if (!adopted) return;
    if (adopted.accountId != null) setAccountId(adopted.accountId);
    navigate({ pathname: location.pathname, search: adopted.search, hash: location.hash },
             { replace: true, state: { ...(location.state as object | null), scopeNotice: adopted.accountId != null } });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.search, mode]);

  const accountId = validScope(stored, accounts.data);
  const accountName = accountId == null ? null : accounts.data?.find((a) => a.id === accountId)?.name ?? null;
  return <Ctx.Provider value={{ accountId, setAccountId, mode, accountName }}>{children}</Ctx.Provider>;
}

export const useAccountScope = () => useContext(Ctx);

/** The scope's account for a list query: undefined (All) unless the page follows the scope. */
export function useScopedAccountId(): number | undefined {
  const { accountId, mode } = useAccountScope();
  return mode === "active" && accountId != null ? accountId : undefined;
}

export function AccountScopeSelect({ className = "" }: { className?: string }) {
  const { t } = useLocale();
  const accounts = useAccounts();
  const { accountId, setAccountId, mode } = useAccountScope();
  const why = mode === "notApplied" ? t("scope.notApplied") : mode === "locked" ? t("scope.locked") : undefined;
  return (
    <select aria-label={t("scope.label")} title={why} disabled={mode !== "active"}
            value={accountId == null ? "" : String(accountId)}
            onChange={(e) => setAccountId(e.target.value ? Number(e.target.value) : null)}
            className={`max-w-[170px] truncate rounded-[5px] border border-border bg-card px-2 py-1.5 text-xs text-foreground disabled:cursor-not-allowed disabled:opacity-50 ${className}`}>
      <option value="">{t("scope.all")}</option>
      {(accounts.data ?? []).map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
    </select>
  );
}

/** "Account scope set from the link" — for the one navigation that adopted it, over the page. */
export function ScopeNotice() {
  const { t } = useLocale();
  const location = useLocation();
  const { accountName } = useAccountScope();
  const [dismissed, setDismissed] = useState<string | null>(null);
  const carried = Boolean((location.state as { scopeNotice?: boolean } | null)?.scopeNotice);
  if (!carried || dismissed === location.key) return null;
  return (
    <div role="status" className="fixed left-1/2 top-[calc(var(--topbar-h)+12px)] z-40 flex w-[min(560px,calc(100vw-30px))] -translate-x-1/2 items-start justify-between gap-3 rounded-md border border-primary/30 bg-card px-3 py-2 text-sm text-foreground shadow-lg">
      <span>{t("scope.adopted").replace("{name}", accountName ?? "—")}</span>
      <button type="button" onClick={() => setDismissed(location.key)} className="text-xs underline">{t("home.dismiss")}</button>
    </div>
  );
}
