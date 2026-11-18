import { createContext, useCallback, useContext, useEffect, useRef } from "react";
import type { AttentionItem } from "@/lib/attention";
import { useNfT } from "../../i18n";
import type { EvidenceVm } from "../../lib/briefs/cause";
import { deferDecision } from "../../lib/pending";
import { useShell } from "../../shell/shellContext";

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
  /** a decision on `item` was made and waits out its undo window (N13): take the item off the list now and show
   *  what is next. → «put it back» (`goBack` = and bring the page back to it) */
  hide: (item: AttentionItem) => (goBack: boolean) => void;
}

export const DecideContext = createContext<DecideApi>({ setBriefKeys: () => {}, done: () => {}, failed: () => {}, openPeek: () => {},
                                                        hide: () => () => {} });
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
  frame: { index: number; total: number; accountName: string | null; now: number; readOnly: boolean; later?: Later };
}

/** «Later» (N14) as the brief's frame shows it: until when the item is put off (null = it is not), and the switch. */
export interface Later { until: string | null; busy: boolean; toggle: () => void }

/** An error as one sentence. */
export const errorText = (e: unknown): string => (e instanceof Error ? e.message : String(e));

/** One decision on `item` (N13: with an undo window). It shows at once — the item leaves the list and the next one
 *  is on the page — and the request is made five seconds later, unless it is taken back first («Z»): then nothing
 *  was ever sent. `what` says the decision in the waiting toast («批准»). When the request goes through, `toast` is
 *  said; when the server refuses it, the item comes back to the list and the refusal is said (`words`) — by then the
 *  brief is gone, so nothing is returned for its own line (always null). */
export function useDecision(item: AttentionItem) {
  const { failed, hide } = useDecide();
  const { defer, notify } = useShell();
  const t = useNfT();
  return useCallback(async <T,>(request: () => Promise<T>, toast: string | ((result: T) => string),
                               words: (e: unknown) => string = (e) => t("err.failed", { msg: errorText(e) }), what?: string): Promise<string | null> => {
    deferDecision({ add: defer }, {
      label: `${item.ref}：${what ?? t("pend.generic")}`,
      hide: () => hide(item),
      request,
      onDone: (result) => notify(typeof toast === "string" ? toast : toast(result)),
      onFailed: (e) => failed(item, words(e)),
    });
    return null;
  }, [defer, notify, failed, hide, item, t]);
}

