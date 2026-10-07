import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useLocale } from "@/i18n/LocaleContext";
import { useSettings } from "@/hooks/useSettings";
import { useBootstrap } from "@/hooks/useBootstrap";
import { FixPlansTab } from "@/components/plans/FixPlansTab";
import { ChangePlansTab } from "@/components/plans/ChangePlansTab";
import { AuditTab } from "@/components/plans/AuditTab";
import { NewChangeDialog } from "@/components/plans/NewChangeDialog";
import { auditTabVisible, hubTab, nextTab, type HubTab } from "@/lib/plans";
import { tabCounts } from "@/lib/attention";
import { useAttention } from "@/hooks/useAttention";
import { useAccountScope } from "@/components/layout/AccountScope";

/** Plans & changes (MVP-2.7.0 S3): fix plans, change requests and the audit trail, one tab each (?tab=). */
export default function PlansAndChanges() {
  const { t } = useLocale();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const boot = useBootstrap();
  const settings = useSettings();
  const [showNew, setShowNew] = useState(false);
  const attention = useAttention(useAccountScope().accountId);
  const changesOn = settings.data?.change_management_enabled === true;
  // /api/audit needs an admin when auth is on (rbac audit.read): the tab is not offered to anyone else
  const auditOn = auditTabVisible(boot.data);
  const requested = hubTab(params.get("tab"));
  const tab: HubTab = requested === "audit" && !auditOn ? "fix" : requested;
  const counts = tabCounts(attention.data?.items ?? []);
  const tabs: { id: HubTab; label: string; count?: number }[] = [
    { id: "fix", label: t("plans.tab.fix"), count: counts.fix },
    { id: "changes", label: t("plans.tab.changes"), count: counts.changes },
    ...(auditOn ? [{ id: "audit" as const, label: t("plans.tab.audit") }] : []),
  ];
  const pick = (next: HubTab) => setParams(next === "fix" ? {} : { tab: next }, { replace: true });
  return (
    <div className="mx-auto max-w-[1280px] space-y-5">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-foreground">{t("nav.plans")}</h1>
          <p className="mt-1 text-sm text-muted-foreground">{t("plans.hub.intro")}</p>
        </div>
        {tab === "changes" && changesOn && (
          <button onClick={() => setShowNew(true)} className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary-hover">
            + {t("plans.newChange")}
          </button>
        )}
      </div>
      <div role="tablist" aria-label={t("nav.plans")} className="flex gap-1 border-b border-border"
           onKeyDown={(e) => {
             const to = nextTab(tabs.map((x) => x.id), tab, e.key);
             if (!to) return;
             e.preventDefault();
             pick(to);
             document.getElementById(`plans-tab-${to}`)?.focus();
           }}>
        {tabs.map((x) => (
          <button key={x.id} id={`plans-tab-${x.id}`} role="tab" type="button" aria-selected={tab === x.id}
                  aria-controls={`plans-panel-${x.id}`} tabIndex={tab === x.id ? 0 : -1} onClick={() => pick(x.id)}
                  className={`-mb-px flex items-center gap-2 border-b-2 px-3 py-2 text-sm ${tab === x.id ? "border-primary font-semibold text-primary" : "border-transparent text-muted-foreground hover:text-foreground"}`}>
            {x.label}
            {!!x.count && <span title={t("plans.tab.pending").replace("{n}", String(x.count))} className="rounded bg-selected px-1.5 text-[11px] font-semibold text-primary">{x.count}</span>}
          </button>
        ))}
      </div>
      <div role="tabpanel" id={`plans-panel-${tab}`} aria-labelledby={`plans-tab-${tab}`}>
        {tab === "fix" && <FixPlansTab />}
        {tab === "changes" && (changesOn ? <ChangePlansTab /> : <p className="text-sm text-muted-foreground">{t("changes.disabled")}</p>)}
        {tab === "audit" && <AuditTab />}
      </div>
      {showNew && <NewChangeDialog onClose={() => setShowNew(false)} onCreated={(id) => { setShowNew(false); navigate(`/app/changes/${id}`); }} />}
    </div>
  );
}
