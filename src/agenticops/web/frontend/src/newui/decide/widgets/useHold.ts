import { useCallback, useEffect, useRef, useState } from "react";
import { HOLD_MS, holdStep, type HoldEvent, type HoldState, type HoldTarget } from "../../lib/hold";

/** Drives lib/hold: `target` is what the page shows NOW (null = nothing that may be approved). The hold remembers the
 *  target it started with; when the time is up it fires that one — and only if the page still shows it. Losing the
 *  window's focus, going to the background, or ANY other key going down cancels: the hook listens for keys itself,
 *  in the capture phase, so a key the shell takes («/» moves the focus to the command bar), Escape, a modifier or a
 *  key that moves nothing still lets go — the approval must not fire under a person who has gone on to something
 *  else. `down(key)` says which key started it (none = the pointer). */
export function useHold(target: HoldTarget | null, onFire: (t: HoldTarget) => void) {
  const [holding, setHolding] = useState(false);
  const [hint, setHint] = useState(false);
  const state = useRef<HoldState>({ phase: "idle" });
  const shown = useRef(target);
  const fire = useRef(onFire);
  const timer = useRef<number | null>(null);
  const hintTimer = useRef<number | null>(null);
  const startKey = useRef<string | null>(null);
  shown.current = target;
  fire.current = onFire;

  const apply = useCallback((event: HoldEvent) => {
    const r = holdStep(state.current, event);
    state.current = r.state;
    setHolding(r.state.phase === "holding");
    if (r.state.phase === "idle" && timer.current !== null) { window.clearTimeout(timer.current); timer.current = null; }
    if (r.hint) {
      setHint(true);
      if (hintTimer.current !== null) window.clearTimeout(hintTimer.current);
      hintTimer.current = window.setTimeout(() => setHint(false), 900);
    }
    if (r.fire) fire.current(r.fire);
  }, []);

  const isHolding = () => (state.current as HoldState).phase === "holding";      // read after apply(): it moves the state
  const tick = useCallback(() => {
    timer.current = null;
    apply({ type: "tick", at: performance.now(), shown: shown.current });
    if (isHolding()) timer.current = window.setTimeout(tick, 16);                  // a timer may fire a hair early
  }, [apply]);

  const down = useCallback((key?: string) => {
    if (isHolding()) return;
    apply({ type: "down", target: shown.current, at: performance.now() });
    if (isHolding()) { startKey.current = typeof key === "string" ? key.toLowerCase() : null; timer.current = window.setTimeout(tick, HOLD_MS); }
  }, [apply, tick]);
  const up = useCallback(() => apply({ type: "up", at: performance.now() }), [apply]);
  const cancel = useCallback(() => apply({ type: "cancel" }), [apply]);

  useEffect(() => {
    const hidden = () => { if (document.visibilityState !== "visible") cancel(); };
    const otherKey = (e: KeyboardEvent) => { if (isHolding() && e.key.toLowerCase() !== startKey.current) cancel(); };
    window.addEventListener("blur", cancel);
    document.addEventListener("visibilitychange", hidden);
    window.addEventListener("keydown", otherKey, true);
    return () => {
      window.removeEventListener("blur", cancel);
      document.removeEventListener("visibilitychange", hidden);
      window.removeEventListener("keydown", otherKey, true);
      if (timer.current !== null) window.clearTimeout(timer.current);
      if (hintTimer.current !== null) window.clearTimeout(hintTimer.current);
    };
  }, [cancel]);

  return { holding, hint, down, up, cancel };
}
