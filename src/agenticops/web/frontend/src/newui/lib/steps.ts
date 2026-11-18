/** An agent run's steps as the code recorded them while it worked (GET /api/ui/activity/steps, N10). A step is a
 *  tool call — when it started, when it ended and how —, what the model said between calls, or a note a person sent
 *  the run. Nothing here adds to what the server recorded. */

export interface StepRow {
  id: number;
  kind: "tool" | "say" | "you" | string;
  tool: string | null;
  /** read = a fact the code fetched · act = something the agent did */
  look: "read" | "act" | null;
  tier: string | null;
  /** an executor's command against its plan: step:3 · rollback:1 · pre:1 · post:2 · off */
  plan_ref: string | null;
  summary: string;
  preview: string | null;
  outcome: "ok" | "error" | "refused" | null;
  by: string | null;
  started_at: string | null;
  ended_at: string | null;
  delivered_at: string | null;
}

export interface StepsAnswer {
  run: { key: string; agent: string; item: string; execution_id: number | null; started_at: string | null } | null;
  steps: StepRow[];
  more: boolean;
}

export interface PlanPlace { part: "step" | "rollback" | "pre" | "post" | "off"; n: number | null }

export interface LiveStepVm {
  id: number;
  /** fact = the code fetched it (◆) · act = the agent did it (▸) · say = the model's own words (◇) · you = a person's note */
  mark: "fact" | "act" | "say" | "you";
  /** now = running · done · bad = it failed · refused = a guard cancelled it, it never ran · waiting = a note the
   *  agent has not read yet */
  state: "now" | "done" | "bad" | "refused" | "waiting";
  /** the sentence: a tool's result (empty while it runs), the model's words, the note */
  say: string;
  /** what was run: the tool and its input on one line; null for words */
  cmd: string | null;
  tier: string | null;
  plan: PlanPlace | null;
  by: string | null;
  at: string | null;
}

const PLACE = /^(step|rollback|pre|post):([1-9]\d*)$/;
function place(ref: string | null): PlanPlace | null {
  if (ref === "off") return { part: "off", n: null };
  const m = ref ? PLACE.exec(ref) : null;
  return m ? { part: m[1] as PlanPlace["part"], n: Number(m[2]) } : null;
}

export function stepVm(row: StepRow): LiveStepVm {
  const base = { id: row.id, tier: row.tier, plan: place(row.plan_ref), by: row.by, at: row.started_at };
  if (row.kind === "say") return { ...base, mark: "say", state: "done", say: row.summary, cmd: null };
  if (row.kind === "you") return { ...base, mark: "you", state: row.delivered_at ? "done" : "waiting", say: row.summary, cmd: null };
  const state = row.outcome === "refused" ? "refused" : row.outcome === "error" ? "bad" : row.ended_at ? "done" : "now";
  return { ...base, mark: row.look === "read" ? "fact" : "act", state, say: row.preview ?? "",
           cmd: [row.tool, row.summary].filter(Boolean).join("　") || null };
}

/** The list the page has, with what the server just sent: new steps appended, a step that changed (it ended, a note
 *  was read) replaced. The same array when nothing changed, so nothing re-renders. */
export function mergeSteps(old: StepRow[], incoming: StepRow[]): StepRow[] {
  if (!incoming.length) return old;
  const byId = new Map(old.map((s) => [s.id, s]));
  for (const s of incoming) byId.set(s.id, s);
  return [...byId.values()].sort((a, b) => a.id - b.id);
}

const open = (s: StepRow) => (s.kind === "you" ? !s.delivered_at : !s.ended_at);

/** What to ask for next: everything after this id. A step that has not ended — or a note not yet read — is asked
 *  about again, so its end arrives; with none open, only what is newer than the last step the page has. */
export function nextAfter(steps: StepRow[]): number {
  if (!steps.length) return 0;
  const firstOpen = steps.find(open);
  return firstOpen ? firstOpen.id - 1 : steps[steps.length - 1].id;
}

/** An execution's commands against its plan: how many could change something (`acts` — a command whose tier is not
 *  read-only), how many of those are word for word a command of the plan (`verbatim`), and how many a guard refused.
 *  The executor types its commands itself; this is the text of what it ran, not a judgement of it. */
export function runTally(steps: StepRow[]): { acts: number; verbatim: number; refused: number } {
  const acts = steps.filter((s) => s.kind === "tool" && s.look === "act" && s.tier !== null);
  return { acts: acts.length, verbatim: acts.filter((s) => s.plan_ref !== null && s.plan_ref !== "off").length,
           refused: acts.filter((s) => s.outcome === "refused").length };
}

/** The plan's steps marked from the record: for each step (1-based → index), how the newest command that is word for
 *  word that step's own went — done, running, failed, refused; null = no such command is on record (the executor may
 *  have run it in other words: see runTally). */
export function planMarks(steps: StepRow[], total: number): ("done" | "now" | "bad" | "refused" | null)[] {
  const marks: ("done" | "now" | "bad" | "refused" | null)[] = Array.from({ length: total }, () => null);
  for (const s of steps) {
    const p = place(s.plan_ref);
    if (s.kind !== "tool" || p?.part !== "step" || p.n === null || p.n > total) continue;
    const state = stepVm(s).state;
    marks[p.n - 1] = state === "waiting" ? null : state;
  }
  return marks;
}

/** What stopping a run of this plan could roll back, as its rollback is written (FixPlan.rollback_outlook): the
 *  sentence's key, how many commands can run exactly as written (`n`; for «rewrite»: how many there are) and how
 *  many cannot (`rest`). null = the plan is not known. */
export function rollbackHint(outlook: { steps: number; commands: number; as_written: number } | null | undefined):
    { key: "stop.rollback.none" | "stop.rollback.rewrite" | "stop.rollback.all" | "stop.rollback.some"; n: number; rest: number } | null {
  if (!outlook) return null;
  if (outlook.commands === 0) return { key: "stop.rollback.none", n: 0, rest: 0 };
  if (outlook.as_written === 0) return { key: "stop.rollback.rewrite", n: outlook.commands, rest: 0 };
  const rest = outlook.commands - outlook.as_written;
  return { key: rest ? "stop.rollback.some" : "stop.rollback.all", n: outlook.as_written, rest };
}
