import { useRef, useState } from "react";
import { useLocale } from "@/i18n/LocaleContext";
import { ApiError } from "@/api/client";
import type { ApiKeyRow, UserRow } from "@/api/types";
import { useCreateUserKey, useRevokeUserKey, useRotateUserKey, useUserKeys } from "@/hooks/useUsers";
import { ModalFrame } from "@/components/ui/ModalFrame";
import { QueryState } from "@/components/ui/QueryState";
import { useConfirm } from "@/components/ui/ConfirmDialog";
import { IconButton } from "@/components/ui/IconButton";
import { KeyList } from "@/components/apikeys/KeyList";
import { KeyPlusIcon } from "@/components/apikeys/KeyPlusIcon";
import { CreateKeyDialog, KeyOnceDialog } from "@/components/apikeys/ApiKeyDialogs";
import { rotateDefaults, writeAllowedForRole } from "@/lib/apiKeys";

/** An admin manages one user's API keys (MVP-2.8.0, owner 2026-11-10: «用户可以像修改密码一样，生成Key、更新Key，以及删除
 *  key»): issue one (never above their role), update one (a new key under the same name, the old one dead at once) or
 *  delete one. A new key is shown to the admin once, like a reset password; a listed key never shows in full. */

function useSayKeyError() {
  const { t } = useLocale();
  return (e: unknown) => {
    const code = e instanceof ApiError ? e.code : undefined;
    const key = code ? `apiKeys.error.${code}` : "";
    const worded = key ? t(key) : key;
    return worded && worded !== key ? worded
      : t("apiKeys.error.generic").replace("{detail}", e instanceof Error ? e.message : String(e));
  };
}

/** Issue or update a key for `user`: the key dialog, then the new key shown once. Focus goes back to `returnTo`
 *  (an element that is still there when the flow ends — the row's or the list's «生成密钥»). */
export function IssueKeyFlow({ user, rotateKey = null, returnTo, onClose }: {
  user: UserRow;
  rotateKey?: ApiKeyRow | null;
  returnTo: HTMLElement | null;
  onClose: () => void;
}) {
  const { t } = useLocale();
  const say = useSayKeyError();
  const create = useCreateUserKey();
  const rotate = useRotateUserKey();
  const [shown, setShown] = useState<{ name: string; key: string } | null>(null);
  const who = user.name || user.email;
  const canWrite = writeAllowedForRole(user.role);
  const busy = rotateKey ? rotate : create;
  // closing forgets the key: the flow's state and both mutations' cached results
  const close = () => { create.reset(); rotate.reset(); onClose(); };

  if (shown) {
    return <KeyOnceDialog name={shown.name} apiKey={shown.key} returnTo={returnTo} onClose={close}
                          title={t("users.keys.onceTitle").replace("{who}", who).replace("{name}", shown.name)} />;
  }
  return (
    <CreateKeyDialog canWrite={canWrite} busy={busy.isPending} error={busy.isError ? say(busy.error) : null}
                     title={rotateKey ? t("users.keys.rotateTitle").replace("{who}", who).replace("{name}", rotateKey.name)
                       : t("users.keys.createTitle").replace("{who}", who)}
                     rotate={rotateKey ? { name: rotateKey.name } : undefined}
                     initial={rotateKey ? rotateDefaults(rotateKey, canWrite) : undefined}
                     blockedHint={t("users.keys.viewerHint").replace("{who}", who)}
                     onClose={close}
                     onSubmit={(v) => {
                       const done = { onSuccess: (r: ApiKeyRow & { key: string }) => setShown({ name: r.name, key: r.key }) };
                       if (rotateKey) rotate.mutate({ userId: user.id, keyId: rotateKey.id, permissions: v.permissions, expires_days: v.expires_days }, done);
                       else create.mutate({ userId: user.id, ...v }, done);
                     }} />
  );
}

export function UserKeysDialog({ user, onClose }: { user: UserRow; onClose: () => void }) {
  const { t } = useLocale();
  const say = useSayKeyError();
  const keys = useUserKeys(user.id);
  const revoke = useRevokeUserKey();
  const { confirm, dialog } = useConfirm();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<number | null>(null);
  const [flow, setFlow] = useState<{ rotate: ApiKeyRow | null } | null>(null);
  // a deleted or updated key's row is gone (no longer listed / a new id): focus comes back to «生成密钥» here
  const issueButton = useRef<HTMLButtonElement | null>(null);
  const who = user.name || user.email;

  const onRevoke = async (k: ApiKeyRow) => {
    setError(null);
    if (!(await confirm(t("users.keys.confirm").replace("{who}", who).replace("{name}", k.name),
                        { variant: "destructive", confirmText: t("apiKeys.confirm.revokeOk") }))) return;
    setBusy(k.id);
    revoke.mutate({ userId: user.id, keyId: k.id }, {
      onSuccess: () => requestAnimationFrame(() => issueButton.current?.focus()),
      onError: (e) => setError(say(e)),
      onSettled: () => setBusy(null),
    });
  };

  return (
    <ModalFrame title={t("users.keys.title").replace("{who}", who)} onClose={onClose} width="w-[min(560px,100%)]">
      <div className="mt-2 flex justify-end">
        <IconButton ref={issueButton} label={t("users.keys.createTitle").replace("{who}", who)} icon={<KeyPlusIcon />}
                    onClick={() => { setError(null); setFlow({ rotate: null }); }} />
      </div>
      <div className="mt-2 max-h-[60vh] space-y-3 overflow-y-auto">
        {error && <p role="alert" className="rounded-md border border-status-danger/40 bg-status-danger/5 px-3 py-2 text-sm text-status-danger">{error}</p>}
        <QueryState query={keys} isEmpty={(rows) => rows.length === 0} emptyText={t("users.keys.empty")} onRetry={() => void keys.refetch()}>
          {(rows) => <KeyList rows={rows} cards showCreated={false} busyId={busy} onRevoke={(k) => void onRevoke(k)}
                              onRotate={(k) => { setError(null); setFlow({ rotate: k }); }} />}
        </QueryState>
      </div>
      <p className="mt-3 text-xs text-muted-foreground">{t("users.keys.note")}</p>
      <div className="mt-4 flex justify-end border-t border-border pt-3">
        <button type="button" onClick={onClose} className="min-h-[40px] rounded-lg border border-border px-4 text-sm hover:bg-accent">{t("common.close")}</button>
      </div>
      {flow && <IssueKeyFlow user={user} rotateKey={flow.rotate} returnTo={issueButton.current} onClose={() => setFlow(null)} />}
      {dialog}
    </ModalFrame>
  );
}
