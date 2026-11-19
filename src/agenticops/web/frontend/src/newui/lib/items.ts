import type { ChangeRequestListItem, HealthIssue } from "@/api/types";
import { ACTIVE_STATUSES } from "@/lib/caseQueue";
import { ISSUE_STATUSES } from "@/lib/issueStatus";
import { CHANGE_STATUSES, CHANGE_TERMINAL_STATUSES } from "@/lib/plans";
import { changeRow, issueRow } from "@/lib/workItems";

/** «所有事项» (round 3, N18): every issue and every change request, in any state — the table NewUI opens where the
 *  classic interface had the issue list. Everything the table shows is the server's: the filters, the search and
 *  the order are applied there (GET /api/health-issues, GET /api/changes), the count is the answer's `total`, and
 *  who a row waits on is the row's own `waiting_on`. The choice lives in the address. */
export type ItemKind = "issue" | "change";
export type ItemGroup = "open" | "closed" | "all";
export type ItemSort = "newest" | "oldest" | "severity";

export interface ItemsQuery {
  kind: ItemKind;
  /** not closed (the default) · closed · everything */
  group: ItemGroup;
  /** one exact status of the kind; wins over the group */
  status: string | null;
  /** issues only */
  severity: string | null;
  q: string;
  sort: ItemSort;
}

export const PAGE = 50;
const SEVERITIES = ["critical", "high", "medium", "low"];
const CLOSED_ISSUE = ["resolved", "dismissed"];
const OPEN_CHANGE = CHANGE_STATUSES.filter((s) => !CHANGE_TERMINAL_STATUSES.has(s));
const CLOSED_CHANGE = CHANGE_STATUSES.filter((s) => CHANGE_TERMINAL_STATUSES.has(s));

/** The statuses a kind has (for the status select). */
export const statusesOf = (kind: ItemKind): readonly string[] => (kind === "issue" ? ISSUE_STATUSES : CHANGE_STATUSES);
export const SEVERITY_CHOICES: readonly string[] = SEVERITIES;
export const sortsOf = (kind: ItemKind): ItemSort[] => (kind === "issue" ? ["newest", "oldest", "severity"] : ["newest", "oldest"]);

const DEFAULTS: ItemsQuery = { kind: "issue", group: "open", status: null, severity: null, q: "", sort: "newest" };

/** The choice the address holds. A value it does not know — or one that belongs to the other kind — is left out. */
export function itemsQuery(params: URLSearchParams): ItemsQuery {
  const kind: ItemKind = params.get("kind") === "change" ? "change" : "issue";
  const st = params.get("st"), status = params.get("status"), sev = params.get("sev"), sort = params.get("sort");
  return {
    kind,
    group: st === "closed" || st === "all" ? st : "open",
    status: status && statusesOf(kind).includes(status) ? status : null,
    severity: kind === "issue" && sev && SEVERITIES.includes(sev) ? sev : null,
    q: (params.get("q") ?? "").trim().slice(0, 200),
    sort: sort && (sortsOf(kind) as string[]).includes(sort) ? (sort as ItemSort) : "newest",
  };
}

/** The address of a choice; what is the default is not written. */
export function itemsSearch(q: ItemsQuery): string {
  const out = new URLSearchParams();
  if (q.kind !== DEFAULTS.kind) out.set("kind", q.kind);
  if (q.group !== DEFAULTS.group) out.set("st", q.group);
  if (q.status) out.set("status", q.status);
  if (q.severity) out.set("sev", q.severity);
  if (q.q) out.set("q", q.q);
  if (q.sort !== DEFAULTS.sort) out.set("sort", q.sort);
  const s = out.toString();
  return s ? `?${s}` : "";
}

const statusList = (q: ItemsQuery): string | null => {
  if (q.status) return q.status;
  if (q.group === "all") return null;
  if (q.kind === "issue") return (q.group === "open" ? ACTIVE_STATUSES : CLOSED_ISSUE).join(",");
  return (q.group === "open" ? OPEN_CHANGE : CLOSED_CHANGE).join(",");
};

function request(path: string, q: ItemsQuery, accountId: number | null, offset: number): string {
  const out = new URLSearchParams();
  const status = statusList(q);
  if (status) out.set("status", status);
  if (q.kind === "issue" && q.severity) out.set("severity", q.severity);
  if (q.q) out.set("q", q.q);
  out.set("sort", q.kind === "change" && q.sort === "severity" ? "newest" : q.sort);
  if (accountId != null) out.set("account_id", String(accountId));
  out.set("limit", String(PAGE));
  out.set("offset", String(offset));
  return `${path}?${out.toString()}`;
}

/** GET /api/health-issues for a page of the table. */
export const issuesRequest = (q: ItemsQuery, accountId: number | null, offset: number): string => request("/health-issues", q, accountId, offset);
/** GET /api/changes for a page of the table. */
export const changesRequest = (q: ItemsQuery, accountId: number | null, offset: number): string => request("/changes", q, accountId, offset);

/** Where the next page starts, or undefined when everything is loaded — or when the last page came back empty
 *  (rows can leave while a person pages; the total of an earlier answer must not keep «load more» alive). */
export function nextOffset(loaded: number, total: number, lastPage: number = 1): number | undefined {
  return lastPage > 0 && loaded < total ? loaded : undefined;
}

export interface ItemRow {
  /** "I12" / "C3": the item's story is /app/new/story/<item> */
  item: string;
  ref: string;
  title: string;
  sub: string | null;
  /** keys of the classic locale files — the product's own words for a status and for who a thing waits on */
  statusKey: string;
  waitKey: string | null;
  /** severity (issue) or risk level (change); null = not rated */
  level: string | null;
  /** since when — only when it waits on a person */
  waitSince: string | null;
  account: string | null;
  time: string | null;
  closed: boolean;
}

/** The rows of the loaded pages, in the server's order; a row that came twice (it moved between two pages while
 *  the person paged) is listed once. */
export function itemRows(kind: "issue", loaded: HealthIssue[]): ItemRow[];
export function itemRows(kind: "change", loaded: ChangeRequestListItem[]): ItemRow[];
export function itemRows(kind: ItemKind, loaded: (HealthIssue | ChangeRequestListItem)[]): ItemRow[] {
  const seen = new Set<number>();
  const out: ItemRow[] = [];
  for (const x of loaded) {
    if (seen.has(x.id)) continue;
    seen.add(x.id);
    const r = kind === "issue" ? issueRow(x as HealthIssue) : changeRow(x as ChangeRequestListItem);
    out.push({ item: r.key, ref: r.ref, title: r.title, sub: r.subtitle,
               statusKey: r.statusKey, waitKey: r.waitKey?.startsWith("workitem.wait.") ? r.waitKey : null,
               level: r.level, waitSince: r.waitSince, account: r.account, time: r.time, closed: r.emphasis === "closed" });
  }
  return out;
}

/** What the search box shows once the address has its text: what was typed, as long as the address says the same
 *  thing trimmed — the address holds the trimmed text, and writing that back took the space off «ssh », so the next
 *  word ran on («sshopen»; N27, review). An address that says something else (Back, a link, a cleared filter) wins. */
export function boxAfterAddress(typed: string, addressQ: string): string {
  return typed.trim() === addressQ ? typed : addressQ;
}
