import type { SearchResponse, SearchResultItem } from "@/api/types";
import type { AttentionItem } from "@/lib/attention";
import type { Lens } from "./keys";
import { storyPath } from "./story";

/** The command bar: «/» for commands, «@» for things, or just type. It goes to places — the three lenses, an item
 *  that waits on you, anything the search finds, and the classic pages NewUI has no page of its own for yet. It does
 *  not talk to an agent: chat is not part of NewUI, and the bar says where it is instead of pretending. */

export const COMMAND_MAX = 8;

export interface CommandRow {
  id: string;
  label: string;
  hint?: string;
  /** where it goes (with the router state to go with) … */
  to?: string;
  state?: { from: Lens; back: string };
  /** … or what it switches */
  run?: "theme" | "help";
}

export interface CommandCtx {
  t: (key: string) => string;
  /** what waits on the person, as far as it has been read */
  waiting: AttentionItem[];
  /** what GET /api/search answered for `searchText(q)`; undefined = not asked, or not back yet */
  found: SearchResponse | undefined;
  lens: Lens;
  /** the lens address the person is at — where a story opened from the bar goes back to */
  here?: string;
  /** whether this person may open Settings (the classic rule: a read-only account only with `settings_read`) */
  canSettings: boolean;
}

/** The classic pages NewUI links to instead of drawing its own. */
const CLASSIC: readonly [string, string][] = [
  ["chat", "/app/chat"], ["reports", "/app/reports"], ["resources", "/app/resources"], ["schedules", "/app/schedules"],
  ["skills", "/app/skills"], ["security", "/app/security"], ["settings", "/app/settings"],
];

function commands({ t, canSettings }: CommandCtx): CommandRow[] {
  return [
    { id: "go:decide", label: t("cmd.decide"), hint: "1", to: "/app/new/decide" },
    { id: "go:live", label: t("cmd.live"), hint: "2", to: "/app/new/live" },
    { id: "go:world", label: t("cmd.world"), hint: "3", to: "/app/new/world" },
    { id: "do:theme", label: t("cmd.theme"), hint: "T", run: "theme" },
    { id: "do:help", label: t("cmd.keys"), hint: "?", run: "help" },
    // a page the person may not open is not offered: it would only answer «not found»
    ...CLASSIC.filter(([k]) => k !== "settings" || canSettings)
      .map(([k, to]): CommandRow => ({ id: `classic:${k}`, label: t(`cmd.${k}`), hint: t("cmd.classic"), to })),
  ];
}

/** "i#12", "I12", "12" → the number; anything else null. */
const numberOf = (text: string): string | null => /^[ic]?#?\d+$/.test(text) ? text.replace(/^[ic]?#?/, "") : null;

function items(text: string, { t, waiting }: CommandCtx): CommandRow[] {
  const n = numberOf(text), kind = /^[ic]/.test(text) && n !== null ? text[0].toUpperCase() : null;
  return waiting
    .filter((i) => (n !== null ? i.id.slice(1) === n && (kind === null || i.id[0] === kind) : i.title.toLowerCase().includes(text)))
    .map((i) => ({ id: `item:${i.id}`, label: `${i.ref}　${i.title}`, hint: t("cmd.waits"), to: `/app/new/decide/${i.id}` }));
}

function found(ctx: CommandCtx, listed: Set<string>): CommandRow[] {
  const r = ctx.found?.results;
  if (!r) return [];
  const state = { from: ctx.lens, back: ctx.here ?? `/app/new/${ctx.lens}` };
  const row = (x: SearchResultItem): CommandRow | null => {
    const base = { id: `found:${x.entity_type}:${x.id}`, hint: ctx.t(`cmd.kind.${x.entity_type}`) };
    switch (x.entity_type) {
      case "issue": return listed.has(`I${x.id}`) ? null : { ...base, label: `I#${x.id}　${x.title}`, to: storyPath(`I${x.id}`), state };
      case "change_request": return listed.has(`C${x.id}`) ? null : { ...base, label: `C#${x.id}　${x.title}`, to: storyPath(`C${x.id}`), state };
      case "change_plan": return x.parent_id ? { ...base, label: x.title, to: storyPath(`C${x.parent_id}`), state } : null;
      case "resource": return { ...base, label: x.title, to: `/app/new/world?sel=${x.id}` };
      case "fix_plan": return { ...base, label: x.title, to: `/app/plans/${x.id}` };
      case "report": return { ...base, label: x.title, to: `/app/reports/${x.id}` };
      default: return null;
    }
  };
  return [...r.issues, ...(r.change_requests ?? []), ...r.resources, ...r.fix_plans, ...r.reports].map(row).filter((x): x is CommandRow => x !== null);
}

/** The rows for what was typed, the best first: «/…» commands only, «@…» things only, plain text both, nothing
 *  typed the commands. */
export function commandRows(q: string, ctx: CommandCtx, max = COMMAND_MAX): CommandRow[] {
  const raw = q.trim(), sign = raw[0] === "/" || raw[0] === "@" ? raw[0] : "", text = raw.slice(sign.length).trim().toLowerCase();
  const cmds = sign === "@" ? [] : commands(ctx).filter((c) => !text || c.label.toLowerCase().includes(text));
  if (sign === "/" || !text) return cmds.slice(0, max);
  const mine = items(text, ctx);
  return [...cmds, ...mine, ...found(ctx, new Set(mine.map((m) => m.id.slice(5))))].slice(0, max);
}

/** What is sent to the search for what was typed: nothing for a command, nor for a text too short to mean anything. */
export function searchText(q: string): string {
  const raw = q.trim();
  if (raw[0] === "/") return "";
  const text = raw.replace(/^@/, "").trim();
  return text.length < 2 ? "" : text;
}

/** ↑ ↓ in the list: round the ends. */
export function moveRow(length: number, index: number, delta: number): number {
  return length ? (index + delta + length) % length : 0;
}
