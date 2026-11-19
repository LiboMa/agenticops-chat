import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { ApiError, apiFetch } from "@/api/client";
import { Spinner } from "@/components/ui/Spinner";
import { useBootstrap } from "@/hooks/useBootstrap";
import { homeTarget, probeFor } from "@/lib/home";
import { forgetLastRoute, localLastRoute } from "@/lib/preferences";
import { readChoice } from "@/lib/shellChoice";
import { needsSetup } from "@/lib/setup";
import type { Readiness } from "@/api/types";

/** The bare /app: a pinned home, else the last allow-listed place (checked first — a deleted or no longer
 *  visible object falls back to its list with a notice that names nothing), else Chat. Waits for the
 *  bootstrap (preferences) up to 3 s; a failure or a timeout lands on Chat. An administrator of an installation
 *  with no enabled cloud account is shown the setup overview first (N23) — unless they just came from it. */
export function HomeResolver() {
  const boot = useBootstrap();
  const navigate = useNavigate();
  const fromSetup = !!(useLocation().state as { fromSetup?: boolean } | null)?.fromSetup;
  const [timedOut, setTimedOut] = useState(false);
  const settled = boot.isSuccess || boot.isError || timedOut;

  useEffect(() => {
    const t = setTimeout(() => setTimedOut(true), 3000);
    return () => clearTimeout(t);
  }, []);

  useEffect(() => {
    if (!settled) return;
    let cancelled = false;
    (async () => {
      if (boot.data?.user?.is_admin && !fromSetup) {
        try {       // asked of administrators only; a slow or failed answer never keeps anyone from the workspace
          const r = await Promise.race([apiFetch<Readiness>("/setup/readiness"),
                                        new Promise<undefined>((resolve) => setTimeout(() => resolve(undefined), 3000))]);
          if (needsSetup(true, r)) {
            if (!cancelled) navigate("/app/setup", { replace: true });
            return;
          }
        } catch { /* the workspace it is */ }
      }
      const prefs = boot.data?.preferences ?? null;
      // this browser's last place first (freshest); the server's copy when this is a new device
      // in the new interface /app lands on «待决» unless chat or reports is pinned (lib/home)
      const target = homeTarget(prefs, localLastRoute() ?? prefs?.last_route ?? null, readChoice());
      const probe = probeFor(target);
      if (probe) {
        try {
          // a hung check must not keep the spinner up: after 3 s go on to the target (the page will say)
          await Promise.race([apiFetch(probe.api), new Promise((resolve) => setTimeout(resolve, 3000))]);
        } catch (e) {
          if (e instanceof ApiError && (e.status === 404 || e.status === 403)) {
            forgetLastRoute();
            if (!cancelled) navigate(probe.list, { replace: true, state: { restoreNotice: true } });
            return;
          }
        }
      }
      if (!cancelled) navigate(target, { replace: true });
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- resolve once, when the preferences settle
  }, [settled]);

  return <Spinner />;
}
