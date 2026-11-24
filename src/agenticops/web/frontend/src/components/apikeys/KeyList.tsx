import { useLocale } from "@/i18n/LocaleContext";
import type { ApiKeyRow } from "@/api/types";
import { StatusText } from "@/components/ui/StatusText";
import { formatShortDate, utcDayKey } from "@/lib/formatDate";
import { keyState, scopeKey, type KeyState } from "@/lib/apiKeys";
import { RotateCcwKey, Trash2 } from "lucide-react";
import { IconButton } from "@/components/ui/IconButton";

/** A list of API keys (MVP-2.8.0) — «My API keys» (a table from 768 px, cards below) and the admin's dialog in user
 *  management (`cards`: always cards). Each key (active or expired; a deleted one is no longer listed) has two icon
 *  buttons: update (a new key under the same name) and delete. The full key is never here. */

const TONE: Record<KeyState, "ok" | "warn" | "neutral"> = { active: "ok", expired: "warn", revoked: "neutral" };

export function KeyList({ rows, onRevoke, onRotate, busyId, cards = false, showCreated = true }: {
  rows: ApiKeyRow[];
  onRevoke: (row: ApiKeyRow) => void;
  /** update = a new key under the same name; no button without it */
  onRotate?: (row: ApiKeyRow) => void;
  busyId?: number | null;
  cards?: boolean;
  showCreated?: boolean;
}) {
  const { t } = useLocale();
  const now = Date.now();
  const lastUsed = (k: ApiKeyRow) => (k.last_used_at ? formatShortDate(k.last_used_at) : t("apiKeys.neverUsed"));
  const expires = (k: ApiKeyRow) => (k.expires_at ? `${utcDayKey(k.expires_at)} UTC` : t("apiKeys.expiry.never"));
  const state = (k: ApiKeyRow) => {
    const s = keyState(k, now);
    return <StatusText tone={TONE[s]}>{t(`apiKeys.state.${s}`)}</StatusText>;
  };
  const revoke = (k: ApiKeyRow) => keyState(k, now) !== "revoked" && (
    <span className="inline-flex gap-1.5">
      {onRotate && (
        <IconButton label={t("apiKeys.rotateNamed").replace("{name}", k.name)} icon={<RotateCcwKey className="h-4 w-4" aria-hidden="true" />}
                    disabled={busyId === k.id} onClick={() => onRotate(k)} />
      )}
      <IconButton label={t("apiKeys.deleteNamed").replace("{name}", k.name)} icon={<Trash2 className="h-4 w-4" aria-hidden="true" />}
                  tone="danger" disabled={busyId === k.id} onClick={() => onRevoke(k)} />
    </span>
  );
  const prefix = (k: ApiKeyRow) => <code className="font-mono text-xs text-muted-foreground">{k.key_prefix}…</code>;

  const cardList = (
    <ul className={`space-y-2 ${cards ? "" : "md:hidden"}`}>
      {rows.map((k) => (
        <li key={k.id} className="space-y-1.5 rounded-lg border border-border bg-card p-3 text-sm">
          <div className="flex items-start justify-between gap-2">
            <p className="min-w-0 font-medium text-foreground [overflow-wrap:anywhere]">{k.name}</p>
            {state(k)}
          </div>
          <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
            {prefix(k)}<span>{t(scopeKey(k.permissions))}</span>
          </p>
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 text-xs">
            {showCreated && <><dt className="text-muted-foreground">{t("apiKeys.col.created")}</dt><dd>{formatShortDate(k.created_at)}</dd></>}
            <dt className="text-muted-foreground">{t("apiKeys.col.lastUsed")}</dt><dd>{lastUsed(k)}</dd>
            <dt className="text-muted-foreground">{t("apiKeys.col.expires")}</dt><dd>{expires(k)}</dd>
          </dl>
          {revoke(k) && <div className="pt-1">{revoke(k)}</div>}
        </li>
      ))}
    </ul>
  );
  if (cards) return cardList;
  return (
    <>
      <div className="hidden overflow-x-auto rounded-lg border border-border bg-card md:block">
        <table className="w-full text-sm">
          <thead className="bg-canvas text-left text-xs text-muted-foreground">
            <tr>
              <th className="px-4 py-2 font-medium">{t("apiKeys.col.name")}</th>
              <th className="px-4 py-2 font-medium">{t("apiKeys.col.prefix")}</th>
              <th className="px-4 py-2 font-medium">{t("apiKeys.col.scope")}</th>
              {showCreated && <th className="px-4 py-2 font-medium">{t("apiKeys.col.created")}</th>}
              <th className="px-4 py-2 font-medium">{t("apiKeys.col.lastUsed")}</th>
              <th className="px-4 py-2 font-medium">{t("apiKeys.col.expires")}</th>
              <th className="px-4 py-2 font-medium">{t("apiKeys.col.state")}</th>
              <th className="px-4 py-2"><span className="sr-only">{t("apiKeys.col.actions")}</span></th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {rows.map((k) => (
              <tr key={k.id}>
                <td className="px-4 py-3 font-medium text-foreground [overflow-wrap:anywhere]">{k.name}</td>
                <td className="px-4 py-3">{prefix(k)}</td>
                <td className="px-4 py-3 text-xs">{t(scopeKey(k.permissions))}</td>
                {showCreated && <td className="px-4 py-3 text-xs text-muted-foreground">{formatShortDate(k.created_at)}</td>}
                <td className="px-4 py-3 text-xs text-muted-foreground">{lastUsed(k)}</td>
                <td className="px-4 py-3 text-xs text-muted-foreground">{expires(k)}</td>
                <td className="px-4 py-3">{state(k)}</td>
                <td className="px-4 py-3 text-right">{revoke(k)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {cardList}
    </>
  );
}
