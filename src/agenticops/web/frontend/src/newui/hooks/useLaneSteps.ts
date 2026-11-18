import { useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import { mergeSteps, nextAfter, type StepRow, type StepsAnswer } from "../lib/steps";

/** Which run's steps: an agent's run on an item — named by its run record (`execution`), or the one in flight since
 *  `since`, or the one that began before `before` (the run that left a result). */
export interface StepsOf {
  item: string;
  agent: "rca" | "sre" | "executor";
  execution?: number | null;
  since?: string | null;
  before?: string | null;
}

export interface StepsState { run: StepsAnswer["run"]; steps: StepRow[] }

const stepsKey = (of: StepsOf | null) =>
  ["ui-activity-steps", of?.item ?? null, of?.agent ?? null, of?.execution ?? null, of?.since ?? null, of?.before ?? null];

/** The run whose steps the page has for `of` (its key) — null when it has none yet. What a note is addressed to:
 *  the run the person was reading, not whichever run is on the lane when the note arrives. */
export function shownRunKey(qc: QueryClient, of: StepsOf): string | null {
  return qc.getQueryData<StepsState>(stepsKey(of))?.run?.key ?? null;
}

const PAGES_MAX = 10;        // 200 steps a page: an ended run is read whole, up to 2,000 steps

/** One run's recorded steps (GET /api/ui/activity/steps, N10). While `live`, asked again every three seconds — only
 *  for what the page does not have yet (lib/steps.nextAfter), merged into what it has. Another run than the one on
 *  the page (the lane began a new run) starts the list over. `enabled` false = not asked at all (a closed panel). */
export function useLaneSteps(of: StepsOf | null, live: boolean, enabled = true) {
  const qc = useQueryClient();
  const key = stepsKey(of);
  return useQuery({
    queryKey: key,
    enabled: !!of && enabled,
    refetchInterval: live ? 3_000 : false,
    staleTime: live ? 0 : 60_000,
    queryFn: async (): Promise<StepsState> => {
      if (!of) return { run: null, steps: [] };
      const q = new URLSearchParams({ item: of.item, agent: of.agent });
      if (of.execution) q.set("execution", String(of.execution));
      else {
        if (of.since) q.set("since", of.since);
        if (of.before) q.set("before", of.before);
      }
      const ask = (after: number) => apiFetch<StepsAnswer>(`/ui/activity/steps?${q.toString()}&after=${after}`);
      const had = qc.getQueryData<StepsState>(key);
      let answer = await ask(had?.run ? nextAfter(had.steps) : 0);
      if (!answer.run) return { run: null, steps: [] };
      let steps = had?.run && had.run.key === answer.run.key ? mergeSteps(had.steps, answer.steps) : null;
      if (steps === null) {                                  // not the run the page has: its steps from the first one
        if (had?.run) answer = await ask(0);
        steps = answer.steps;
      }
      for (let page = 1; answer.more && page < PAGES_MAX && answer.run; page++) {
        answer = await ask(steps[steps.length - 1]?.id ?? 0);
        steps = mergeSteps(steps, answer.steps);
      }
      return { run: answer.run, steps };
    },
  });
}
