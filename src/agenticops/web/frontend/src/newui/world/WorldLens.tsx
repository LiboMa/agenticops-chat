import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { useAccountScope } from "@/components/layout/AccountScope";
import { useAccounts } from "@/hooks/useAccounts";
import { useReadOnly } from "@/hooks/useBootstrap";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { useAllWaiting } from "../hooks/useAllWaiting";
import { useNfT } from "../i18n";
import { storyPath } from "../lib/story";
import { NO_ASK, reconcile, scene, type Ask, type Drawn, type View, type Waiting } from "../lib/world/scene";
import { utcStamp } from "../lib/time";
import { Message, StateBlock } from "../shell/StateBlock";
import { useLensKeys, useShell } from "../shell/shellContext";
import { useWorld } from "./WorldData";
import { Check, Happen, Legend, NodeCard, PathHint, Tools, healthKey } from "./WorldPanels";

const NARROW = "(max-width: 760px)";

/** «全景»: every resource of the latest relation-graph build on one map. What to show is worked out once
 *  (lib/world/scene) from what the person asked for; the canvas draws that result and the panels read their numbers
 *  from it. Once a second the lens asks the canvas what it actually drew and compares: the «数据核对» card says
 *  whether the picture matches the data. The open resource and the filters live in the address. */
export function WorldLens() {
  const t = useNfT();
  const navigate = useNavigate();
  const location = useLocation();
  const world = useWorld();
  const { graph: g, sky, sky3, want, load3d } = world;
  const { notify, setRootFlag } = useShell();
  useEffect(() => { want(); }, [want]);
  const { accountId } = useAccountScope();
  const accounts = useAccounts();
  const narrow = useMediaQuery(NARROW);
  const readOnly = useReadOnly();
  const waitingQ = useAllWaiting(accountId);
  const [params, setParams] = useSearchParams();
  const [q, setQ] = useState("");
  const [pathMode, setPathMode] = useState(() => params.has("a"));
  const [bad, setBad] = useState<{ what: keyof Drawn; want: number; got: number }[] | null>(null);
  const [perf, setPerf] = useState<{ fps: number; ms: number | null } | null>(null);
  const [busy, setBusy] = useState(false);
  const [turning, setTurning] = useState(false);
  const [tip, setTip] = useState<{ x: number; y: number; i: number } | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const search = useRef<HTMLInputElement>(null);
  const drag = useRef<{ x: number; y: number; moved: boolean } | null>(null);

  // what the address says: the open resource, the filters, the two ends of a path — by resource id, so a link survives a rebuild
  const at = useCallback((key: string): number | null => {
    const ref = params.get(key);
    return ref && g ? g.byId.get(`res:${ref}`) ?? null : null;
  }, [params, g]);
  const ask: Ask = useMemo(() => ({
    ...NO_ASK, q, account: accountId, type: params.get("type"), group: params.get("grp"), onlyAbnormal: params.get("abn") === "1",
    sel: at("sel"), focus: params.get("near") === "1" && at("sel") !== null, a: at("a"), b: at("b"),
  }), [q, accountId, params, at]);
  const patch = useCallback((change: Record<string, string | null>) => {
    setParams((old) => {
      const next = new URLSearchParams(old);
      for (const [k, v] of Object.entries(change)) { if (v === null || v === "") next.delete(k); else next.set(k, v); }
      return next;
    }, { replace: true });
  }, [setParams]);
  const refOf = (i: number | null) => (i === null || !g ? null : String(g.nodes[i].ref));

  const waiting: Waiting[] | null = useMemo(
    () => waitingQ.data?.items.map((it) => ({ id: it.id, ref: it.resource?.ref ?? null })) ?? null, [waitingQ.data]);
  const sc = useMemo(() => (g ? scene(g, ask, waiting) : null), [g, ask, waiting]);
  const ready = world.status === "ready" && !!g && !!sc;

  // the view: flat, or 3D once its engine is here (it is fetched the first time someone asks for it)
  const want3d = params.get("v") === "3d";
  const view: View = want3d && sky3 ? "3d" : "2d";
  const act = useRef({ pick: (_i: number | null) => {}, hover: (_i: number | null, _x: number, _y: number) => {} });
  useEffect(() => {
    if (!want3d || sky3) return;
    let live = true;
    setBusy(true);
    void load3d({ pick: (i) => act.current.pick(i), hover: (i, x, y) => act.current.hover(i, x, y) }).then((ok) => {
      if (!live) return;
      setBusy(false);
      if (!ok) { notify(t("view.failed")); patch({ v: null }); }
    });
    return () => { live = false; };
  }, [want3d, sky3, load3d, notify, t, patch]);
  useEffect(() => {
    if (view !== "3d" || !sky3) return;
    sky3.show(true);
    setRootFlag("view3d", true);
    return () => { sky3.show(false); setRootFlag("view3d", false); setTurning(false); sky3.turn(false); };
  }, [view, sky3, setRootFlag]);

  // the canvas: this lens owns it while it is on the page; the map is fitted into what the panels leave free
  const carded = ask.sel !== null && !pathMode;
  useEffect(() => {
    if (!sky) return;
    // a phone: the panels are a column above the map (44 % of the height, see newui.css), the open resource's card below it
    const tall = window.innerHeight;
    const inset = narrow ? { left: 0, right: 0, top: Math.round(tall * 0.44) + 60, bottom: carded ? Math.round(tall * 0.3) : 0 }
                         : { left: 320, right: carded ? 330 : 20, top: 0, bottom: 0 };
    sky.setMode({ world: true, off: view === "3d", inset });
    sky3?.setInset(inset.left, inset.right);
  }, [sky, sky3, narrow, carded, view]);
  useEffect(() => () => { sky?.setMode({ world: false, inset: { left: 0, right: 0, top: 0, bottom: 0 } }); sky?.apply(null, null, null); }, [sky]);
  // a link that names a resource opens ON it
  const flown = useRef(false);
  useEffect(() => {
    if (flown.current || !ready || !sky) return;
    flown.current = true;
    if (ask.sel !== null && !pathMode) sky.flyTo(ask.sel);
  }, [ready, sky, ask.sel, pathMode]);
  // whichever view is on: the same camera moves
  const cam = view === "3d" && sky3 ? sky3 : sky;
  useEffect(() => {
    sky?.apply(ready ? sc : null, pathMode ? null : ask.sel, g);
    sky3?.apply(ready ? sc : null, pathMode ? null : ask.sel, g);
    setBad(null);
  }, [sky, sky3, sc, ready, ask.sel, pathMode, g, view]);

  // the picture against the data, once the canvas has drawn this result — and again every second
  useEffect(() => {
    if (!sky || !ready || !sc) return;
    const check = () => {
      if (view === "3d" && sky3) { setBad(reconcile(sc, sky3.stats(), "3d")); setPerf({ fps: sky3.fps, ms: null }); }
      else { setBad(reconcile(sc, sky.stats(), "2d")); setPerf({ fps: sky.fps, ms: sky.drawMs }); }
      setNow(Date.now());
    };
    // the 3D engine builds its objects over a few frames: ask it a little later
    const first = window.setTimeout(check, view === "3d" ? 900 : 260), again = window.setInterval(check, 1000);
    return () => { window.clearTimeout(first); window.clearInterval(again); };
  }, [sky, sky3, sc, ready, view]);

  const pick = useCallback((i: number | null, fly = true) => {
    if (!g) return;
    if (pathMode) {
      if (i === null) return;
      if (ask.a === null || ask.b !== null) patch({ a: refOf(i), b: null });
      else if (i !== ask.a) { patch({ b: refOf(i) }); cam?.home(); }
      return;
    }
    patch({ sel: refOf(i), near: i === null ? null : params.get("near") });
    if (i !== null && fly) cam?.flyTo(i);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [g, pathMode, ask.a, ask.b, patch, cam, params]);
  act.current = { pick: (i) => pick(i, false), hover: (i, x, y) => setTip(i === null ? null : { x, y, i }) };
  const setView = useCallback((v: View) => patch({ v: v === "3d" ? "3d" : null }), [patch]);
  const toggleTurn = useCallback(() => { if (view !== "3d" || !sky3) return; const on = !sky3.turning; sky3.turn(on); setTurning(on); }, [view, sky3]);
  const togglePath = useCallback((from?: number | null) => {
    const on = !pathMode;
    setPathMode(on);
    patch({ near: null, a: on ? refOf(from ?? ask.sel) : null, b: null });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pathMode, patch, ask.sel, g]);
  const toggleFocus = useCallback(() => { if (ask.sel !== null) patch({ near: ask.focus ? null : "1" }); }, [ask.sel, ask.focus, patch]);
  const here = location.pathname + location.search;

  useLensKeys({
    onKey: (key) => {
      if (!ready) return false;
      if (key === "f") { search.current?.focus(); search.current?.select(); return true; }
      if (key === "l") { togglePath(); return true; }
      if (key === "g") { toggleFocus(); return true; }
      if (key === "h") { cam?.home(); return true; }
      if (key === "v") { setView(want3d ? "2d" : "3d"); return true; }
      if (key === "r" && view === "3d") { toggleTurn(); return true; }
      return false;
    },
    // Esc peels one layer at a time: the path, «only around it», the open resource, a moved camera
    onEscape: () => {
      if (pathMode) { togglePath(); return true; }
      if (ask.focus) { patch({ near: null }); return true; }
      if (ask.sel !== null) { patch({ sel: null, near: null }); cam?.home(); return true; }
      cam?.home();
      return false;
    },
  });

  // gestures on the map itself — wherever no panel covers it
  const onDown = (e: React.PointerEvent<HTMLElement>) => {
    if (e.target !== e.currentTarget || !ready) return;
    drag.current = { x: e.clientX, y: e.clientY, moved: false };
    e.currentTarget.setPointerCapture(e.pointerId);
  };
  const onMove = (e: React.PointerEvent<HTMLElement>) => {
    const d = drag.current;
    if (d) {
      const dx = e.clientX - d.x, dy = e.clientY - d.y;
      if (d.moved || Math.hypot(dx, dy) > 4) { d.moved = true; sky?.panBy(dx, dy); d.x = e.clientX; d.y = e.clientY; e.currentTarget.style.cursor = "grabbing"; setTip(null); }
      return;
    }
    if (e.target !== e.currentTarget || !ready) { setTip(null); e.currentTarget.style.cursor = ""; return; }
    const i = sky?.pick(e.clientX, e.clientY) ?? null;
    e.currentTarget.style.cursor = i === null ? "grab" : "pointer";
    setTip(i === null ? null : { x: e.clientX, y: e.clientY, i });
  };
  const onUp = (e: React.PointerEvent<HTMLElement>) => {
    const d = drag.current;
    drag.current = null;
    e.currentTarget.style.cursor = "";
    if (!d || d.moved) return;
    pick(sky?.pick(e.clientX, e.clientY) ?? null, false);
  };
  const section = useRef<HTMLElement>(null);
  useEffect(() => {                                   // the wheel must be a non-passive listener to keep the page from scrolling
    const el = section.current;
    if (!el) return;
    const wheel = (e: WheelEvent) => { if (e.target !== el || !sky) return; e.preventDefault(); sky.zoomAt(e.clientX, e.clientY, Math.exp(-e.deltaY * 0.0016)); };
    el.addEventListener("wheel", wheel, { passive: false });
    return () => el.removeEventListener("wheel", wheel);
  }, [sky]);

  const accountName = useCallback((id: number | null) =>
    (id === null ? t("world.noAccount") : accounts.data?.find((a) => a.id === id)?.name ?? g?.accounts.find((a) => a.id === id)?.name ?? `#${id}`), [accounts.data, g, t]);
  const selNode = ready && ask.sel !== null ? g!.nodes[ask.sel] : null;
  const mine = selNode ? (waitingQ.data?.items ?? []).filter((it) => it.resource?.ref === selNode.ref) : [];

  return (
    <section ref={section} className="view" id="world" onPointerDown={onDown} onPointerMove={onMove} onPointerUp={onUp} onPointerLeave={() => setTip(null)}>
      {!ready ? (
        <div className="wstate card">
          {world.status === "loading" ? <StateBlock kind="loading" />
            : world.status === "failed" ? <StateBlock kind="failed" failKey="world.failed.p" onRetry={world.retry} />
            : <Message big={t("world.empty.big")}><p>{t("world.empty.p")}</p></Message>}
        </div>
      ) : (
        <>
          <div className="wleft">
            {world.staleAt !== null && <p className="stalebar" role="alert">{t("world.stale", { t: utcStamp(world.staleAt, now) })}</p>}
            <Tools g={g!} ask={ask} sc={sc!} search={search} pathMode={pathMode} view={view} busy={busy} turning={turning} onView={setView} onTurn={toggleTurn}
                   onAsk={(change) => { if ("q" in change) setQ(change.q ?? ""); patch({ ...("type" in change ? { type: change.type ?? null } : {}),
                     ...("group" in change ? { grp: change.group ?? null } : {}), ...("onlyAbnormal" in change ? { abn: change.onlyAbnormal ? "1" : null } : {}) }); }}
                   onPick={(i) => pick(i)} onPath={() => togglePath()} onHome={() => cam?.home()} />
            <Check sc={sc!} view={view} bad={bad} perf={perf} buildId={g!.buildId} builtAt={world.builtAt} building={world.building} now={now} />
            <Happen g={g!} sc={sc!} complete={waitingQ.data?.complete ?? true} readOnly={readOnly} onPick={(i) => pick(i)} onDecide={() => navigate("/app/new/decide")} />
          </div>
          {pathMode && <PathHint g={g!} ask={ask} sc={sc!} onExit={() => togglePath()} />}
          {selNode && !pathMode && (
            <NodeCard key={selNode.id} g={g!} i={selNode.i} ask={ask} mine={mine} accountName={accountName} now={now}
                      onPick={(i) => pick(i)} onClose={() => { patch({ sel: null, near: null }); cam?.home(); }} onFocus={toggleFocus}
                      onPathFrom={() => togglePath(selNode.i)}
                      onStory={(item) => navigate(storyPath(item), { state: { from: "world", back: here } })}
                      onDecide={(item) => navigate(`/app/new/decide/${item}`)} />
          )}
          <Legend t={t} view={view} />
          {tip && <div id="tip" style={{ left: tip.x + 14, top: tip.y + 12 }}>{g!.nodes[tip.i].name}　{g!.nodes[tip.i].type}　{t(healthKey(g!.nodes[tip.i]))}</div>}
        </>
      )}
    </section>
  );
}
