import { useLocale } from "@/i18n/LocaleContext";
import { AuditTab } from "@/components/plans/AuditTab";

export default function Audit() {
  const { t } = useLocale();
  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold text-foreground">{t("nav.audit")}</h1>
      <AuditTab />
    </div>
  );
}
