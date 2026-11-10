import { useEffect, useRef, useState } from "react";
import { useLocale } from "@/i18n/LocaleContext";
import { ApiError } from "@/api/client";
import type { UserRow } from "@/api/types";
import { useBootstrap } from "@/hooks/useBootstrap";
import { useCreateUser, useDeleteUser, useResetPassword, useUpdateUser, useUsers } from "@/hooks/useUsers";
import { QueryState } from "@/components/ui/QueryState";
import { StatusText } from "@/components/ui/StatusText";
import { useConfirm } from "@/components/ui/ConfirmDialog";
import { DeleteUserDialog, PasswordOnceDialog, RoleDialog } from "@/components/users/UserDialogs";
import { IssueKeyFlow, UserKeysDialog } from "@/components/users/UserKeysDialog";
import { IconButton } from "@/components/ui/IconButton";
import { KeyPlusIcon } from "@/components/apikeys/KeyPlusIcon";
import { Ban, RectangleEllipsis, Trash2, UserCheck, UserCog } from "lucide-react";
import { formatShortDate } from "@/lib/formatDate";
import { closeFocusTarget } from "@/lib/focusReturn";
import {
  fillRefusal, filterUsers, keysLabel, lastActiveAdminId, roleKey, rowActions, type RoleFilter, type RowAction, type StatusFilter,
} from "@/lib/users";

/** User management (MVP-2.8.0 S2 rework, owner 2026-11-09): admins see every web account and create one (the
 *  password shown once), change its role, disable / enable it and reset its password. The server is the boundary
 *  (/api/users — services/user_admin); this page only words what it allows and refuses. Admins only (App.tsx). */
export default function Users() {
  const { t } = useLocale();
  const boot = useBootstrap();
  const meId = boot.data?.user?.id ?? null;
  const users = useUsers();
  const create = useCreateUser();
  const update = useUpdateUser();
  const reset = useResetPassword();
  const del = useDeleteUser();
  const { confirm, dialog } = useConfirm();
  const [q, setQ] = useState("");
  const [role, setRole] = useState<RoleFilter>("all");
  const [status, setStatus] = useState<StatusFilter>("all");
  const [editing, setEditing] = useState<UserRow | "new" | null>(null);
  const [shown, setShown] = useState<{ email: string; password: string; kind: "created" | "reset" } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [keysOf, setKeysOf] = useState<UserRow | null>(null);
  const [keyFlow, setKeyFlow] = useState<UserRow | null>(null);
  const [deleting, setDeleting] = useState<UserRow | null>(null);
  // a delete closes in two renders: first the dialog learns its opener's row is gone (focus goes to «新建用户»), then
  // it closes — Radix hands focus back while the row is still on the page (T11 E2E: focus fell to <body>)
  const [deleted, setDeleted] = useState(false);
  useEffect(() => {
    if (deleted) { setDeleting(null); setDeleted(false); }
  }, [deleted]);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  // a deleted user's row is gone: focus comes back to «＋ 新建用户»
  const newUserButton = useRef<HTMLButtonElement | null>(null);
  // the button that started a create / reset flow: the one-time password dialog opens after another dialog or a
  // confirm closed, so it hands focus back here explicitly (S2 rework E2E: it fell to <body>)
  const flowOpener = useRef<HTMLElement | null>(null);

  const say = (e: unknown) => {
    const code = e instanceof ApiError ? e.code : undefined;
    const key = code ? `users.error.${code}` : "";
    const worded = key ? t(key) : key;
    return worded && worded !== key ? fillRefusal(worded, e instanceof ApiError ? e.data : undefined)
      : t("users.error.generic").replace("{detail}", e instanceof Error ? e.message : String(e));
  };

  const act = async (u: UserRow, a: RowAction) => {
    setError(null);
    if (a === "role") { setEditing(u); return; }
    if (a === "newKey") { setKeyFlow(u); return; }
    if (a === "delete") { setDeleteError(null); del.reset(); setDeleting(u); return; }
    if (a === "enable") { update.mutate({ id: u.id, is_active: true }, { onError: (e) => setError(say(e)) }); return; }
    if (a === "disable") {
      if (!(await confirm(t("users.confirm.disable").replace("{email}", u.email),
                          { variant: "destructive", confirmText: t("users.confirm.disableOk") }))) return;
      update.mutate({ id: u.id, is_active: false }, { onError: (e) => setError(say(e)) });
      return;
    }
    const own = u.id === meId;
    if (!(await confirm(own ? t("users.confirm.resetSelf") : t("users.confirm.reset").replace("{email}", u.email),
                        { confirmText: t("users.confirm.resetOk") }))) return;
    reset.mutate(u.id, {
      onSuccess: (r) => setShown({ email: u.email, password: r.password, kind: "reset" }),
      onError: (e) => setError(say(e)),
    });
  };

  // one row of icon buttons (MVP-2.8.0, owner): the credentials, a divider, then the account; each says what it does
  // — and to whom — on hover / focus and to a screen reader
  const ICONS: Record<RowAction, JSX.Element> = {
    reset: <RectangleEllipsis className="h-4 w-4" aria-hidden="true" />, newKey: <KeyPlusIcon />,
    role: <UserCog className="h-4 w-4" aria-hidden="true" />, disable: <Ban className="h-4 w-4" aria-hidden="true" />,
    enable: <UserCheck className="h-4 w-4" aria-hidden="true" />, delete: <Trash2 className="h-4 w-4" aria-hidden="true" />,
  };
  const iconButton = (u: UserRow, a: RowAction) => (
    <IconButton key={a} label={t(`users.icon.${a}`).replace("{who}", u.name || u.email)} icon={ICONS[a]}
                tone={a === "disable" || a === "delete" ? "danger" : "default"}
                onClick={(e) => { flowOpener.current = e.currentTarget; void act(u, a); }} />
  );
  const actionRow = (u: UserRow, rows: UserRow[]) => {
    const { credential, account } = rowActions(u, meId, { lastActiveAdmin: lastActiveAdminId(rows) === u.id });
    return (
      <div className="flex flex-wrap items-center justify-end gap-1.5">
        {credential.map((a) => iconButton(u, a))}
        {credential.length > 0 && account.length > 0 && <span aria-hidden="true" className="mx-1 h-6 w-px bg-border" />}
        {account.map((a) => iconButton(u, a))}
      </div>
    );
  };
  const lastLogin = (u: UserRow) => (u.last_login_at ? formatShortDate(u.last_login_at) : t("users.neverSignedIn"));
  const who = (u: UserRow) => (
    <div className="min-w-0">
      <p className="font-medium text-foreground [overflow-wrap:anywhere]">
        {u.name || u.email}
        {u.id === meId && <span className="ml-1.5 rounded border border-primary/40 px-1 text-[10px] text-primary">{t("users.you")}</span>}
      </p>
      {u.name && <p className="text-xs text-muted-foreground [overflow-wrap:anywhere]">{u.email}</p>}
    </div>
  );
  // «API 密钥» (MVP-2.8.0): «N 个有效 ▸» or «无»; opens the user's keys (issue, update, delete)
  const keysButton = (u: UserRow) => (
    <button type="button" onClick={() => setKeysOf(u)} aria-label={t("users.keys.open").replace("{who}", u.name || u.email)}
            className="min-h-[32px] rounded-md border border-border px-2.5 text-xs text-foreground hover:bg-accent">
      {keysLabel(u.active_api_keys ?? 0, t)}
    </button>
  );
  const state = (u: UserRow) => (
    <StatusText tone={u.is_active ? "ok" : "neutral"}>{t(u.is_active ? "users.status.active" : "users.status.disabled")}</StatusText>
  );

  return (
    <div className="mx-auto max-w-5xl space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-2xl font-semibold text-foreground">{t("users.title")}</h1>
          <p className="mt-1 text-sm text-muted-foreground">{t("users.intro")}</p>
        </div>
        <button ref={newUserButton} type="button" onClick={(e) => { flowOpener.current = e.currentTarget; setError(null); setEditing("new"); }}
                className="min-h-[40px] rounded-lg bg-primary px-4 text-sm font-medium text-primary-foreground hover:bg-primary-hover">
          ＋ {t("users.new")}
        </button>
      </div>

      {boot.data && !boot.data.auth_enabled && (
        <p role="status" className="rounded-md border border-status-warn/40 bg-status-warn/5 px-3 py-2 text-sm text-status-warn">{t("users.authOff")}</p>
      )}
      {error && editing === null && <p role="alert" className="rounded-md border border-status-danger/40 bg-status-danger/5 px-3 py-2 text-sm text-status-danger">{error}</p>}

      <div className="flex flex-wrap gap-2">
        <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder={t("users.search")} aria-label={t("users.search")}
               className="min-w-[180px] flex-1 rounded-lg border border-border bg-card px-3 py-2 text-[16px] sm:text-sm" />
        <select value={role} onChange={(e) => setRole(e.target.value as RoleFilter)} aria-label={t("users.filter.role")}
                className="rounded-lg border border-border bg-card px-3 py-2 text-[16px] sm:text-sm">
          <option value="all">{t("users.filter.allRoles")}</option>
          {(["admin", "writer", "viewer"] as const).map((r) => <option key={r} value={r}>{t(`users.role.${r}`)}</option>)}
        </select>
        <select value={status} onChange={(e) => setStatus(e.target.value as StatusFilter)} aria-label={t("users.filter.status")}
                className="rounded-lg border border-border bg-card px-3 py-2 text-[16px] sm:text-sm">
          <option value="all">{t("users.filter.allStatus")}</option>
          <option value="active">{t("users.status.active")}</option>
          <option value="disabled">{t("users.status.disabled")}</option>
        </select>
      </div>

      <QueryState query={users} isEmpty={(rows) => rows.length === 0} emptyText={t("users.empty")} onRetry={() => void users.refetch()}>
        {(rows) => {
          const list = filterUsers(rows, { q, role, status });
          if (list.length === 0) return <p className="rounded-lg border border-dashed border-border px-4 py-8 text-center text-sm text-muted-foreground">{t("users.emptyFiltered")}</p>;
          return (
            <>
              {/* ≥ 768 px a table, below one card per user */}
              <div className="hidden overflow-hidden rounded-lg border border-border bg-card md:block">
                <table className="w-full text-sm">
                  <thead className="bg-canvas text-left text-xs text-muted-foreground">
                    <tr>
                      <th className="px-4 py-2 font-medium">{t("users.col.user")}</th>
                      <th className="px-4 py-2 font-medium">{t("users.col.role")}</th>
                      <th className="px-4 py-2 font-medium">{t("users.col.status")}</th>
                      <th className="px-4 py-2 font-medium">{t("users.col.lastLogin")}</th>
                      <th className="px-4 py-2 font-medium">{t("users.col.keys")}</th>
                      <th className="px-4 py-2"><span className="sr-only">{t("users.col.actions")}</span></th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    {list.map((u) => (
                      <tr key={u.id}>
                        <td className="px-4 py-3">{who(u)}</td>
                        <td className="px-4 py-3"><span className="rounded border border-border px-1.5 py-0.5 text-xs">{t(roleKey(u))}</span></td>
                        <td className="px-4 py-3">{state(u)}</td>
                        <td className="px-4 py-3 text-xs text-muted-foreground">{lastLogin(u)}</td>
                        <td className="px-4 py-3">{keysButton(u)}</td>
                        <td className="px-4 py-3">{actionRow(u, rows)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <ul className="space-y-2 md:hidden">
                {list.map((u) => (
                  <li key={u.id} className="space-y-2 rounded-lg border border-border bg-card p-3 text-sm">
                    <div className="flex items-start justify-between gap-2">{who(u)}{state(u)}</div>
                    <p className="text-xs text-muted-foreground">{t(roleKey(u))} · {t("users.col.lastLogin")} {lastLogin(u)}</p>
                    <div className="flex flex-wrap items-center justify-between gap-2">{keysButton(u)}{actionRow(u, rows)}</div>
                  </li>
                ))}
              </ul>
              <p className="text-xs text-muted-foreground">{t("users.count").replace("{n}", String(rows.length))} · {t("users.selfNote")}</p>
            </>
          );
        }}
      </QueryState>

      {editing !== null && (
        <RoleDialog user={editing === "new" ? null : editing} busy={create.isPending || update.isPending} error={error}
                    onClose={() => { setEditing(null); setError(null); }}
                    onSubmit={(v) => {
                      setError(null);
                      if (editing === "new") {
                        create.mutate(v, {
                          onSuccess: (r) => { setEditing(null); setShown({ email: r.user.email, password: r.password, kind: "created" }); },
                          onError: (e) => setError(say(e)),
                        });
                      } else {
                        update.mutate({ id: editing.id, role: v.role, settings_view: v.settings_view }, {
                          onSuccess: () => setEditing(null),
                          onError: (e) => setError(say(e)),
                        });
                      }
                    }} />
      )}
      {/* closing forgets the password: the dialog's state and the mutations' cached results (S2 rework review) */}
      {shown && <PasswordOnceDialog {...shown} returnTo={flowOpener.current}
                                    onClose={() => { setShown(null); create.reset(); reset.reset(); }} />}
      {keysOf && <UserKeysDialog user={keysOf} onClose={() => setKeysOf(null)} />}
      {keyFlow && <IssueKeyFlow user={keyFlow} returnTo={flowOpener.current} onClose={() => setKeyFlow(null)} />}
      {deleting && (
        <DeleteUserDialog user={deleting} busy={del.isPending || deleted} error={deleteError}
                          returnTo={closeFocusTarget(flowOpener.current, newUserButton.current, deleted)}
                          onClose={() => { setDeleting(null); setDeleteError(null); }}
                          onConfirm={() => del.mutate(deleting.id, {
                            onSuccess: () => setDeleted(true),
                            onError: (e) => setDeleteError(say(e)),
                          })} />
      )}
      {dialog}
    </div>
  );
}
