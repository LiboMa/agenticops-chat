import { createContext, useContext, useEffect, useRef } from "react";
import type { AttentionItem } from "@/lib/attention";
import type { EvidenceVm } from "../../lib/briefs/cause";

/** What the open brief does with the keys «待决» does not use itself (J / K move through the queue). */
export interface BriefKeys {
  /** true = used */
  onKey?: (key: string, e: KeyboardEvent, repeat: boolean) => boolean | void;
  onKeyUp?: (key: string) => void;
  /** Escape: true when something of the brief closed (the reason box) */
  onEscape?: () => boolean;
}

export interface DecideApi {
  setBriefKeys: (keys: BriefKeys | null) => void;
  /** a decision went through: say it, and show what is next in the queue */
  done: (message: string) => void;
  /** open the evidence panel on one of these */
  openPeek: (evidence: EvidenceVm[], index: number) => void;
}

export const DecideContext = createContext<DecideApi>({ setBriefKeys: () => {}, done: () => {}, openPeek: () => {} });
export const useDecide = () => useContext(DecideContext);

export function useBriefKeys(keys: BriefKeys): void {
  const { setBriefKeys } = useDecide();
  const latest = useRef(keys);
  latest.current = keys;
  useEffect(() => {
    setBriefKeys({
      onKey: (key, e, repeat) => latest.current.onKey?.(key, e, repeat),
      onKeyUp: (key) => latest.current.onKeyUp?.(key),
      onEscape: () => latest.current.onEscape?.() ?? false,
    });
    return () => setBriefKeys(null);
  }, [setBriefKeys]);
}

/** What every brief is given: the item, and what its frame needs. */
export interface BriefProps {
  item: AttentionItem;
  frame: { index: number; total: number; accountName: string | null; now: number; readOnly: boolean };
}

/** An error as one sentence. */
export const errorText = (e: unknown): string => (e instanceof Error ? e.message : String(e));
