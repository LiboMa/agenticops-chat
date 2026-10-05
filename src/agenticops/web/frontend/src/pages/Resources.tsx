import { useNavigate, useSearchParams } from "react-router-dom";
import { useLocale } from "@/i18n/LocaleContext";
import { ResourcesView } from "@/pages/IssuesAndPlans";

/** Resources' own sidebar entry (spec §3); `?type=` still preselects the type filter. */
export default function Resources() {
  const { t } = useLocale();
  const navigate = useNavigate();
  const [sp] = useSearchParams();
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold text-foreground">{t("resources.title")}</h1>
      <ResourcesView navigate={navigate} t={t} initialType={sp.get("type") || ""} />
    </div>
  );
}
