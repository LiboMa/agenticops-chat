import { useState } from "react";
import { useLocale } from "@/i18n/LocaleContext";
import { ApiError } from "@/api/client";
import type { ApiKeyRow, UserRow } from "@/api/types";
import { useRevokeUserKey, useUserKeys } from "@/hooks/useUsers";
import { ModalFrame } from "@/components/ui/ModalFrame";
import { QueryState } from "@/components/ui/QueryState";
import { useConfirm } from "@/components/ui/ConfirmDialog";
import { KeyList } from "@/components/apikeys/KeyList";

/** An admin's view of one user's API keys (MVP-2.8.0, owner 2026-11-10): every key with its state, Revoke on the
 *  active ones after a confirm. An admin may issue a key for someone (never above their role) and sees that key
 *  once, like a reset password; a listed key never shows in full. */
export function UserKeysDialog({ user, onClose }: { user: UserRow; onClose: () => void }) {
  const { t } = useLocale();
  const keys = useUserKeys(user.id);
  const revoke = useRevokeUserKey();
  const { confirm, dialog } = useConfirm();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<number | null>(null);
  const who = user.name || user.email;

  const say = (e: unknown) => {
    const code = e instanceof ApiError ? e.code : undefined;
    const key = code ? `apiKeys.error.${code}` : "";
    const worded = key ? t(key) : key;
    return worded && worded !== key ? worded
      : t("apiKeys.error.generic").replace("{detail}", e instanceof Error ? e.message : String(e));
  };
  const onRevoke = async (k: ApiKeyRow) => {
    setError(null);
    if (!(await confirm(t("users.keys.confirm").replace("{who}", who).replace("{name}", k.name),
                        { variant: "destructive", confirmText: t("apiKeys.confirm.revokeOk") }))) return;
    setBusy(k.id);
    revoke.mutate({ userId: user.id, keyId: k.id }, { onError: (e) => setError(say(e)), onSettled: () => setBusy(null) });
  };

  return (
    <ModalFrame title={t("users.keys.title").replace("{who}", who)} onClose={onClose} width="w-[min(560px,100%)]">
      <div className="mt-3 max-h-[60vh] space-y-3 overflow-y-auto">
        {error && <p role="alert" className="rounded-md border border-status-danger/40 bg-status-danger/5 px-3 py-2 text-sm text-status-danger">{error}</p>}
        <QueryState query={keys} isEmpty={(rows) => rows.length === 0} emptyText={t("users.keys.empty")} onRetry={() => void keys.refetch()}>
          {(rows) => <KeyList rows={rows} cards showCreated={false} busyId={busy} onRevoke={(k) => void onRevoke(k)} />}
        </QueryState>
      </div>
      <p className="mt-3 text-xs text-muted-foreground">{t("users.keys.note")}</p>
      <div className="mt-4 flex justify-end border-t border-border pt-3">
        <button type="button" onClick={onClose} className="min-h-[40px] rounded-lg border border-border px-4 text-sm hover:bg-accent">{t("common.close")}</button>
      </div>
      {dialog}
    </ModalFrame>
  );
}
