import { useCallback, useEffect, useState } from "react";
import type { EvidenceVm } from "../../lib/briefs/cause";
import { useShell } from "../../shell/shellContext";
import { Peek } from "./Peek";

/** The evidence panel beside a page («待决», «经过»). It belongs to the item it was opened on: once the page shows
 *  another item it is closed. ← → walk the evidence, Space closes. */
export function usePeek(owner: string | null) {
  const { setRootFlag } = useShell();
  const [peek, setPeek] = useState<{ evidence: EvidenceVm[]; index: number; owner: string } | null>(null);
  const open = !!peek && peek.owner === owner;
  useEffect(() => { setRootFlag("peeking", open); return () => setRootFlag("peeking", false); }, [open, setRootFlag]);
  const show = useCallback((evidence: EvidenceVm[], index: number) => { if (owner) setPeek({ evidence, index, owner }); }, [owner]);
  const close = useCallback(() => setPeek(null), []);
  /** true = the key was the panel's */
  const onKey = (key: string): boolean => {
    if (!open || !peek) return false;
    if (key === "arrowright" || key === "arrowleft") {
      const n = peek.evidence.length;
      setPeek({ ...peek, index: (peek.index + (key === "arrowright" ? 1 : -1) + n) % n });
      return true;
    }
    if (key === " ") { setPeek(null); return true; }
    return false;
  };
  return { open, show, close, onKey, node: open && peek ? <Peek evidence={peek.evidence} index={peek.index} onClose={close} /> : null };
}
