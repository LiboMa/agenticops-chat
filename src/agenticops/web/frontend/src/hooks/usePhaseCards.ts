import { useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import type { PhaseView } from "@/lib/issuePhases";
import { openableCards, seedOpenCards, toggledCardHash } from "@/lib/phaseCards";
import { parseHash } from "@/lib/workitemRoutes";

export interface PhaseCards<Id extends string> {
  isOpen: (id: Id) => boolean;
  openCard: (id: Id) => void;
  toggleCard: (id: Id, open: boolean) => void;
  openable: Id[];
  allOpen: boolean;
  toggleAll: () => void;            // expand every reachable card, or collapse them all when they all are open
  activityOpen: boolean;
  setActivityOpen: (open: boolean) => void;
  scrollTo: (id: string, focus?: boolean) => void;
}

/**
 * The phase cards of a work-item page and the URL hash that opens one. Every card is controlled: the open set is
 * re-seeded (`seedOpenCards`) whenever `seedKey` moves, so a poll landing on a new phase opens its card. A hash opens
 * the card (or the activity) it names and scrolls to it; a hash a card header wrote opens it without scrolling.
 * `phases` is null until the work item has loaded.
 */
export function usePhaseCards<Id extends string>({ ids, hashes, phases, seedKey }: {
  ids: readonly Id[];
  hashes: readonly string[];
  phases: readonly PhaseView<Id>[] | null;
  seedKey: string | null;
}): PhaseCards<Id> {
  const location = useLocation();
  const navigate = useNavigate();
  const target = parseHash(location.hash, hashes);

  const [cards, setCards] = useState<{ key: string | null; open: Set<Id> }>({ key: null, open: new Set() });
  if (phases && cards.key !== seedKey) setCards({ key: seedKey, open: seedOpenCards(phases, ids, target) });
  const openCard = (id: Id) => setCards((c) => ({ ...c, open: new Set(c.open).add(id) }));
  const [activityOpen, setActivityOpen] = useState(true);
  const [scroll, setScroll] = useState<{ id: string; focus?: boolean } | null>(null);
  const selfHash = useRef<string | null>(null); // a hash a card header wrote: open it, do not scroll to it

  const loaded = phases !== null;
  useEffect(() => {
    if (selfHash.current !== null && selfHash.current === location.hash) {
      selfHash.current = null;
      return;
    }
    if (!loaded || !target) return;
    if (target === "activity") setActivityOpen(true);
    else openCard(target as Id);
    setScroll({ id: target });
  }, [location.hash, loaded]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!scroll) return;
    const el = document.getElementById(scroll.id);
    el?.scrollIntoView(scroll.focus ? { behavior: "smooth", block: "center" } : { block: "start" });
    if (scroll.focus) el?.focus();
    setScroll(null);
  }, [scroll]);

  const toggleCard = (id: Id, open: boolean) => {
    setCards((c) => {
      const next = new Set(c.open);
      if (open) next.add(id);
      else next.delete(id);
      return { ...c, open: next };
    });
    const hash = toggledCardHash(location.hash, id, open);
    if (hash !== location.hash) {
      selfHash.current = hash;
      // keep the entry's state: a case opened from the queue still goes back through history (S4 review m2)
      navigate({ search: location.search, hash }, { replace: true, state: location.state });
    }
  };

  const openable = phases ? openableCards(phases) : [];
  const allOpen = openable.length > 0 && openable.every((x) => cards.open.has(x));
  return {
    isOpen: (id) => cards.open.has(id),
    openCard,
    toggleCard,
    openable,
    allOpen,
    toggleAll: () => setCards((c) => ({ ...c, open: new Set(allOpen ? [] : openable) })),
    activityOpen,
    setActivityOpen,
    scrollTo: (id, focus) => setScroll({ id, focus }),
  };
}
