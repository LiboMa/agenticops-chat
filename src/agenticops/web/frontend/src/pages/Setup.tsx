import { Link, useNavigate } from "react-router-dom";
import { useLocale } from "@/i18n/LocaleContext";
import { getAuthToken } from "@/api/client";
import { useBootstrap } from "@/hooks/useBootstrap";
import { useReadiness, useVerifyModel } from "@/hooks/useSetup";
import { StatusText } from "@/components/ui/StatusText";
import { Spinner } from "@/components/ui/Spinner";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import { formatFullDate } from "@/lib/formatDate";
import { SETUP_ITEMS, itemViews, patrolDraft, type SetupItemId, type SetupItemView } from "@/lib/setup";
import { canViewSettings } from "@/lib/permissions";
import { FRESH_CHAT } from "@/lib/contextRef";
import { draftKey, loadDraft, saveDraft } from "@/lib/chatDrafts";
import { currentUserId } from "@/lib/home";
import type { Readiness, ReadinessCheckView } from "@/api/types";

type T = (key: string) => string;
const fill = (text: string, vars: Record<string, string | number>) =>
  Object.entries(vars).reduce((s, [k, v]) => s.replace(`{${k}}`, String(v)), text);
const onOff = (t: T, on: boolean) => t(on ? "setup.on" : "setup.off");
const card = "rounded-lg border border-border bg-card p-5";
const button = "inline-flex min-h-[44px] items-center justify-center rounded-md px-4 text-sm font-medium sm:min-h-9";
const primary = `${button} bg-primary text-primary-foreground hover:bg-primary-hover disabled:opacity-60`;
const quiet = `${button} border border-border bg-background text-foreground hover:bg-accent disabled:opacity-60`;

function CheckLine({ check, t }: { check: ReadinessCheckView | null; t: T }) {
  if (!check) return <span className="text-status-warn">{t("setup.check.none")}</span>;
  return (
    <span className={check.ok ? "text-status-ok" : "text-status-danger"}>
      {fill(t(check.ok ? "setup.check.ok" : "setup.check.failed"), { time: formatFullDate(check.checked_at), by: check.checked_by.replace(/^user:/, "") })}
      {!check.ok && check.detail && <span className="font-mono [overflow-wrap:anywhere]"> · {check.detail}</span>}
      {check.ok && check.detail === "cut_at_limit" && <span className="text-muted-foreground"> · {t("setup.check.cut")}</span>}
    </span>
  );
}

/** What an item says once someone is signed in: the facts of THIS installation. */
function Facts({ id, r, t }: { id: SetupItemId; r: Readiness; t: T }) {
  if (id === "accounts") {
    return (
      <>
        <p>{fill(t("setup.accounts.count"), { n: r.accounts.enabled, regions: r.accounts.regions })}</p>
        <ul className="mt-1 space-y-0.5">
          {r.accounts.items.map((a) => (
            <li key={a.id} className="[overflow-wrap:anywhere]"><span className="font-medium text-foreground">{a.name}</span> · <CheckLine check={a.check} t={t} /></li>
          ))}
        </ul>
      </>
    );
  }
  if (id === "model") {
    return (
      <>
        <p className="[overflow-wrap:anywhere]">{t("setup.model.id")}: <span className="font-mono text-foreground">{r.model.model_id}</span></p>
        {r.model.provider && r.model.provider !== "bedrock"
          ? <p className="[overflow-wrap:anywhere]">{fill(t("setup.model.provider"), { provider: r.model.provider, endpoint: r.model.endpoint ?? "" })}</p>
          : <p>{fill(t("setup.model.region"), { region: r.model.region ?? "" })}</p>}
        <p><CheckLine check={r.model.check} t={t} /></p>
      </>
    );
  }
  if (id === "execution") {
    const e = r.execution;
    return (
      <>
        <ul className="grid gap-x-6 gap-y-0.5 sm:grid-cols-2">
          <li>{t("setup.exec.executor")}: <b className="text-foreground">{onOff(t, e.executor_enabled)}</b></li>
          <li>{t("setup.exec.autoFix")}: <b className="text-foreground">{onOff(t, e.auto_fix_enabled)}</b></li>
          <li>{t("setup.exec.autoApprove")}: <b className="text-foreground">{onOff(t, e.auto_approve_l0_l1)}</b></li>
          <li>{t("setup.exec.changeAuto")}: <b className="text-foreground">{onOff(t, e.change_auto_approve_standard)}</b></li>
          <li className="sm:col-span-2">{t("setup.exec.rbac")}: <b className="text-foreground">{t(e.rbac_enforce ? "setup.exec.rbacOn" : "setup.exec.rbacShadow")}</b></li>
        </ul>
        <p className="mt-1">{t(e.read_only ? "setup.exec.youReadOnly" : e.you_can_approve ? "setup.exec.youApprove" : "setup.exec.youCannot")}</p>
      </>
    );
  }
  return <p>{fill(t("setup.notify.count"), { n: r.notifications.channels })}</p>;
}

/** The setup overview (MVP-2.9.0 N23 — the 2.8.0 spec's S6), open before and after signing in. Signed out: what the
 *  four things are and what to prepare — no data of any workspace. Signed in: how far THIS installation is — where
 *  «configured» and «verified» are different words — and the next step of each. It never runs a check by itself. */
export default function Setup() {
  const { t, locale, setLocale } = useLocale();
  const navigate = useNavigate();
  const signedIn = !!getAuthToken();
  const boot = useBootstrap();
  const readiness = useReadiness(signedIn);
  const verify = useVerifyModel();
  // who this is decides what each item offers: nothing is offered before that is known (no link that then goes)
  const views: SetupItemView[] | null = readiness.data && boot.data
    ? itemViews(readiness.data, { settings: canViewSettings(boot.data) }) : null;

  const tryPatrol = () => {            // a draft in a new conversation — never sent from here
    if (!boot.data) return;
    const key = draftKey(boot.data.deployment_id, currentUserId(), "new");
    saveDraft(localStorage, key, patrolDraft(loadDraft(localStorage, key), t("setup.patrol.prompt")));
    navigate("/app/chat", { state: FRESH_CHAT });
  };

  return (
    <div className="min-h-screen bg-canvas px-4 py-6 sm:px-8">
      <div className="mx-auto max-w-5xl">
        <header className="mb-6 flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <img src={`${import.meta.env.BASE_URL}logo-icon.svg`} alt="" className="h-8 w-8" />
            <div>
              <h1 className="text-xl font-semibold text-foreground">{t("setup.title")}</h1>
              <p className="text-sm text-muted-foreground">{t(signedIn ? "setup.subtitle.in" : "setup.subtitle.out")}</p>
            </div>
          </div>
          <div role="group" aria-label="Language / 语言" className="flex rounded-[5px] border border-border bg-card p-0.5">
            {(["zh", "en"] as const).map((l) => (
              <button key={l} type="button" onClick={() => setLocale(l)} aria-pressed={locale === l}
                      className={`rounded-[3px] px-2 py-1 text-[11px] ${locale === l ? "bg-selected font-semibold text-primary" : "text-muted-foreground"}`}>
                {l === "zh" ? "中文" : "English"}
              </button>
            ))}
          </div>
        </header>

        {signedIn && readiness.isError && !readiness.data && (
          <div className="mb-4"><ErrorBanner message={t("setup.failed")} onRetry={() => void readiness.refetch()} actionLabel={t("common.retry")} /></div>
        )}
        {signedIn && !views && !readiness.isError && <div className="mb-4"><Spinner label={t("common.loading")} /></div>}

        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_18rem]">
          <ol className="space-y-4">
            {SETUP_ITEMS.map((id, i) => {
              const view = views?.find((v) => v.id === id) ?? null;
              return (
                <li key={id} className={card}>
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <h2 className="text-base font-semibold text-foreground">{i + 1}. {t(`setup.item.${id}.title`)}</h2>
                    {view && <StatusText tone={view.tone} className="whitespace-normal text-sm font-medium">{t(view.stateKey)}</StatusText>}
                  </div>
                  <p className="mt-1 text-sm text-muted-foreground"><span className="font-medium text-foreground">{t("setup.why")}</span> {t(`setup.item.${id}.why`)}</p>
                  {view && readiness.data ? (
                    <>
                      <div className="mt-2 text-sm text-muted-foreground">
                        <div className="font-medium text-foreground">{t("setup.now")}</div>
                        <Facts id={id} r={readiness.data} t={t} />
                      </div>
                      <div className="mt-3 flex flex-wrap items-center gap-2">
                        {/* the one filled button of an item is the step it still owes: verifying the model when
                            this person can, else the place in Settings */}
                        {view.canVerify && (
                          <button type="button" disabled={verify.isPending} onClick={() => verify.mutate()} className={view.owed ? primary : quiet}>
                            {verify.isPending ? t("setup.verify.busy") : t("setup.verify.button")}
                          </button>
                        )}
                        {view.next
                          ? <Link to={view.next.to} className={view.owed && !view.canVerify ? primary : quiet}>{t(`setup.item.${id}.next`)}</Link>
                          : <span className="text-sm text-muted-foreground">{t("setup.askAdmin")}</span>}
                        {id === "model" && !view.canVerify && view.next && <span className="text-sm text-muted-foreground">{t("setup.verify.adminOnly")}</span>}
                      </div>
                      {id === "model" && verify.isError && <p role="alert" className="mt-2 text-sm text-status-danger">{t("setup.verify.failed")}</p>}
                      {id === "model" && view.canVerify && <p className="mt-2 text-xs text-muted-foreground">{t("setup.verify.note")}</p>}
                    </>
                  ) : (
                    <p className="mt-2 text-sm text-muted-foreground"><span className="font-medium text-foreground">{t("setup.prepare")}</span> {t(`setup.item.${id}.prepare`)}</p>
                  )}
                </li>
              );
            })}
          </ol>

          <aside className="space-y-4">
            {signedIn && (
              <section className={card}>
                <h2 className="text-sm font-semibold text-foreground">{t("setup.patrol.title")}</h2>
                <p className="mt-1 text-sm text-muted-foreground">{t("setup.patrol.body")}</p>
                <button type="button" onClick={tryPatrol} disabled={!boot.data} className={`${quiet} mt-3 w-full`}>
                  {t("setup.patrol.button")}
                </button>
              </section>
            )}
            <section className={card}>
              {(["permissions", "again", "done"] as const).map((q) => (
                <details key={q} className="border-b border-border/60 py-2 last:border-0">
                  <summary className="cursor-pointer text-sm font-medium text-foreground">{t(`setup.faq.${q}.q`)}</summary>
                  <p className="mt-1 text-sm text-muted-foreground">{t(`setup.faq.${q}.a`)}</p>
                </details>
              ))}
            </section>
          </aside>
        </div>

        <footer className="mt-6 flex flex-wrap items-center gap-2">
          {!signedIn && <Link to="/app/login" className={primary}>{t("setup.backToLogin")}</Link>}
          {signedIn && (
            <>
              <button type="button" onClick={() => void readiness.refetch()} disabled={readiness.isFetching} className={quiet}>{t("setup.recheck")}</button>
              <button type="button" onClick={() => navigate("/app", { state: { fromSetup: true } })} className={primary}>{t("setup.enter")}</button>
              {readiness.data && <span className="text-xs text-muted-foreground">{fill(t("setup.readAt"), { time: formatFullDate(readiness.data.generated_at) })} · {t("setup.recheckNote")}</span>}
            </>
          )}
        </footer>
      </div>
    </div>
  );
}
