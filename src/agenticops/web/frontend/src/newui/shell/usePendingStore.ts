import { useEffect, useMemo, useRef, useState } from "react";
import { keepaliveFor } from "@/api/client";
import { Pending, type Deferred } from "../lib/pending";

/** The shell's ONE waiting decision (lib/pending, N13): what is waiting — for the toast —, a way to add one, and
 *  «undo». A decision still waiting when the page goes away is sent then: the person had decided. (`pagehide` covers
 *  a closed tab and a reload; the requests that leave in that moment are marked keep-alive so the browser lets them
 *  finish. Leaving NewUI for the classic pages unmounts the shell: same thing, no keep-alive needed.) */
export function usePendingStore() {
  const ref = useRef<Pending | null>(null);
  if (ref.current === null) ref.current = new Pending();
  const store = ref.current;
  const [waiting, setWaiting] = useState(store.waiting);
  useEffect(() => store.subscribe(() => setWaiting(store.waiting)), [store]);
  useEffect(() => {
    const leaving = () => { if (store.waiting) { keepaliveFor(3000); void store.flush(); } };
    window.addEventListener("pagehide", leaving);
    return () => { window.removeEventListener("pagehide", leaving); void store.flush(); };
  }, [store]);
  // `settle`: send the waiting decision now and wait for its answer — for what must not happen before it (signing
  // out takes the session away: a decision still waiting then left without credentials, or with ones the server had
  // just withdrawn, and nothing said that it never happened)
  const act = useMemo(() => ({ defer: (d: Deferred) => store.add(d), undo: () => store.undo(), settle: () => store.flush() }), [store]);
  return { waiting, ...act };
}
