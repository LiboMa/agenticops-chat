import { useNavigate } from "react-router-dom";
import * as Dialog from "@radix-ui/react-dialog";
import { useLocale } from "@/i18n/LocaleContext";
import { useAttention } from "@/hooks/useAttention";
import { useAccountScope } from "@/components/layout/AccountScope";
import { Spinner } from "@/components/ui/Spinner";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import { reasonKey, safeRoute } from "@/lib/attention";

/** Needs your attention: one row per work item, a click goes to where it is decided — nothing is approved here (the
 *  approval's acknowledgement is about the version the page shows). Radix: ESC and focus handled. */
export function AttentionDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const { t } = useLocale();
  const navigate = useNavigate();
  const scope = useAccountScope();
  const q = useAttention(scope.accountId);
  const items = q.data?.items ?? [];
  const go = (route: string) => {
    const to = safeRoute(route);
    if (!to) return;
    onOpenChange(false);
    navigate(to);
  };
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        {/* centred by the overlay, not by a translate: the slideInRight keyframe owns `transform` */}
        <Dialog.Overlay className="fixed inset-0 z-50 grid items-start justify-items-center overflow-y-auto bg-black/30 px-[15px] pt-[12vh]">
        <Dialog.Content className="max-h-[76vh] w-[min(560px,100%)] overflow-y-auto rounded-lg border border-border bg-card p-5 shadow-xl animate-[slideInRight_0.2s_ease-out]">
          <div className="mb-3 flex items-center justify-between">
            <Dialog.Title className="text-lg font-semibold text-foreground">{t("attention.title")}</Dialog.Title>
            <Dialog.Close aria-label={t("common.close")} className="rounded px-2 text-lg text-muted-foreground hover:text-foreground">×</Dialog.Close>
          </div>
          <Dialog.Description className="sr-only">{t("attention.hint")}</Dialog.Description>
          {scope.accountId != null && (
            <p className="mb-2 rounded bg-selected px-2.5 py-1.5 text-xs text-primary">
              {t("attention.scopedTo").replace("{name}", scope.accountName ?? `#${scope.accountId}`)}
            </p>
          )}
          {q.isLoading ? <Spinner label={t("common.loading")} />
            : q.error ? <ErrorBanner message={q.error.message} onRetry={() => q.refetch()} actionLabel={t("common.retry")} />
            : items.length === 0 ? <p className="py-6 text-center text-sm text-muted-foreground">{t("attention.empty")}</p>
            : (
              <ul className="divide-y divide-border">
                {items.map((i) => (
                  <li key={i.id}>
                    <button type="button" onClick={() => go(i.route)} className="w-full px-1 py-3 text-left hover:bg-selected">
                      <strong className="block text-sm font-medium text-foreground">{i.title}</strong>
                      <small className="text-xs text-muted-foreground"><span className="font-mono">{i.ref}</span> · {t(reasonKey(i))}</small>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          {q.data && q.data.total > items.length && (
            <p className="mt-3 text-xs text-muted-foreground">{t("attention.more").replace("{shown}", String(items.length)).replace("{total}", String(q.data.total))}</p>
          )}
        </Dialog.Content>
        </Dialog.Overlay>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
