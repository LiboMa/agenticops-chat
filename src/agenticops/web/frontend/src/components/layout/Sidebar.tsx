import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import * as Dialog from "@radix-ui/react-dialog";
import { usePersistedState } from "@/hooks/usePersistedState";
import { useStats } from "@/hooks/useStats";
import { useBootstrap, useCanManageUsers, useCanViewSettings } from "@/hooks/useBootstrap";
import { navItemVisible } from "@/lib/permissions";
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

/** The blue/white sidebar: daily work, the collapsible tools (the group holding the current page opens by itself,
 *  not saved; a group the user opens or closes is saved to their preferences), and administration at the foot. */
export function Sidebar({ rail = false }: { rail?: boolean }) {
  const { t } = useLocale();
  const { pathname } = useLocation();
  // 2026-11-07: on Chat the sidebar is a 56px icon rail; «expand» opens the full sidebar over the page
  const [railOpen, setRailOpen] = useState(false);
  useEffect(() => { setRailOpen(false); }, [pathname]);
  useEffect(() => {
    if (!railOpen) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setRailOpen(false); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [railOpen]);
  const boot = useBootstrap();
  const can = { settings: useCanViewSettings(), users: useCanManageUsers() };
  const stats = useStats();
  const hasOpenIssues = (stats.data?.open_anomalies ?? 0) > 0;

  const [storedOrder, setStoredOrder] = usePersistedState<NavOrder>(ORDER_V2, initialOrder());
  const order = useMemo(() => normalizeOrder(storedOrder), [storedOrder]);
  const [drag, setDrag] = useState<{ group: GroupId; id: string } | null>(null);
  const [over, setOver] = useState<string | null>(null);

  const saved = boot.data?.preferences.nav_groups_open ?? [];
  const current = entryForPath(pathname);
  // The group holding the page opens when you arrive in it; after that the user's click wins (even inside it)
  const [override, setOverride] = useState<Partial<Record<CollapsibleGroup, boolean>>>({});
  const currentGroup = current?.group;
  useEffect(() => {
    if (currentGroup && currentGroup !== "daily") {
      setOverride((o) => {
        const next = { ...o };
        delete next[currentGroup as CollapsibleGroup];
        return next;
      });
    }
  }, [currentGroup]);
  const isOpen = (g: CollapsibleGroup) => override[g] ?? (saved.includes(g) || currentGroup === g);
  const toggle = (g: CollapsibleGroup) => {
    const open = !isOpen(g);
    setOverride((o) => ({ ...o, [g]: open }));
    const next = open ? [...new Set([...saved, g])] : saved.filter((x) => x !== g);
    if (next.length !== saved.length) void savePreferences({ nav_groups_open: next });  // only a real change is saved
  };

  if (rail && !railOpen) {
    return (
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-[56px] flex-col items-center border-r border-border bg-card pb-3 pt-4 min-[801px]:flex">
        <Link to="/app/chat" className="mb-4 flex h-9 w-9 items-center justify-center" aria-label="AgenticOps">
          <img src={`${import.meta.env.BASE_URL}logo-icon.svg`} alt="" className="h-6 w-6" />
        </Link>
        <nav aria-label={t("nav.menu")} className="flex min-h-0 flex-1 flex-col items-center gap-1 overflow-y-auto">
          {NAV_GROUPS.map((g, gi) => (
            <div key={g.id} className={`flex flex-col items-center gap-1 ${gi > 0 ? "mt-1 border-t border-border pt-2" : ""}`}>
              {order[g.id].map((id) => g.items.find((i) => i.id === id)!).filter(Boolean)
                .filter((i) => navItemVisible(i.id, can)).map((item) => {
                  const active = current?.entry.id === item.id;
                  return (
                    <Link key={item.id} to={item.to} title={t(item.labelKey)} aria-label={t(item.labelKey)}
                          aria-current={active ? "page" : undefined}
                          className={`relative flex h-10 w-10 items-center justify-center rounded-lg transition-colors ${
                            active ? "bg-selected text-primary" : "text-foreground/70 hover:bg-accent hover:text-foreground"}`}>
                      <SvgIcon d={ICON_PATHS[item.icon]} className="h-[18px] w-[18px]" />
                      {item.badge && hasOpenIssues && (
                        <span className="absolute right-1.5 top-1.5 h-2 w-2 rounded-full bg-red-500" aria-hidden="true" />
                      )}
                    </Link>
                  );
                })}
            </div>
          ))}
        </nav>
        <button type="button" onClick={() => setRailOpen(true)} title={t("nav.expand")} aria-label={t("nav.expand")}
                className="mt-2 flex h-10 w-10 items-center justify-center rounded-lg text-muted-foreground hover:bg-accent hover:text-foreground">
          <svg className="h-[18px] w-[18px]" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden>
            <rect x="3" y="3.5" width="14" height="13" rx="2" /><path d="M8 3.5v13M11 8.5l2 1.5-2 1.5" />
          </svg>
        </button>
      </aside>
    );
  }

  return (
    <>
    {rail && <div className="fixed inset-0 z-30 bg-black/20" onClick={() => setRailOpen(false)} aria-hidden="true" />}
    <aside className={rail
      ? "fixed inset-y-0 left-0 z-40 flex w-[200px] flex-col border-r border-border bg-card px-3 pb-3 pt-5 shadow-xl animate-[slideInRight_0.2s_ease-out]"
      : "fixed inset-y-0 left-0 z-30 hidden w-[200px] flex-col border-r border-border bg-card px-3 pb-3 pt-5 min-[801px]:flex max-[1100px]:w-[166px] max-[1100px]:px-2"}>
      <Link to="/app/chat" className="mb-5 flex items-center gap-2.5 px-2 text-[18px] font-bold tracking-tight text-primary max-[1100px]:text-[15px]">
        <img src={`${import.meta.env.BASE_URL}logo-icon.svg`} alt="" className="h-6 w-6 shrink-0" />
        <span className="truncate">AgenticOps</span>
      </Link>

      {/* a flex column, so the bottom group (administration) sits at the foot — after everything when the list scrolls */}
      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">
        {NAV_GROUPS.map((g) => {
          const collapsible = g.collapsible;
          const open = !collapsible || isOpen(g.id as CollapsibleGroup);
          const items = order[g.id].map((id) => g.items.find((i) => i.id === id)!).filter(Boolean)
            .filter((i) => navItemVisible(i.id, can));
          if (items.length === 0) return null;   // a group with nothing this person may open is not shown
          return (
            <section key={g.id} className={g.bottom ? "mt-auto border-t border-border pt-3"
              : collapsible ? "border-t border-border py-3" : "mb-5"}>
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
                      {/* a plain Link: the active entry is lib/navGroups' (detail pages, Signals), and so is aria-current */}
                      <Link
                        to={item.to}
                        className={`relative my-0.5 flex min-h-[39px] items-center gap-2.5 rounded-[5px] px-[11px] py-2 text-[13px] transition-colors max-[1100px]:gap-2 max-[1100px]:px-2 max-[1100px]:text-xs ${
                          current?.entry.id === item.id ? "bg-selected font-semibold text-primary" : "text-foreground/75 hover:bg-accent hover:text-foreground"
                        }`}
                        aria-current={current?.entry.id === item.id ? "page" : undefined}
                      >
                        <SvgIcon d={ICON_PATHS[item.icon]} className="h-[17px] w-[17px]" />
                        <span className="truncate">{t(item.labelKey)}</span>
                        {item.badge && hasOpenIssues && (
                          <>
                            <span className="ml-auto h-2 w-2 shrink-0 rounded-full bg-red-500" aria-hidden="true" />
                            <span className="sr-only">{t("nav.openIssues")}</span>
                          </>
                        )}
                      </Link>
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
    </>
  );
}

const HOME_CHOICES: { value: Home; labelKey: string }[] = [
  { value: "resume", labelKey: "home.resume" },
  { value: "chat", labelKey: "nav.chat" },
  { value: "issues", labelKey: "nav.issues" },
  { value: "reports", labelKey: "nav.reports" },
];

export function HomePrefsButton({ className = "" }: { className?: string }) {
  const { t } = useLocale();
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}
              className={`w-full rounded-[5px] px-2.5 py-2 text-left text-[11px] text-foreground/75 hover:bg-selected ${className}`}>
        {t("home.prefsTitle")}
      </button>
      <HomePrefsDialog open={open} onOpenChange={setOpen} />
    </>
  );
}

/** 首页与语言 / Home & language: which page /app opens. Language itself is switched from the top bar. */
export function HomePrefsDialog({ open, onOpenChange: setOpen }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const { t } = useLocale();
  const boot = useBootstrap();
  const [choice, setChoice] = useState<Home>("resume");
  const [saving, setSaving] = useState(false);

  // Start from the saved home when the dialog OPENS — not on every cache write while it is open (the
  // throttled last-route save rewrites the cache and would undo the user's pick)
  const savedHome = useRef<Home>("resume");
  savedHome.current = boot.data?.preferences.home ?? "resume";
  useEffect(() => {
    if (open) setChoice(savedHome.current);
  }, [open]);

  const save = async () => {
    setSaving(true);
    await savePreferences({ home: choice });
    setSaving(false);
    setOpen(false);
  };

  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Portal>
        {/* centred by the overlay, not by a translate: the slideInRight keyframe owns `transform` */}
        <Dialog.Overlay className="fixed inset-0 z-50 grid place-items-center overflow-y-auto bg-black/30 px-[15px]">
        <Dialog.Content className="w-[min(460px,100%)] rounded-lg border border-border bg-card p-6 shadow-xl animate-[slideInRight_0.2s_ease-out]">
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
        </Dialog.Overlay>
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
  const can = { settings: useCanViewSettings(), users: useCanManageUsers() };
  return (
    <select
      aria-label={t("nav.menu")}
      value={current && pathname === current.to ? current.to : ""}
      onChange={(e) => { if (e.target.value) navigate(e.target.value); }}
      className="min-w-[110px] max-w-[150px] rounded-[5px] border border-border bg-card px-2 py-1.5 text-xs min-[801px]:hidden"
    >
      <option value="" disabled>{current ? t(current.labelKey) : t("nav.menu")}</option>
      {NAV_GROUPS.map((g) => {
        const items = g.items.filter((i) => navItemVisible(i.id, can));
        return items.length === 0 ? null : (   // an empty optgroup is skipped, as in the sidebar
          <optgroup key={g.id} label={t(g.labelKey)}>
            {items.map((i) => <option key={i.id} value={i.to}>{t(i.labelKey)}</option>)}
          </optgroup>
        );
      })}
    </select>
  );
}
