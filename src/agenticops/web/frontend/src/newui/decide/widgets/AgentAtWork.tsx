import { useAuth } from "@/hooks/useAuth";
import { useAccountScope } from "@/components/layout/AccountScope";
import { ApiError } from "@/api/client";
import { useActivity } from "../../hooks/useActivity";
import { useNfT, type NfT } from "../../i18n";
import { agentOn, whoText, type ActivityLane } from "../../lib/activity";
import { waitedParts } from "../../lib/queue";
import { errorText } from "../briefs/briefContext";

const KEY: Record<string, string> = { diagnosis: "atwork.rca", plan: "atwork.sre", change_review: "atwork.review" };
const OVERDUE: Record<string, string> = { diagnosis: "atwork.overdue.rca", plan: "atwork.overdue.sre", change_review: "atwork.overdue.review" };

/** The agent at work on this item right now, by the server's own record (GET /api/ui/activity) — so a reload, another
 *  browser or another person sees the same thing, and nobody asks twice. null = nothing in flight. */
export function useAgentOn(item: string): ActivityLane | null {
  const { accountId } = useAccountScope();
  return agentOn(useActivity(accountId).data, item);
}

/** One line above the brief's body: an agent is on it, since when, and who asked. Work that outlived its own time
 *  limit is said as what the record shows — a start and no end — and not as «no need to ask again before it ends»:
 *  most likely nothing is working on it any more. */
export function AgentAtWork({ lane, now }: { lane: ActivityLane | null; now: number }) {
  const t = useNfT();
  const { user } = useAuth();
  if (!lane || !KEY[lane.kind]) return null;
  const w = waitedParts(lane.since, now);
  const ago = !w ? "" : w.unit === "now" ? t("unit.min", { n: 0 }) : t(`unit.${w.unit}`, { n: w.n });
  const by = lane.requested_by ? t("atwork.by", { who: whoText(lane.requested_by, user?.email, t) }) : "";
  if (lane.overdue) return <p className="note err" role="status">{t(OVERDUE[lane.kind], { t: ago })}</p>;
  return <p className="back" role="status">{t(KEY[lane.kind], { t: ago, by })}</p>;
}

/** What to say when asking an agent failed: «one is already on it» has its own sentence. */
export function triggerError(e: unknown, t: NfT): string {
  return e instanceof ApiError && e.code === "agent_run_in_flight" ? t("err.inFlight") : t("err.failed", { msg: errorText(e) });
}
