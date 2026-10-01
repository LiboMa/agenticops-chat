import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useLocale } from "@/i18n/LocaleContext";
import { useSettings } from "@/hooks/useSettings";
import { ChangePlansTab } from "@/components/plans/ChangePlansTab";
import { NewChangeDialog } from "@/components/plans/NewChangeDialog";
import { Spinner } from "@/components/ui/Spinner";

export default function Changes() {
  const { t } = useLocale();
  const navigate = useNavigate();
  const [showNew, setShowNew] = useState(false);
  const settings = useSettings();
  // A settings error counts as off: the Changes surfaces stay hidden unless the flag is explicitly true.
  const changesOn = settings.data?.change_management_enabled === true;

  if (settings.isLoading) return <Spinner label={t("common.loading")} />;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-foreground">{t("nav.changes")}</h1>
        {changesOn && (
          <button onClick={() => setShowNew(true)}
            className="px-4 py-2 text-sm font-medium rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 transition-colors">
            + {t("plans.newChange")}
          </button>
        )}
      </div>
      {changesOn ? <ChangePlansTab /> : <p className="text-sm text-muted-foreground">{t("changes.disabled")}</p>}
      {changesOn && showNew && (
        <NewChangeDialog onClose={() => setShowNew(false)} onCreated={(id) => { setShowNew(false); navigate(`/app/changes/${id}`); }} />
      )}
    </div>
  );
}
