import { describe, expect, it, vi } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import type { AttentionItem } from "@/lib/attention";

/** The two briefs that ask an agent for work — «diagnose again» (RerunBrief) and «write the plan» (GenerateBrief) —
 *  share one body since the review of MVP-2.9.0 (④: `briefs/AgentAskBrief`). What each says and which key asks for
 *  what is pinned here for every reason it serves, rendered on the server with the widgets around it stood in for:
 *  the page reads as it did before the two were merged. */

const asked: string[] = [];
let keys: { onKey: (key: string, e: unknown, repeat: boolean) => boolean } | null = null;

vi.mock("@/newui/i18n", () => ({
  useNfT: () => (key: string, vars?: Record<string, unknown>) => (vars ? `${key}${JSON.stringify(vars)}` : key),
}));
vi.mock("@/newui/decide/BriefFrame", () => ({
  BriefFrame: ({ ask, actions, children }: { ask: string; actions: unknown; children: unknown }) => (
    <section data-ask={ask}><nav>{actions as never}</nav>{children as never}</section>),
}));
vi.mock("@/newui/live/LiveSteps", () => ({
  LiveSteps: ({ of, heading }: { of: unknown; heading: string }) => <div data-steps={JSON.stringify(of)} data-heading={heading} />,
}));
vi.mock("@/newui/lib/time", () => ({ utcStamp: (t: string) => `T(${t})` }));
vi.mock("@/newui/decide/widgets/AgentAtWork", () => ({ AgentAtWork: () => <div data-agent-at-work="" /> }));
vi.mock("@/newui/decide/widgets/Cause", () => ({ Prov: ({ code }: { code?: boolean }) => <i data-prov={code ? "code" : ""} /> }));
vi.mock("@/newui/decide/widgets/CauseSection", () => ({
  CauseSection: ({ heading, children }: { heading: string; children?: unknown }) => <div data-cause={heading}>{children as never}</div>,
  useCause: () => ({ cause: null, rca: { id: 7 } }),
}));
vi.mock("@/newui/decide/briefs/briefContext", () => ({
  useBriefKeys: (k: typeof keys) => { keys = k; },
  useDecide: () => ({ openPeek: () => {} }),
}));
vi.mock("@/newui/decide/briefs/shared", () => ({
  DismissForm: () => <form />,
  useAgentAsk: () => ({ issueId: 12, lane: null, busy: false, error: null, ask: (what: string) => { asked.push(what); },
                        setError: () => {} }),
  VerdictQuote: ({ issueId, rcaId }: { issueId: number; rcaId: number | null }) => <q data-issue={issueId} data-rca={rcaId} />,
}));

const { RerunBrief } = await import("@/newui/decide/briefs/RerunBrief");
const { GenerateBrief } = await import("@/newui/decide/briefs/GenerateBrief");

const item = (reason_detail: string) =>
  ({ id: "I12", ref: "I#12", reason_detail, occurred_at: "2026-11-26T09:00:00Z" }) as unknown as AttentionItem;
const frame = (readOnly = false) => ({ index: 0, total: 1, accountName: null, now: 0, readOnly });

function keysAsk(readOnly: boolean): string[] {
  asked.length = 0;
  for (const k of ["a", "m", "d", " "]) keys?.onKey(k, {}, false);
  return [...asked, readOnly ? "(read-only)" : ""];
}

describe.each([
  ["rerun", RerunBrief, ["rca_missing", "rca_stopped", "reopened", "rca_rejected"]],
  ["generate", GenerateBrief, ["rca_confirmed", "plan_stopped", "rca_ready"]],
] as const)("%s brief", (_name, Brief, reasons) => {
  it.each(reasons)("%s reads as before", (reason) => {
    expect(renderToStaticMarkup(<Brief item={item(reason)} frame={frame()} />)).toMatchSnapshot();
    expect(keysAsk(false)).toMatchSnapshot();
    renderToStaticMarkup(<Brief item={item(reason)} frame={frame(true)} />);
    expect(keysAsk(true)).toMatchSnapshot();
  });
});
