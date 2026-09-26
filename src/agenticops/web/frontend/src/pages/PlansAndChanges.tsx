import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import * as Tabs from "@radix-ui/react-tabs";
import { useLocale } from "@/i18n/LocaleContext";
import { useSettings } from "@/hooks/useSettings";
import { resolvePlansTab } from "@/lib/plans";
import { FixPlansTab } from "@/components/plans/FixPlansTab";
import { ChangePlansTab } from "@/components/plans/ChangePlansTab";
import { AuditTab } from "@/components/plans/AuditTab";
import { NewChangeDialog } from "@/components/plans/NewChangeDialog";
import { Spinner } from "@/components/ui/Spinner";

// Verbatim from Settings.tsx so the two tab bars read identically.
const tabTriggerClass =
  "px-4 py-2 text-sm font-medium border-b-2 border-transparent data-[state=active]:border-primary data-[state=active]:text-primary text-muted-foreground hover:text-foreground transition-colors";

export default function PlansAndChanges() {
  const { t } = useLocale();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const [showNew, setShowNew] = useState(false);
  const settings = useSettings();
  // A settings error counts as off: the Changes surfaces stay hidden unless the flag is explicitly true.
  const changesOn = settings.data?.change_management_enabled === true;

  if (settings.isLoading) return <Spinner label={t("common.loading")} />;

  // The Changes tab exists only while the flag is on; an off-flag ?tab=changes shows Fix without rewriting the URL.
  const tab = resolvePlansTab(params.get("tab"), changesOn);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-foreground">{t("plans.title")}</h1>
        {changesOn && (
          <button onClick={() => setShowNew(true)}
            className="px-4 py-2 text-sm font-medium rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 transition-colors">
            + {t("plans.newChange")}
          </button>
        )}
      </div>
      <Tabs.Root value={tab} onValueChange={(v) => setParams({ tab: v })}>
        <Tabs.List className="flex border-b border-border mb-6 gap-0 overflow-x-auto">
          <Tabs.Trigger value="fix" className={tabTriggerClass}>{t("plans.tab.fix")}</Tabs.Trigger>
          {changesOn && <Tabs.Trigger value="changes" className={tabTriggerClass}>{t("plans.tab.changes")}</Tabs.Trigger>}
          <Tabs.Trigger value="audit" className={tabTriggerClass}>{t("plans.tab.audit")}</Tabs.Trigger>
        </Tabs.List>
        <Tabs.Content value="fix"><FixPlansTab /></Tabs.Content>
        {changesOn && <Tabs.Content value="changes"><ChangePlansTab /></Tabs.Content>}
        <Tabs.Content value="audit"><AuditTab /></Tabs.Content>
      </Tabs.Root>
      {changesOn && showNew && (
        <NewChangeDialog onClose={() => setShowNew(false)} onCreated={(id) => { setShowNew(false); navigate(`/app/changes/${id}`); }} />
      )}
    </div>
  );
}
