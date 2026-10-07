import { useLocale } from "@/i18n/LocaleContext";

const VERIFICATION_CHIP: Record<string, string> = {
  passed: "bg-green-500/20 text-green-600 dark:text-green-400",
  failed: "bg-red-500/20 text-red-600 dark:text-red-400",
  pending_acceptance: "bg-amber-500/20 text-amber-600 dark:text-amber-400",
};

/** A run's verification status (passed / failed / pending acceptance); "—" before it has one. */
export function VerificationChip({ status }: { status: string | null }) {
  const { t } = useLocale();
  if (!status) return <span className="text-xs text-muted-foreground">—</span>;
  return (
    <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${VERIFICATION_CHIP[status] ?? "bg-secondary text-muted-foreground"}`}>
      {t(`verification.${status}`)}
    </span>
  );
}
