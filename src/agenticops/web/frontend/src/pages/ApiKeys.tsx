import { useRef, useState } from "react";
import { useLocale } from "@/i18n/LocaleContext";
import { ApiError } from "@/api/client";
import type { ApiKeyRow } from "@/api/types";
import { useBootstrap } from "@/hooks/useBootstrap";
import { useCreateApiKey, useMyApiKeys, useRevokeApiKey, useRotateApiKey } from "@/hooks/useApiKeys";
import { QueryState } from "@/components/ui/QueryState";
import { useConfirm } from "@/components/ui/ConfirmDialog";
import { CreateKeyDialog, KeyOnceDialog } from "@/components/apikeys/ApiKeyDialogs";
import { KeyList } from "@/components/apikeys/KeyList";
import { canChooseWrite, rotateDefaults } from "@/lib/apiKeys";

/** «My API keys» (MVP-2.8.0, owner 2026-11-10; from the avatar menu, every signed-in person). A key calls
 *  AgenticOps as its owner for a third-party app or a coding agent — never more than the owner's role, never a human
 *  decision (approve / run / accept), never managing keys. The server is the boundary (services/api_keys). */
export default function ApiKeys() {
  const { t } = useLocale();
  const boot = useBootstrap();
  const keys = useMyApiKeys();
  const create = useCreateApiKey();
  const revoke = useRevokeApiKey();
  const rotate = useRotateApiKey();
  const { confirm, dialog } = useConfirm();
  const [creating, setCreating] = useState(false);
  const [rotating, setRotating] = useState<ApiKeyRow | null>(null);
  const [shown, setShown] = useState<{ name: string; key: string; rotated: boolean } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [revoking, setRevoking] = useState<number | null>(null);
  // «＋ New API key»: the key-once dialog opens after the create / update dialog closed, and an updated or deleted
  // key's row is gone (a new id, or no longer listed) — so focus comes back here
  const newButton = useRef<HTMLButtonElement | null>(null);

  const say = (e: unknown) => {
    const code = e instanceof ApiError ? e.code : undefined;
    const key = code ? `apiKeys.error.${code}` : "";
    const worded = key ? t(key) : key;
    return worded && worded !== key ? worded
      : t("apiKeys.error.generic").replace("{detail}", e instanceof Error ? e.message : String(e));
  };

  const onRevoke = async (k: ApiKeyRow) => {
    setError(null);
    if (!(await confirm(t("apiKeys.confirm.revoke").replace("{name}", k.name),
                        { variant: "destructive", confirmText: t("apiKeys.confirm.revokeOk") }))) return;
    setRevoking(k.id);
    revoke.mutate(k.id, {
      // the row is gone once it is deleted: focus goes to the page's own button, not <body>
      onSuccess: () => newButton.current?.focus(),
      onError: (e) => setError(say(e)),
      onSettled: () => setRevoking(null),
    });
  };

  return (
    <div className="mx-auto max-w-5xl space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 max-w-2xl">
          <h1 className="text-2xl font-semibold text-foreground">{t("apiKeys.title")}</h1>
          <p className="mt-1 text-sm text-muted-foreground">{t("apiKeys.intro")}</p>
        </div>
        <button ref={newButton} type="button" onClick={() => { setError(null); create.reset(); setCreating(true); }}
                className="min-h-[40px] rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground hover:bg-primary-hover">
          ＋ {t("apiKeys.new")}
        </button>
      </div>

      {boot.data && !boot.data.user && (
        <p role="status" className="rounded-md border border-border bg-canvas px-3 py-2 text-sm text-muted-foreground">{t("apiKeys.signInFirst")}</p>
      )}
      {boot.data && !boot.data.auth_enabled && (
        <p role="status" className="rounded-md border border-status-warn/40 bg-status-warn/5 px-3 py-2 text-sm text-status-warn">{t("apiKeys.authOff")}</p>
      )}
      {error && <p role="alert" className="rounded-md border border-status-danger/40 bg-status-danger/5 px-3 py-2 text-sm text-status-danger">{error}</p>}

      <QueryState query={keys} isEmpty={(rows) => rows.length === 0} emptyText={t("apiKeys.empty")} onRetry={() => void keys.refetch()}>
        {(rows) => <KeyList rows={rows} busyId={revoking} onRevoke={(k) => void onRevoke(k)}
                            onRotate={(k) => { setError(null); rotate.reset(); setRotating(k); }} />}
      </QueryState>
      <p className="text-xs text-muted-foreground">{t("apiKeys.revokeNote")}</p>

      {creating && (
        <CreateKeyDialog canWrite={canChooseWrite(boot.data)} busy={create.isPending}
                         error={create.isError ? say(create.error) : null}
                         onClose={() => { setCreating(false); create.reset(); }}
                         onSubmit={(v) => create.mutate(v, {
                           onSuccess: (r) => { setCreating(false); setShown({ name: r.name, key: r.key, rotated: false }); },
                         })} />
      )}
      {rotating && (
        <CreateKeyDialog canWrite={canChooseWrite(boot.data)} busy={rotate.isPending}
                         error={rotate.isError ? say(rotate.error) : null}
                         title={t("apiKeys.dialog.rotateTitle").replace("{name}", rotating.name)}
                         rotate={{ name: rotating.name }} initial={rotateDefaults(rotating, canChooseWrite(boot.data))}
                         onClose={() => { setRotating(null); rotate.reset(); }}
                         onSubmit={(v) => rotate.mutate({ id: rotating.id, permissions: v.permissions, expires_days: v.expires_days }, {
                           onSuccess: (r) => { setRotating(null); setShown({ name: r.name, key: r.key, rotated: true }); },
                         })} />
      )}
      {/* closing forgets the key: the dialog's state and the mutations' cached results */}
      {shown && <KeyOnceDialog name={shown.name} apiKey={shown.key} returnTo={newButton.current}
                               title={shown.rotated ? t("apiKeys.once.rotatedTitle").replace("{name}", shown.name) : undefined}
                               onClose={() => { setShown(null); create.reset(); rotate.reset(); }} />}
      {dialog}
    </div>
  );
}
