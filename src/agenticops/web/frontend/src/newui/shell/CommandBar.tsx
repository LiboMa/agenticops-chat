import { useEffect, useState, type RefObject } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useAccountScope } from "@/components/layout/AccountScope";
import { useCanViewSettings } from "@/hooks/useBootstrap";
import { useSearch } from "@/hooks/useSearch";
import { useAllWaiting } from "../hooks/useAllWaiting";
import { useNfT } from "../i18n";
import { commandRows, moveRow, searchText } from "../lib/command";
import type { Lens } from "../lib/keys";

/** The command bar at the foot of every lens («/», Cmd/Ctrl+K): «/» lists commands, «@» lists things, plain text
 *  both. It goes to places; it does not talk to an agent (chat stays on the classic page, and a row says so). */
export function CommandBar({ input, lens, onTheme, onHelp }: {
  input: RefObject<HTMLInputElement>; lens: Lens; onTheme: () => void; onHelp: () => void;
}) {
  const t = useNfT();
  const navigate = useNavigate();
  const location = useLocation();
  const { accountId } = useAccountScope();
  const canSettings = useCanViewSettings();
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const [index, setIndex] = useState(0);
  // what is typed is searched a moment after the typing stops
  const [asked, setAsked] = useState("");
  useEffect(() => {
    const id = window.setTimeout(() => setAsked(searchText(q)), 220);
    return () => window.clearTimeout(id);
  }, [q]);
  const search = useSearch(asked);
  const waiting = useAllWaiting(accountId, open);
  const here = /^\/app\/new\/(decide|live|world)(\/|$)/.test(location.pathname) ? location.pathname + location.search : undefined;
  const rows = commandRows(q, { t, waiting: waiting.data?.items ?? [], found: asked && asked === searchText(q) ? search.data : undefined, lens, here, canSettings });
  const at = Math.min(index, Math.max(0, rows.length - 1));
  const seeking = !!searchText(q) && (asked !== searchText(q) || search.isFetching);

  const close = () => { setOpen(false); setQ(""); setIndex(0); input.current?.blur(); };
  const run = (k: number) => {
    const row = rows[k];
    if (!row) return;
    close();
    if (row.run === "theme") onTheme();
    else if (row.run === "help") onHelp();
    else if (row.to) navigate(row.to, row.state ? { state: row.state } : undefined);
  };

  return (
    <>
      {open && (rows.length > 0 || !!q.trim()) && (
        <div className="sugg" id="nf-sugg" role="listbox" aria-label={t("cmd.label")}>
          {rows.map((r, k) => (
            <button key={r.id} id={`nf-sugg-${k}`} type="button" role="option" aria-selected={k === at}
                    onMouseDown={(e) => e.preventDefault()} onClick={() => run(k)} onMouseEnter={() => setIndex(k)}>
              <span>{r.label}</span>{r.hint && <small>{r.hint}</small>}
            </button>
          ))}
          {rows.length === 0 && <p className="sugg-note">{t(seeking ? "cmd.seeking" : "cmd.none")}</p>}
        </div>
      )}
      <div className="barwrap">
        <label className="bar">
          <span className="spark" aria-hidden="true" />
          <input ref={input} id="nf-cmd" type="text" role="combobox" autoComplete="off" spellCheck={false} value={q}
                 aria-label={t("cmd.label")} aria-expanded={open} aria-controls="nf-sugg" aria-autocomplete="list"
                 aria-activedescendant={open && rows.length ? `nf-sugg-${at}` : undefined} placeholder={t("cmd.placeholder")}
                 onChange={(e) => { setQ(e.target.value); setIndex(0); setOpen(true); }}
                 onFocus={() => setOpen(true)} onBlur={() => setOpen(false)}
                 onKeyDown={(e) => {
                   if (e.nativeEvent.isComposing || e.keyCode === 229) return;            // an input method is picking a candidate
                   if (e.key !== "ArrowDown" && e.key !== "ArrowUp" && e.key !== "Enter" && e.key !== "Escape") return;
                   // a key the bar uses is the bar's alone. Running a row leaves the field and may put another lens on the
                   // page before this same key press reaches the shell — which would then hand it to that lens (Enter on
                   // «待决» opens the story: the item the bar had just opened went straight on to its story)
                   e.nativeEvent.stopPropagation();
                   if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); setIndex(moveRow(rows.length, at, e.key === "ArrowDown" ? 1 : -1)); }
                   else if (e.key === "Enter") { e.preventDefault(); run(at); }
                   else close();
                 }} />
          <kbd>/</kbd>
        </label>
      </div>
    </>
  );
}
