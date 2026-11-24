import { Fragment, useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useAccountScope } from "@/components/layout/AccountScope";
import { initials } from "@/components/layout/TopBar";
import { useAccounts } from "@/hooks/useAccounts";
import { useAuth } from "@/hooks/useAuth";
import { useCanManageUsers, useCanViewSettings, useReadOnly } from "@/hooks/useBootstrap";
import { useNavCounts } from "@/hooks/useNavCounts";
import { FONT_SIZES, useTheme, type FontSize } from "@/hooks/useTheme";
import { useLocale } from "@/i18n/LocaleContext";
import { scopeSelect } from "@/lib/accountScope";
import { navBadge } from "@/lib/navCounts";
import { breadcrumbFor } from "@/lib/navGroups";
import { savePreferences } from "@/lib/preferences";
import { TO_CLASSIC, setChoice } from "@/lib/shellChoice";
import { useActivity } from "../hooks/useActivity";
import { useWaitingCounts } from "../hooks/useDecideQueue";
import { useNfT } from "../i18n";
import { endsTyping, escapeStep, focusContext, keyIntent, stillTyping, toastMs, type Lens } from "../lib/keys";
import { atWork } from "../lib/live";
import { currentPage, pagesMenu } from "../lib/pages";
import { groupCounts } from "../lib/queue";
import { lensOf, shellTitle } from "../lib/shell";
import { WorldLayer } from "../world/WorldData";
import { CommandBar } from "./CommandBar";
import { Help } from "./Help";
import { PendingToast } from "./PendingToast";
import { Pulse } from "./Pulse";
import { usePendingStore } from "./usePendingStore";
import { ShellContext, type LensKeys, type ShellApi } from "./shellContext";
import "../newui.css";

const LENSES: Lens[] = ["decide", "live", "world"];
const SINGLE_KEYS = "nf-single-keys";

const readFlag = (key: string): boolean => {
  try { return localStorage.getItem(key) !== "off"; } catch { return true; }
};

/** NewUI's frame: the lens tabs, the «pages» menu, the account scope, theme, language, help, the way back to the
 *  classic interface and the account menu — and the one place that listens to the keyboard. Around a lens it is the
 *  whole page. `hosting` (round 3): the page is a classic one, drawn by components/layout/NewFrame OUTSIDE this
 *  element; the frame is then one layer over it (no <main>, no map), its single keys stand back (lib/keys `hosted`),
 *  the account select follows the page's rule and the tab's title is the page's section. `tucked`: the page's own
 *  input takes the command bar's place (chat) — the bar is out of sight until Cmd/Ctrl+K calls it. */
export function NewShell({ children, hosting = false, tucked = false }: { children: ReactNode; hosting?: boolean; tucked?: boolean }) {
  const t = useNfT();
  const { locale, setLocale, t: classicT } = useLocale();      // the classic words: a hosted page's section, the menu's entries
  const { theme, toggle, fontSize, setFontSize } = useTheme();
  const { user, logout } = useAuth();
  const readOnly = useReadOnly();
  const accounts = useAccounts();
  const { accountId, setAccountId, mode, locked } = useAccountScope();
  const canSettings = useCanViewSettings(), canUsers = useCanManageUsers();
  const nav = useNavCounts();
  const navigate = useNavigate();
  const location = useLocation();
  const lens = lensOf(location.pathname, (location.state as { from?: string } | null)?.from);
  const counts = useWaitingCounts(accountId);
  const working = atWork(useActivity(accountId).data);              // the same record «现场» lists

  const [help, setHelp] = useState(false);
  const [menu, setMenu] = useState<null | "account" | "pages">(null);
  const [singleKeys, setSingleKeys] = useState(() => readFlag(SINGLE_KEYS));
  const [notice, setNotice] = useState<string | null>(null);
  const [flags, setFlags] = useState<readonly string[]>([]);
  const lensKeys = useRef<LensKeys | null>(null);
  const command = useRef<HTMLInputElement>(null);
  const lastPlace = useRef<Partial<Record<Lens, string>>>({});
  const avatar = useRef<HTMLButtonElement>(null);
  const pagesButton = useRef<HTMLButtonElement>(null);
  const menuBox = useRef<HTMLDivElement>(null);
  const noticeTimer = useRef<number | null>(null);
  const lastFieldKey = useRef<number | null>(null);        // when a key last went into a field

  // each lens remembers where you were in it: «1» from the map goes back to the item you were reading
  useEffect(() => {
    if (lens && /^\/app\/new\/(decide|live|world)(\/|$)/.test(location.pathname)) lastPlace.current[lens] = location.pathname + location.search;
  }, [lens, location.pathname, location.search]);
  const go = useCallback((l: Lens) => navigate(lastPlace.current[l] ?? `/app/new/${l}`), [navigate]);

  // a hosted page is titled as the classic top bar titled it: by its section («not found» for an address of no section,
  // nothing yet while /app is still deciding where home is)
  const crumb = breadcrumbFor(location.pathname);
  const resolving = /^\/app\/?$/.test(location.pathname);
  const ownPage = currentPage(location.pathname) === "items" && !hosting;         // a NewUI page that is no lens
  const section = ownPage ? t("pages.items") : !hosting || resolving ? null : classicT(crumb.sectionKey ?? "notFound.title");
  useEffect(() => {
    document.title = shellTitle(location.pathname, { lens: lens ? t(`lens.${lens}`) : null, story: t("act.story"), section });
  }, [location.pathname, lens, t, section]);

  const notify = useCallback((text: string) => {
    if (noticeTimer.current) window.clearTimeout(noticeTimer.current);
    setNotice(text);
    noticeTimer.current = window.setTimeout(() => { noticeTimer.current = null; setNotice(null); }, toastMs(text));
  }, []);
  useEffect(() => () => { if (noticeTimer.current) window.clearTimeout(noticeTimer.current); }, []);

  // the one decision that is waiting out its undo window (N13): «Z» or the toast's button takes it back
  const pending = usePendingStore();
  const pendingUndo = pending.undo;
  const undo = useCallback(() => {
    const took = pendingUndo();
    if (took) notify(t("toast.undone"));
    return took;
  }, [pendingUndo, notify, t]);

  const closeMenu = useCallback((refocus: boolean) => {
    setMenu((open) => {
      if (refocus) (open === "pages" ? pagesButton : avatar).current?.focus();
      return null;
    });
  }, []);

  useEffect(() => {
    const down = (e: KeyboardEvent) => {
      const at = focusContext(document.activeElement), now = performance.now();
      // a key that goes into a field starts a moment in which keys are still typing — the field may be taken away
      // under the hands (lib/keys.stillTyping); each key swallowed that way renews it, Enter / Esc / Tab end it
      const typing = !at.inField && stillTyping(lastFieldKey.current, now);
      if (at.inField || typing) lastFieldKey.current = endsTyping(e.key) ? null : now;
      const intent = keyIntent(e, { ...at, typing, modal: help || menu !== null, singleKeys, hosted: hosting });
      if (!intent) return;
      if (intent.type === "escape") {
        const step = escapeStep({ help, menu: menu !== null, inField: at.inField, hosted: hosting });
        if (step === "help") return setHelp(false);
        if (step === "menu") return closeMenu(true);
        if (step === "none") return;                       // a hosted classic page: Escape is the page's own
        if (step === "blur") return (document.activeElement as HTMLElement).blur();
        lensKeys.current?.onEscape?.();
        return;
      }
      if (intent.type === "command") { e.preventDefault(); command.current?.focus(); return; }
      if (intent.type === "help") return setHelp(true);
      if (intent.type === "theme") return toggle();
      if (intent.type === "lens") return go(intent.lens);
      // «Z» takes the waiting decision back — before the lens sees the key: it works on every lens
      if (intent.key === "z" && !intent.repeat && undo()) { e.preventDefault(); return; }
      if (lensKeys.current?.onKey?.(intent.key, e, intent.repeat)) e.preventDefault();
    };
    const up = (e: KeyboardEvent) => lensKeys.current?.onKeyUp?.(e.key.toLowerCase(), e);
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    return () => { window.removeEventListener("keydown", down); window.removeEventListener("keyup", up); };
  }, [help, menu, singleKeys, hosting, toggle, go, closeMenu, undo]);

  // the account menu: the pointer anywhere else closes it; opening it puts the focus on its first line
  useEffect(() => {
    if (!menu) return;
    menuBox.current?.querySelector<HTMLElement>(".mi")?.focus();
    const away = (e: PointerEvent) => {
      if (!menuBox.current?.parentElement?.contains(e.target as Node)) setMenu(null);
    };
    document.addEventListener("pointerdown", away);
    return () => document.removeEventListener("pointerdown", away);
  }, [menu]);
  const menuKeys = (e: React.KeyboardEvent) => {
    const lines = [...(menuBox.current?.querySelectorAll<HTMLElement>(".mi") ?? [])].filter((el) => el.offsetParent !== null);
    const at = lines.indexOf(document.activeElement as HTMLElement);
    const to = e.key === "ArrowDown" ? at + 1 : e.key === "ArrowUp" ? at - 1 : e.key === "Home" ? 0 : e.key === "End" ? lines.length - 1 : null;
    if (to !== null && lines.length) { e.preventDefault(); lines[(to + lines.length) % lines.length].focus(); }
    if (e.key === "Tab") setMenu(null);
  };

  const pickLocale = (next: "zh" | "en") => {
    if (next === locale) return;
    setLocale(next);
    void savePreferences({ locale: next });      // the choice follows the person to their other browsers
  };
  const flipSingleKeys = () => {
    const next = !singleKeys;
    setSingleKeys(next);
    try { if (next) localStorage.removeItem(SINGLE_KEYS); else localStorage.setItem(SINGLE_KEYS, "off"); } catch { /* this tab only */ }
  };

  const all = groupCounts(counts.data)?.all;
  const countText = all !== undefined ? all.toLocaleString("en-US") : counts.isPending ? "…" : "—";
  // on a lens the scope is the person's and free; over a hosted page it is that page's rule (lib/accountScope.scopeSelect)
  const picked = scopeSelect({ lens: !hosting, mode, locked, accountId });
  const scope = (className: string) => (
    <select className={className} aria-label={t("scope.label")} value={picked.value == null ? "" : String(picked.value)}
            disabled={picked.disabled} title={picked.why ? classicT(`scope.${picked.why}`) : undefined}
            onChange={(e) => setAccountId(e.target.value ? Number(e.target.value) : null)}>
      <option value="">{t("scope.all")}</option>
      {(accounts.data ?? []).map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
    </select>
  );
  const setRootFlag = useCallback((flag: string, on: boolean) => {
    setFlags((old) => (old.includes(flag) === on ? old : on ? [...old, flag] : old.filter((f) => f !== flag)));
  }, []);
  const api = useMemo<ShellApi>(() => ({
    setLensKeys: (keys) => { lensKeys.current = keys; }, notify, singleKeys, setRootFlag, defer: pending.defer,
    pendingItem: pending.waiting?.item ?? null,
  }), [notify, singleKeys, setRootFlag, pending.defer, pending.waiting?.item]);
  const nfTheme = theme === "dark" ? "night" : "day";
  // «back to the classic interface» is a choice the browser keeps (lib/shellChoice), as «the new interface» is on the other side
  const toClassic = () => { setChoice("classic"); navigate("/app", { state: TO_CLASSIC }); };
  const nextFont = () => {
    const sizes = Object.keys(FONT_SIZES) as FontSize[];
    setFontSize(sizes[(sizes.indexOf(fontSize) + 1) % sizes.length]);
  };
  const pages = pagesMenu({ settings: canSettings, users: canUsers });
  const here = currentPage(location.pathname);                 // null on a lens

  return (
    <ShellContext.Provider value={api}>
      <div className={["nf", ...(hosting ? ["hosting"] : []), ...flags].join(" ")} data-theme={nfTheme}>
        <WorldLayer asleep={hosting}>
        <header className="top">
          <div className="tabs" role="tablist" aria-label={t("lens.label")}>
            {LENSES.map((l, i) => (
              <button key={l} type="button" role="tab" aria-selected={lens === l} onClick={() => go(l)}>
                <span className="n">{i + 1}</span>{t(`lens.${l}`)}
                {l === "decide" && <b className="cnt num">{countText}</b>}
                {l === "live" && working !== undefined && working > 0 && <b className="cnt num">{working}</b>}
              </button>
            ))}
          </div>
          {/* every page by click (round 3): the classic sidebar's own table; over a hosted page it names where you are */}
          <div className="menuwrap pageswrap">
            <button ref={pagesButton} type="button" className={`chip-btn${here ? " on" : ""}`} aria-haspopup="menu"
                    aria-expanded={menu === "pages"} onClick={() => setMenu((v) => (v === "pages" ? null : "pages"))}>
              {section && here ? section : t("shell.pages")}<span aria-hidden="true"> ▾</span>
            </button>
            {menu === "pages" && (
              <div ref={menuBox} className="menu pages" role="menu" aria-label={t("shell.pages")} onKeyDown={menuKeys}>
                {pages.map((g, k) => (
                  <Fragment key={g.id}>
                    {k > 0 && <div className="sep" />}
                    <div className="whoami">{classicT(g.labelKey)}</div>
                    {g.items.map((i) => {
                      const badge = i.own ? null : navBadge(i.id, { status: nav.status, data: nav.data }, readOnly).count;
                      return (
                        <Link key={i.id} className="mi" role="menuitem" to={i.to} state={i.state} aria-current={here === i.id ? "page" : undefined}
                              onClick={() => setMenu(null)}>
                          {i.own ? t(i.labelKey) : classicT(i.labelKey)}{badge ? <small className="num">{badge}</small> : null}
                        </Link>
                      );
                    })}
                  </Fragment>
                ))}
              </div>
            )}
          </div>
          <div className="pulsebox"><Pulse accountId={accountId} /></div>
          <div className="who">
            {scope("scope")}
            <button type="button" className="chip-btn wide" onClick={toClassic} title={t("shell.classic.hint")}>{t("shell.classic")}</button>
            <button type="button" className="chip-btn wide" onClick={toggle} aria-label={t("theme.toggle")}>{t(`theme.${nfTheme}`)}</button>
            <button type="button" className="chip-btn" onClick={() => setHelp(true)} aria-label={t("keys.open")}>?</button>
            {readOnly && <span className="ro" title={t("shell.readOnly.hint")}>{t("shell.readOnly")}</span>}
            <div className="menuwrap">
              <button ref={avatar} type="button" className="avatar" aria-label={t("shell.menu")} aria-haspopup="menu"
                      aria-expanded={menu === "account"} onClick={() => setMenu((v) => (v === "account" ? null : "account"))}>
                {initials(user?.name, user?.email)}
              </button>
              {menu === "account" && (
                <div ref={menuBox} className="menu" role="menu" aria-label={t("shell.menu")} onKeyDown={menuKeys}>
                  {user && <div className="whoami">{user.email}</div>}
                  {/* on a phone the bar has no room for the badge: it is said here */}
                  {readOnly && <div className="whoami narrow">{t("shell.readOnly")}</div>}
                  {(["zh", "en"] as const).map((l) => (
                    <button key={l} type="button" className="mi" role="menuitemradio" aria-checked={locale === l}
                            onClick={() => pickLocale(l)}>
                      {l === "zh" ? "中文" : "English"}{locale === l && <small>✓</small>}
                    </button>
                  ))}
                  <div className="sep" />
                  <button type="button" className="mi narrow mid" role="menuitem" onClick={toggle}>
                    {t("theme.toggle")}<small>{t(`theme.${nfTheme}`)}</small>
                  </button>
                  {scope("mi narrow scope-m")}
                  <button type="button" className="mi narrow mid" role="menuitem" onClick={toClassic}>{t("shell.classic")}</button>
                  {/* the size of a hosted page's text (the classic top bar had it; NewUI's own pages are set in px) */}
                  <button type="button" className="mi" role="menuitem" onClick={nextFont}>
                    {t("shell.menu.fontSize")}<small>{t(`shell.font.${fontSize}`)}</small>
                  </button>
                  <button type="button" className="mi" role="menuitemcheckbox" aria-checked={singleKeys} onClick={flipSingleKeys}>
                    {t("shell.menu.singleKeys")}<small>{t(singleKeys ? "shell.on" : "shell.off")}</small>
                  </button>
                  {user && <Link className="mi" role="menuitem" to="/app/account/api-keys" onClick={() => setMenu(null)}>{t("shell.menu.apiKeys")}</Link>}
                  <Link className="mi" role="menuitem" to="/app/setup" onClick={() => setMenu(null)}>{t("shell.menu.setup")}</Link>
                  <div className="sep" />
                  <button type="button" className="mi" role="menuitem"
                          // a decision still inside its undo window is sent first, and has its answer, before the
                          // session goes: signing out is leaving — the person had decided
                          onClick={async () => { await pending.settle(); await logout(); navigate("/app/login", { replace: true }); }}>
                    {t("shell.menu.signOut")}
                  </button>
                </div>
              )}
            </div>
          </div>
        </header>
        {/* a hosted classic page is not drawn in here: components/layout/NewFrame draws it beside this element */}
        {!hosting && <main>{children}</main>}
        <CommandBar input={command} lens={lens ?? "decide"} tucked={tucked} onTheme={toggle} onHelp={() => setHelp(true)} />
        {pending.waiting && <PendingToast label={pending.waiting.label} due={pending.waiting.due} onUndo={undo} />}
        {/* a plain line never covers a decision's undo window: it sits above it */}
        {notice && <div className={`toast${pending.waiting ? " above" : ""}`} role="status"><span className="spark" aria-hidden="true" /><span className="msg">{notice}</span></div>}
        {help && <Help onClose={() => setHelp(false)} hosting={hosting} />}
        </WorldLayer>
      </div>
    </ShellContext.Provider>
  );
}
