import { lazy, Suspense, useLayoutEffect, useRef } from "react";
import { Navigate, Outlet, useLocation } from "react-router-dom";
import { Spinner } from "@/components/ui/Spinner";
import { frameMode, nativeTarget, stayClassic, type ClassicSection } from "@/lib/shellRoutes";
import { AccountScopeProvider, ScopeNotice } from "./AccountScope";
import { RestoreNotice, ShellEffects } from "./ShellEffects";
import "@/bridge.css";

// NewUI's shell is a chunk of its own: this file is part of the entry, and the classic interface must not carry it
const NewShell = lazy(() => import("@/newui/shell/NewShell").then((m) => ({ default: m.NewShell })));

/** A page whose own input takes the command bar's place. */
const NO_BAR = /^\/app\/chat(\/|$)/;

/** NewUI's frame around every page (round 3). A lens (/app/new/…) is drawn inside NewUI's shell. A classic page is
 *  HOSTED: it renders here, in the entry chunk, as a sibling of the shell and outside `.nf` — so no rule of NewUI's
 *  stylesheet can reach it, it scrolls as the page it always was, and it does not wait for NewUI's chunk — while the
 *  shell is one layer over it (top bar, command bar). `html.nf-on` (src/bridge.css) gives it NewUI's palette.
 *  One shell stays mounted while the person moves between lenses and pages: a decision inside its undo window is not
 *  sent early, the map is not laid out again. Where NewUI has its own page for an address, the address opens it
 *  (lib/shellRoutes.nativeTarget) — unless the person came through one of NewUI's exits to the classic page. */
export function NewFrame() {
  const location = useLocation();
  const hosted = frameMode(location.pathname) === "hosted";
  // the exit to a classic page stays open while the person moves inside that section (idempotent: a render may repeat)
  const stay = useRef<ClassicSection | null>(null);
  stay.current = hosted ? stayClassic(stay.current, location) : null;
  const target = hosted && stay.current === null ? nativeTarget(location.pathname, location.search, location.hash) : null;
  const noBar = hosted && NO_BAR.test(location.pathname);

  useLayoutEffect(() => {
    const root = document.documentElement;
    root.classList.add("nf-on");
    return () => root.classList.remove("nf-on", "nf-nobar");
  }, []);
  useLayoutEffect(() => { document.documentElement.classList.toggle("nf-nobar", noBar); }, [noBar]);

  return (
    <AccountScopeProvider>
      <Suspense fallback={hosted ? null : <Spinner />}>
        <NewShell hosting={hosted} tucked={noBar}>{hosted ? null : <Outlet />}</NewShell>
      </Suspense>
      {hosted && (
        <main className="cl-host p-6">
          <RestoreNotice />
          <ScopeNotice />
          {target ? <Navigate to={target} replace /> : <Outlet />}
        </main>
      )}
      <ShellEffects />
    </AccountScopeProvider>
  );
}
