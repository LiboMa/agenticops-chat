import { useEffect, useMemo, useState } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import * as Dialog from "@radix-ui/react-dialog";
import { usePersistedState } from "@/hooks/usePersistedState";
import { useStats } from "@/hooks/useStats";
import { useBootstrap } from "@/hooks/useBootstrap";
import { useLocale } from "@/i18n/LocaleContext";
import {
  NAV_GROUPS, entryForPath, migrateNavOrder, moveWithinGroup, normalizeOrder,
  type CollapsibleGroup, type GroupId, type NavOrder,
} from "@/lib/navGroups";
import { savePreferences } from "@/lib/preferences";
import type { Home } from "@/lib/home";
import { ICON_PATHS, SvgIcon } from "./navIcons";

const ORDER_V2 = "aiops-nav-order-v2";

/** The stored order, migrated once from the v1 one-list sidebar (`aiops-nav-order`) the first time. */
function initialOrder(): NavOrder {
  try {
    const v2 = localStorage.getItem(ORDER_V2);
    if (v2) return normalizeOrder(JSON.parse(v2));
    const v1 = localStorage.getItem("aiops-nav-order");
    return migrateNavOrder(v1 ? JSON.parse(v1) : null);
  } catch {
    return migrateNavOrder(null);
  }
}

/** The blue/white sidebar: daily work, then two collapsible groups; the group holding the current page opens
 *  by itself (not saved), a group the user opens or closes is saved to their preferences. */
export function Sidebar() {
  const { t } = useLocale();
  const { pathname } = useLocation();
  const boot = useBootstrap();
  const stats = useStats();
  const hasOpenIssues = (stats.data?.open_anomalies ?? 0) > 0;

  const [storedOrder, setStoredOrder] = usePersistedState<NavOrder>(ORDER_V2, initialOrder());
  const order = useMemo(() => normalizeOrder(storedOrder), [storedOrder]);
  const [drag, setDrag] = useState<{ group: GroupId; id: string } | null>(null);
  const [over, setOver] = useState<string | null>(null);

  const saved = boot.data?.preferences.nav_groups_open ?? [];
  const current = entryForPath(pathname);
  const isOpen = (g: CollapsibleGroup) => saved.includes(g) || current?.group === g;
  const toggle = (g: CollapsibleGroup) => {
    const next = isOpen(g) ? saved.filter((x) => x !== g) : [...saved, g];
    void savePreferences({ nav_groups_open: next });
  };

  return (
    <aside className="fixed inset-y-0 left-0 z-30 hidden w-[200px] flex-col border-r border-border bg-card px-3 pb-3 pt-5 min-[801px]:flex max-[1100px]:w-[166px] max-[1100px]:px-2">
      <NavLink to="/app/chat" className="mb-5 flex items-center gap-2.5 px-2 text-[18px] font-bold tracking-tight text-primary max-[1100px]:text-[15px]">
        <img src={`${import.meta.env.BASE_URL}logo-icon.svg`} alt="" className="h-6 w-6 shrink-0" />
        <span className="truncate">AgenticOps</span>
      </NavLink>

      <div className="min-h-0 flex-1 overflow-y-auto">
        {NAV_GROUPS.map((g) => {
          const collapsible = g.id !== "daily";
          const open = !collapsible || isOpen(g.id as CollapsibleGroup);
          const items = order[g.id].map((id) => g.items.find((i) => i.id === id)!).filter(Boolean);
          return (
            <section key={g.id} className={collapsible ? "border-t border-border py-3" : "mb-5"}>
              {collapsible ? (
                <button type="button" onClick={() => toggle(g.id as CollapsibleGroup)} aria-expanded={open}
                        className="flex w-full items-center justify-between rounded px-[11px] py-1 text-[11px] text-muted-foreground hover:text-foreground">
                  {t(g.labelKey)}
                  <span aria-hidden="true" className={`text-base leading-none transition-transform ${open ? "rotate-90" : ""}`}>›</span>
                </button>
              ) : (
                <p className="mb-2 px-[11px] text-[10px] text-muted-foreground">{t(g.labelKey)}</p>
              )}
              {open && (
                <nav aria-label={t(g.labelKey)} className={collapsible ? "pt-1" : ""}>
                  {items.map((item) => (
                    <div
                      key={item.id}
                      draggable
                      onDragStart={() => setDrag({ group: g.id, id: item.id })}
                      onDragOver={(e) => { if (drag?.group === g.id) { e.preventDefault(); setOver(item.id); } }}
                      onDragLeave={() => setOver((cur) => (cur === item.id ? null : cur))}
                      onDrop={() => {
                        if (drag?.group === g.id) setStoredOrder(moveWithinGroup(order, g.id, drag.id, item.id));
                        setDrag(null); setOver(null);
                      }}
                      onDragEnd={() => { setDrag(null); setOver(null); }}
                      className={over === item.id && drag?.id !== item.id ? "border-t-2 border-primary" : "border-t-2 border-transparent"}
                    >
                      <NavLink
                        to={item.to}
                        className={() => {
                          const active = current?.entry.id === item.id;
                          return `relative my-0.5 flex min-h-[39px] items-center gap-2.5 rounded-[5px] px-[11px] py-2 text-[13px] transition-colors max-[1100px]:gap-2 max-[1100px]:px-2 max-[1100px]:text-xs ${
                            active ? "bg-selected font-semibold text-primary" : "text-foreground/75 hover:bg-accent hover:text-foreground"
                          }`;
                        }}
                        aria-current={current?.entry.id === item.id ? "page" : undefined}
                      >
                        <SvgIcon d={ICON_PATHS[item.icon]} className="h-[17px] w-[17px]" />
                        <span className="truncate">{t(item.labelKey)}</span>
                        {item.badge && hasOpenIssues && (
                          <span className="ml-auto h-2 w-2 shrink-0 rounded-full bg-red-500" aria-label={t("nav.openIssues")} />
                        )}
                      </NavLink>
                    </div>
                  ))}
                </nav>
              )}
            </section>
          );
        })}
      </div>

      <div className="mt-3 border-t border-border pt-2">
        <HomePrefsButton />
        {boot.data?.version && <p className="px-2.5 pt-2 text-[10px] text-muted-foreground">v{boot.data.version}</p>}
      </div>
    </aside>
  );
}

const HOME_CHOICES: { value: Home; labelKey: string }[] = [
  { value: "resume", labelKey: "home.resume" },
  { value: "chat", labelKey: "nav.chat" },
  { value: "issues", labelKey: "nav.issues" },
  { value: "reports", labelKey: "nav.reports" },
];

/** 首页与语言 / Home & language: which page /app opens. Language itself is switched from the top bar. */
export function HomePrefsButton({ className = "" }: { className?: string }) {
  const { t } = useLocale();
  const boot = useBootstrap();
  const [open, setOpen] = useState(false);
  const [choice, setChoice] = useState<Home>("resume");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (open) setChoice(boot.data?.preferences.home ?? "resume");
  }, [open, boot.data]);

  const save = async () => {
    setSaving(true);
    await savePreferences({ home: choice });
    setSaving(false);
    setOpen(false);
  };

  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Trigger asChild>
        <button type="button" className={`w-full rounded-[5px] px-2.5 py-2 text-left text-[11px] text-foreground/75 hover:bg-selected ${className}`}>
          {t("home.prefsTitle")}
        </button>
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/30" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-50 w-[min(460px,calc(100vw-30px))] -translate-x-1/2 -translate-y-1/2 rounded-lg border border-border bg-card p-6 shadow-xl animate-[slideInRight_0.2s_ease-out]">
          <Dialog.Title className="text-lg font-semibold text-foreground">{t("home.prefsTitle")}</Dialog.Title>
          <Dialog.Description className="mt-2 text-sm text-muted-foreground">{t("home.prefsHint")}</Dialog.Description>
          <label className="mt-5 block text-sm font-medium text-foreground" htmlFor="home-choice">{t("home.defaultEntry")}</label>
          <select id="home-choice" value={choice} onChange={(e) => setChoice(e.target.value as Home)}
                  className="mt-1.5 w-full rounded-md border border-border px-3 py-2 text-sm">
            {HOME_CHOICES.map((c) => <option key={c.value} value={c.value}>{t(c.labelKey)}</option>)}
          </select>
          <div className="mt-6 flex justify-end gap-2">
            <Dialog.Close asChild>
              <button type="button" className="rounded-md border border-border px-3 py-2 text-sm">{t("common.cancel")}</button>
            </Dialog.Close>
            <button type="button" onClick={save} disabled={saving}
                    className="rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground hover:bg-primary-hover disabled:opacity-60">
              {t("home.save")}
            </button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

/** ≤800px: the sidebar is hidden and this native menu navigates (one optgroup per group). A page that is no
 *  entry (a 404) shows the placeholder; a detail page shows the entry it belongs to. */
export function MobileNav() {
  const { t } = useLocale();
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const current = entryForPath(pathname)?.entry;
  return (
    <select
      aria-label={t("nav.menu")}
      value={current?.to ?? ""}
      onChange={(e) => { if (e.target.value) navigate(e.target.value); }}
      className="min-w-[110px] max-w-[150px] rounded-[5px] border border-border bg-card px-2 py-1.5 text-xs min-[801px]:hidden"
    >
      <option value="" disabled>{t("nav.menu")}</option>
      {NAV_GROUPS.map((g) => (
        <optgroup key={g.id} label={t(g.labelKey)}>
          {g.items.map((i) => <option key={i.id} value={i.to}>{t(i.labelKey)}</option>)}
        </optgroup>
      ))}
    </select>
  );
}
