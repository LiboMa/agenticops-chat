import { useRef, useState } from "react";
import { useLocale } from "@/i18n/LocaleContext";
import { ApiError } from "@/api/client";
import type { UserRow } from "@/api/types";
import { useBootstrap } from "@/hooks/useBootstrap";
import { useCreateUser, useResetPassword, useUpdateUser, useUsers } from "@/hooks/useUsers";
import { QueryState } from "@/components/ui/QueryState";
import { StatusText } from "@/components/ui/StatusText";
import { useConfirm } from "@/components/ui/ConfirmDialog";
import { PasswordOnceDialog, RoleDialog } from "@/components/users/UserDialogs";
import { formatShortDate } from "@/lib/formatDate";
import { filterUsers, roleKey, rowActions, type RoleFilter, type RowAction, type StatusFilter } from "@/lib/users";

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
  const { confirm, dialog } = useConfirm();
  const [q, setQ] = useState("");
  const [role, setRole] = useState<RoleFilter>("all");
  const [status, setStatus] = useState<StatusFilter>("all");
  const [editing, setEditing] = useState<UserRow | "new" | null>(null);
  const [shown, setShown] = useState<{ email: string; password: string; kind: "created" | "reset" } | null>(null);
  const [error, setError] = useState<string | null>(null);
  // the button that started a create / reset flow: the one-time password dialog opens after another dialog or a
  // confirm closed, so it hands focus back here explicitly (S2 rework E2E: it fell to <body>)
  const flowOpener = useRef<HTMLElement | null>(null);

  const say = (e: unknown) => {
    const code = e instanceof ApiError ? e.code : undefined;
    const key = code ? `users.error.${code}` : "";
    const worded = key ? t(key) : key;
    return worded && worded !== key ? worded
      : t("users.error.generic").replace("{detail}", e instanceof Error ? e.message : String(e));
  };

  const act = async (u: UserRow, a: RowAction) => {
    setError(null);
    if (a === "role") { setEditing(u); return; }
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

  const actionButton = (u: UserRow, a: RowAction) => (
    <button key={a} type="button" onClick={(e) => { flowOpener.current = e.currentTarget; void act(u, a); }}
            className={`min-h-[32px] rounded-md border px-2.5 text-xs ${a === "disable"
              ? "border-status-danger/40 text-status-danger hover:bg-status-danger/5" : "border-border text-foreground hover:bg-accent"}`}>
      {t(`users.action.${a}`)}
    </button>
  );
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
        <button type="button" onClick={(e) => { flowOpener.current = e.currentTarget; setError(null); setEditing("new"); }}
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
                className="rounded-lg border border-border bg-card px-3 py-2 text-sm">
          <option value="all">{t("users.filter.allRoles")}</option>
          {(["admin", "writer", "viewer"] as const).map((r) => <option key={r} value={r}>{t(`users.role.${r}`)}</option>)}
        </select>
        <select value={status} onChange={(e) => setStatus(e.target.value as StatusFilter)} aria-label={t("users.filter.status")}
                className="rounded-lg border border-border bg-card px-3 py-2 text-sm">
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
                        <td className="px-4 py-3"><div className="flex flex-wrap justify-end gap-1.5">{rowActions(u, meId).map((a) => actionButton(u, a))}</div></td>
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
                    <div className="flex flex-wrap gap-1.5">{rowActions(u, meId).map((a) => actionButton(u, a))}</div>
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
      {shown && <PasswordOnceDialog {...shown} onClose={() => setShown(null)} returnTo={flowOpener.current} />}
      {dialog}
    </div>
  );
}
