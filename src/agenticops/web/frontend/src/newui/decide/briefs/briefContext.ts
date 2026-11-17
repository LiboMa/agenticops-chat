import { createContext, useCallback, useContext, useEffect, useRef } from "react";
import type { AttentionItem } from "@/lib/attention";
import { useNfT } from "../../i18n";
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
  /** a decision on `item` went through: say it, hide the item, and show what is next — only if the page still
   *  shows that item (the answer may arrive after the person moved on: lib/queue.settle) */
  done: (item: AttentionItem, message: string) => void;
  /** a decision on `item` did not go through. The brief shows it on its own line while it is on the page; this
   *  says it in a toast once it is not — otherwise nothing would say the decision did not happen */
  failed: (item: AttentionItem, message: string) => void;
  /** open the evidence panel on one of these */
  openPeek: (evidence: EvidenceVm[], index: number) => void;
}

export const DecideContext = createContext<DecideApi>({ setBriefKeys: () => {}, done: () => {}, failed: () => {}, openPeek: () => {} });
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

/** One decision request for `item`, settled through the lens: on success the toast and the next item, on failure
 *  the error — returned for the brief's own line, and said by the lens when the brief is no longer on the page. */
export function useDecision(item: AttentionItem) {
  const { done, failed } = useDecide();
  const t = useNfT();
  return useCallback(async <T,>(request: () => Promise<T>, toast: string | ((result: T) => string),
                               words: (e: unknown) => string = (e) => t("err.failed", { msg: errorText(e) })): Promise<string | null> => {
    let result: T;
    try { result = await request(); } catch (e) { const text = words(e); failed(item, text); return text; }
    done(item, typeof toast === "string" ? toast : toast(result));
    return null;
  }, [done, failed, item, t]);
}

