import { useLocale } from "@/i18n/LocaleContext";
interface EmptyStateProps {
  message?: string;
  icon?: string;
}

export function EmptyState({
  message,
}: EmptyStateProps) {
  const { t } = useLocale();
  return (
    <div className="flex flex-col items-center justify-center py-16 text-muted-foreground/60">
      <p className="text-sm">{message ?? t("common.noDataAvailable")}</p>
    </div>
  );
}
