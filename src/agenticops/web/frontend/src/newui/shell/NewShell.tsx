import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { useAccountScope } from "@/components/layout/AccountScope";
import { initials } from "@/components/layout/TopBar";
import { useAccounts } from "@/hooks/useAccounts";
import { useAuth } from "@/hooks/useAuth";
import { useReadOnly } from "@/hooks/useBootstrap";
import { useTheme } from "@/hooks/useTheme";
import { useLocale } from "@/i18n/LocaleContext";
import { savePreferences } from "@/lib/preferences";
import { useWaitingCounts } from "../hooks/useDecideQueue";
import { useNfT } from "../i18n";
import { focusContext, keyIntent, type Lens } from "../lib/keys";
import { groupCounts } from "../lib/queue";
import { Help } from "./Help";
import { ShellContext, type LensKeys, type ShellApi } from "./shellContext";

const LENSES: Lens[] = ["decide", "live", "world"];
const SINGLE_KEYS = "nf-single-keys";

/** The lens a path belongs to. «经过» (story) is a page of the lens it was opened from, «待决» unless said. */
function lensOf(pathname: string, from: unknown): Lens {
  const m = /^\/app\/new\/(decide|live|world|story)(\/|$)/.exec(pathname);
  if (!m) return "decide";
  if (m[1] === "story") return from === "live" || from === "world" ? from : "decide";
  return m[1] as Lens;
}

const readFlag = (key: string): boolean => {
  try { return localStorage.getItem(key) !== "off"; } catch { return true; }
};

/** NewUI's frame, outside the classic shell: the lens tabs, the account scope, theme, language, help, the way back to
 *  the classic interface and the account menu — and the one place that listens to the keyboard. */
export function NewShell({ children }: { children: ReactNode }) {
  const t = useNfT();
  const { locale, setLocale } = useLocale();
  const { theme, toggle } = useTheme();
  const { user, logout } = useAuth();
  const readOnly = useReadOnly();
  const accounts = useAccounts();
  const { accountId, setAccountId } = useAccountScope();
  const navigate = useNavigate();
  const location = useLocation();
  const lens = lensOf(location.pathname, (location.state as { from?: string } | null)?.from);
  const counts = useWaitingCounts(accountId);

  const [help, setHelp] = useState(false);
  const [menu, setMenu] = useState(false);
  const [singleKeys, setSingleKeys] = useState(() => readFlag(SINGLE_KEYS));
  const [notice, setNotice] = useState<string | null>(null);
  const lensKeys = useRef<LensKeys | null>(null);
  const lastPlace = useRef<Partial<Record<Lens, string>>>({});
  const avatar = useRef<HTMLButtonElement>(null);
  const menuBox = useRef<HTMLDivElement>(null);
  const noticeTimer = useRef<number | null>(null);

  // each lens remembers where you were in it: «1» from the map goes back to the item you were reading
  useEffect(() => {
    if (/^\/app\/new\/(decide|live|world)(\/|$)/.test(location.pathname)) lastPlace.current[lens] = location.pathname + location.search;
  }, [lens, location.pathname, location.search]);
  const go = useCallback((l: Lens) => navigate(lastPlace.current[l] ?? `/app/new/${l}`), [navigate]);

  useEffect(() => { document.title = `AgenticOps · ${t(`lens.${lens}`)}`; }, [lens, t]);

  const notify = useCallback((text: string) => {
    if (noticeTimer.current) window.clearTimeout(noticeTimer.current);
    setNotice(text);
    noticeTimer.current = window.setTimeout(() => { noticeTimer.current = null; setNotice(null); }, 2600);
  }, []);
  useEffect(() => () => { if (noticeTimer.current) window.clearTimeout(noticeTimer.current); }, []);

  const closeMenu = useCallback((refocus: boolean) => {
    setMenu(false);
    if (refocus) avatar.current?.focus();
  }, []);

  useEffect(() => {
    const down = (e: KeyboardEvent) => {
      const intent = keyIntent(e, { ...focusContext(document.activeElement), modal: help || menu, singleKeys });
      if (!intent) return;
      if (intent.type === "escape") {
        if (help) return setHelp(false);
        if (menu) return closeMenu(true);
        if (lensKeys.current?.onEscape?.()) return;
        if (focusContext(document.activeElement).inField) (document.activeElement as HTMLElement).blur();
        return;
      }
      if (intent.type === "command") return;                       // the command bar arrives with its own stage
      if (intent.type === "help") return setHelp(true);
      if (intent.type === "theme") return toggle();
      if (intent.type === "lens") return go(intent.lens);
      if (lensKeys.current?.onKey?.(intent.key, e, intent.repeat)) e.preventDefault();
    };
    const up = (e: KeyboardEvent) => lensKeys.current?.onKeyUp?.(e.key.toLowerCase(), e);
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    return () => { window.removeEventListener("keydown", down); window.removeEventListener("keyup", up); };
  }, [help, menu, singleKeys, toggle, go, closeMenu]);

  // the account menu: the pointer anywhere else closes it; opening it puts the focus on its first line
  useEffect(() => {
    if (!menu) return;
    menuBox.current?.querySelector<HTMLElement>(".mi")?.focus();
    const away = (e: PointerEvent) => {
      if (!menuBox.current?.parentElement?.contains(e.target as Node)) setMenu(false);
    };
    document.addEventListener("pointerdown", away);
    return () => document.removeEventListener("pointerdown", away);
  }, [menu]);
  const menuKeys = (e: React.KeyboardEvent) => {
    const lines = [...(menuBox.current?.querySelectorAll<HTMLElement>(".mi") ?? [])].filter((el) => el.offsetParent !== null);
    const at = lines.indexOf(document.activeElement as HTMLElement);
    const to = e.key === "ArrowDown" ? at + 1 : e.key === "ArrowUp" ? at - 1 : e.key === "Home" ? 0 : e.key === "End" ? lines.length - 1 : null;
    if (to !== null && lines.length) { e.preventDefault(); lines[(to + lines.length) % lines.length].focus(); }
    if (e.key === "Tab") setMenu(false);
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
  const scope = (className: string) => (
    <select className={className} aria-label={t("scope.label")} value={accountId == null ? "" : String(accountId)}
            onChange={(e) => setAccountId(e.target.value ? Number(e.target.value) : null)}>
      <option value="">{t("scope.all")}</option>
      {(accounts.data ?? []).map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
    </select>
  );
  const api = useMemo<ShellApi>(() => ({
    setLensKeys: (keys) => { lensKeys.current = keys; }, notify, singleKeys,
  }), [notify, singleKeys]);
  const nfTheme = theme === "dark" ? "night" : "day";

  return (
    <ShellContext.Provider value={api}>
      <div className="nf nobar" data-theme={nfTheme}>
        <header className="top">
          <div className="tabs" role="tablist" aria-label={t("lens.label")}>
            {LENSES.map((l, i) => (
              <button key={l} type="button" role="tab" aria-selected={lens === l} onClick={() => go(l)}>
                <span className="n">{i + 1}</span>{t(`lens.${l}`)}
                {l === "decide" && <b className="cnt num">{countText}</b>}
              </button>
            ))}
          </div>
          <div className="gap" />
          <div className="who">
            {scope("scope")}
            <Link className="chip-btn wide" to="/app" title={t("shell.classic.hint")}>{t("shell.classic")}</Link>
            <button type="button" className="chip-btn wide" onClick={toggle} aria-label={t("theme.toggle")}>{t(`theme.${nfTheme}`)}</button>
            <button type="button" className="chip-btn" onClick={() => setHelp(true)} aria-label={t("keys.open")}>?</button>
            {readOnly && <span className="ro" title={t("shell.readOnly.hint")}>{t("shell.readOnly")}</span>}
            <div className="menuwrap">
              <button ref={avatar} type="button" className="avatar" aria-label={t("shell.menu")} aria-haspopup="menu"
                      aria-expanded={menu} onClick={() => setMenu((v) => !v)}>
                {initials(user?.name, user?.email)}
              </button>
              {menu && (
                <div ref={menuBox} className="menu" role="menu" aria-label={t("shell.menu")} onKeyDown={menuKeys}>
                  {user && <div className="whoami">{user.email}</div>}
                  {(["zh", "en"] as const).map((l) => (
                    <button key={l} type="button" className="mi" role="menuitemradio" aria-checked={locale === l}
                            onClick={() => pickLocale(l)}>
                      {l === "zh" ? "中文" : "English"}{locale === l && <small>✓</small>}
                    </button>
                  ))}
                  <div className="sep" />
                  <button type="button" className="mi narrow" role="menuitem" onClick={toggle}>
                    {t("theme.toggle")}<small>{t(`theme.${nfTheme}`)}</small>
                  </button>
                  {scope("mi narrow scope-m")}
                  <Link className="mi narrow" role="menuitem" to="/app">{t("shell.classic")}</Link>
                  <button type="button" className="mi" role="menuitemcheckbox" aria-checked={singleKeys} onClick={flipSingleKeys}>
                    {t("shell.menu.singleKeys")}<small>{t(singleKeys ? "shell.on" : "shell.off")}</small>
                  </button>
                  {user && <Link className="mi" role="menuitem" to="/app/account/api-keys">{t("shell.menu.apiKeys")}</Link>}
                  <div className="sep" />
                  <button type="button" className="mi" role="menuitem"
                          onClick={async () => { await logout(); navigate("/app/login", { replace: true }); }}>
                    {t("shell.menu.signOut")}
                  </button>
                </div>
              )}
            </div>
          </div>
        </header>
        <main>{children}</main>
        {notice && <div className="toast" role="status"><span className="spark" aria-hidden="true" /><span className="msg">{notice}</span></div>}
        {help && <Help onClose={() => setHelp(false)} />}
      </div>
    </ShellContext.Provider>
  );
}
