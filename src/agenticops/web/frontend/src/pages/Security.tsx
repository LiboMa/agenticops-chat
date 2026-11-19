import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  CartesianGrid, Legend, Line, LineChart, PolarAngleAxis, PolarGrid, PolarRadiusAxis, Radar, RadarChart,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { Card, CardHeader, CardBody } from "@/components/ui/Card";
import { QueryState } from "@/components/ui/QueryState";
import { StatusText, type StatusTone } from "@/components/ui/StatusText";
import { useAccountScope, useScopedAccountId } from "@/components/layout/AccountScope";
import { reachView } from "@/lib/reachability";
import { moduleStatus, type QueryLike } from "@/lib/queryState";
import { formatShortDate, utcDayKey } from "@/lib/formatDate";
import {
  REACH_CHOICES, SEVERITY_CHOICES, TIER_TONE, TREND_RANGES, cardView, findingsQuery, findingsSearch, pageInfo,
  radarAccount, radarRows, trendChart, trendDays, type FindingsQuery, type TrendChart,
} from "@/lib/security";
import { useLocale } from "@/i18n/LocaleContext";
import { useTheme } from "@/hooks/useTheme";
import {
  useAttackPaths, useSecurityFindings, useSecurityRecommendations,
  useSecuritySummary, useSecurityTrend,
} from "@/hooks/useSecurity";
import type { SecurityAccountScore, SecurityFindingItem } from "@/api/types";

const SEV_TONE: Record<string, StatusTone> = { critical: "danger", high: "danger", medium: "warn", low: "info" };
// the dataviz reference palette's first slots, one step per mode (components/chat/rich/ChartBlock)
const SERIES = { light: ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"], dark: ["#3987e5", "#d95926", "#199e70", "#c98500"] };
const INK = "hsl(var(--muted-foreground))";
const GRID = "hsl(var(--border))";
const SURFACE = "hsl(var(--card))";
const FIELD = "h-9 rounded-md border border-border bg-background px-2 text-[16px] sm:text-sm";   // 16 px on a phone: iOS zooms into a smaller control
const noItems = (d: unknown[]) => d.length === 0;

type T = (key: string) => string;
const fill = (text: string, vars: Record<string, string | number>) =>
  Object.entries(vars).reduce((s, [k, v]) => s.replace(`{${k}}`, String(v)), text);

/** A module's own word about its data, in its corner: «data fetched» or «update failed». */
function ModuleState({ query, t }: { query: QueryLike; t: T }) {
  const s = moduleStatus(query);
  return (
    <StatusText tone={s === "failed" ? "danger" : s === "fetched" ? "ok" : "neutral"} className="text-xs font-normal">
      {t(`security.module.${s}`)}
    </StatusText>
  );
}

function Errors({ errors, t }: { errors: { source: string; error: string }[]; t: T }) {
  if (errors.length === 0) return null;
  return (
    <ul className="mt-1 space-y-0.5 text-xs text-muted-foreground">
      {errors.map((e) => (
        <li key={e.source} className="[overflow-wrap:anywhere]">{t(`security.source.${e.source}`)}: <span className="font-mono">{e.error}</span></li>
      ))}
    </ul>
  );
}

function AccountCard({ a, t }: { a: SecurityAccountScore; t: T }) {
  const view = cardView(a);
  return (
    <Card>
      <CardBody>
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-medium [overflow-wrap:anywhere]">{a.account_name}</span>
          {a.partition && <span className="rounded border border-border px-1.5 py-0.5 text-xs text-muted-foreground">{t(`security.partition.${a.partition}`)}</span>}
        </div>
        {view.score === null ? (
          <div className="mt-2">
            <StatusText tone="danger" className="text-lg font-medium">{t("security.unscored")}</StatusText>
            <div className="mt-1 text-xs text-muted-foreground">{t("security.unscored.why")}</div>
          </div>
        ) : (
          <div className="mt-2 flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <span className="text-3xl font-light font-mono">{view.score}<span className="text-sm text-muted-foreground"> / 100</span></span>
            {view.tier && <StatusText tone={TIER_TONE[view.tier]} className="text-sm">{t(`security.tier.${view.tier}`)}</StatusText>}
          </div>
        )}
        {view.state === "partial" && (
          <div className="mt-1 text-xs">
            <StatusText tone="warn">{t("security.partial")}</StatusText>
            <span className="text-muted-foreground"> · {t("security.partial.why")}</span>
          </div>
        )}
        <Errors errors={view.errors} t={t} />
        <div className="mt-2 text-xs text-muted-foreground">
          {fill(t("security.cardCounts"), { reachable: a.reachable_paths, open: a.open_findings })}
        </div>
        <div className="mt-0.5 text-xs text-muted-foreground">{fill(t("security.scoredAt"), { time: formatShortDate(a.created_at) })}</div>
      </CardBody>
    </Card>
  );
}

function TrendPlot({ chart, t }: { chart: TrendChart; t: T }) {
  const { theme } = useTheme();
  const palette = theme === "dark" ? SERIES.dark : SERIES.light;
  const drawn = chart.series.filter((s) => s.points > 0);
  return (
    <div className="h-64">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={chart.rows} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
          <CartesianGrid vertical={false} stroke={GRID} strokeDasharray="3 3" />
          <XAxis dataKey="day" tickFormatter={(d: string) => d.slice(5)} minTickGap={24}
                 tick={{ fill: INK, fontSize: 12 }} tickLine={false} axisLine={{ stroke: GRID }} />
          <YAxis domain={[0, 100]} ticks={[0, 25, 50, 75, 100]} width={36} tick={{ fill: INK, fontSize: 12 }} tickLine={false} axisLine={false} />
          <Tooltip
            labelFormatter={(d) => `${String(d)} UTC`}
            formatter={(value, name, item) => {
              const day = (item?.payload as { day?: string } | undefined)?.day ?? "";
              const partial = (chart.partial[day] ?? []).includes(String(name));
              return [`${typeof value === "number" ? value.toFixed(1) : "—"}${partial ? t("security.trend.partialMark") : ""}`, name];
            }}
            contentStyle={{ background: SURFACE, border: `1px solid ${GRID}`, borderRadius: 8, fontSize: 12 }}
            labelStyle={{ color: "hsl(var(--foreground))" }} itemStyle={{ color: "hsl(var(--foreground))" }} />
          {drawn.length > 1 && (
            <Legend wrapperStyle={{ fontSize: 12 }} iconType="plainline"
                    formatter={(v) => <span style={{ color: "hsl(var(--foreground))" }}>{String(v)}</span>} />
          )}
          {chart.series.map((s, k) => s.points > 0 && (
            <Line key={s.key} dataKey={s.key} name={s.name} type="linear" stroke={palette[k % palette.length]} strokeWidth={2}
                  strokeDasharray={s.dash} connectNulls={false} dot={{ r: 2.5 }} activeDot={{ r: 4 }} isAnimationActive={false} />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

function FindingRow({ f, t }: { f: SecurityFindingItem; t: T }) {
  const reach = reachView(f.reachability);
  const where = [f.resource_type, f.account_name, f.region].filter(Boolean).join(" · ");
  return (
    <li className="flex flex-wrap items-start gap-x-3 gap-y-1 border-b border-border/50 py-2.5 text-sm last:border-0">
      <StatusText tone={SEV_TONE[f.severity] ?? "neutral"} className="w-20 shrink-0 text-xs">
        {SEV_TONE[f.severity] ? t(`severity.${f.severity}`) : f.severity}
      </StatusText>
      <div className="min-w-0 flex-1 basis-56">
        <div className="[overflow-wrap:anywhere]">{f.title}</div>
        <div className="mt-0.5 text-xs text-muted-foreground [overflow-wrap:anywhere]">
          {where || f.resource_id}{f.last_seen && <> · {fill(t("security.lastSeen"), { time: formatShortDate(f.last_seen) })}</>}
        </div>
      </div>
      {reach && <StatusText tone={reach.tone} className="text-xs">{reach.key ? t(reach.key) : reach.text}</StatusText>}
      <span className="text-xs text-muted-foreground">{t(`issues.status.${f.status}`)}</span>
      <Link to={`/app/issues/${f.id}`} className="whitespace-nowrap text-xs font-medium text-primary hover:underline"
            aria-label={`${t("security.viewIssue")} ${f.issue_ref}`}>
        {t("security.viewIssue")}
      </Link>
    </li>
  );
}

/** Security (MVP-2.9.0 N20 — the 2.8.0 spec's S3): every module follows the top bar's account; an account's card
 *  counts its own findings; an account nobody could read is «not scored», never 100; one trend line per account;
 *  the findings list is filtered, counted and paged by the server and each row opens its issue. Every module states
 *  its own loading / failed / empty / stale, and one failed module never hides the others. */
export default function Security() {
  const { t } = useLocale();
  const accountId = useScopedAccountId();
  const { accountName } = useAccountScope();
  const [params, setParams] = useSearchParams();
  const days = trendDays(params);
  const query = findingsQuery(params);
  const [picked, setPicked] = useState<string | null>(null);
  const [draft, setDraft] = useState(query.q);
  useEffect(() => setDraft(query.q), [query.q]);

  const summary = useSecuritySummary(accountId);
  const trend = useSecurityTrend(days, accountId);
  const findings = useSecurityFindings(query, accountId);
  const recs = useSecurityRecommendations("open", accountId);
  const paths = useAttackPaths(accountId);
  const all = [summary, trend, findings, recs, paths];
  const refreshing = all.some((q) => q.isFetching);
  const refreshAll = () => all.forEach((q) => void q.refetch());

  const setFilters = (next: FindingsQuery) => setParams(findingsSearch(params, next), { replace: true });
  const filter = (patch: Partial<FindingsQuery>) => setFilters({ ...query, page: 1, ...patch });
  const setDays = (n: number) => {
    const next = new URLSearchParams(params);
    if (n === 30) next.delete("days"); else next.set("days", String(n));
    setParams(next, { replace: true });
  };
  const filtered = Boolean(query.severity || query.reach || query.q || query.status !== "open");

  const reach = (r: unknown) => {
    const v = reachView(r);
    return v && <StatusText tone={v.tone} className="text-xs">{v.key ? t(v.key) : v.text}</StatusText>;
  };
  const scoped = accountId !== undefined;
  const noSnapshot = scoped ? t("security.noSnapshot.account") : t("security.noSnapshot");

  return (
    <div className="p-6 space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-medium">{t("nav.security")}</h1>
          <p className="mt-0.5 text-sm text-muted-foreground [overflow-wrap:anywhere]">
            {scoped ? fill(t("security.scope.one"), { name: accountName ?? `#${accountId}` }) : t("security.scope.all")}
          </p>
        </div>
        <button type="button" onClick={refreshAll} disabled={refreshing}
                className="inline-flex min-h-11 items-center gap-2 rounded-lg border border-border bg-background px-3 py-1.5 text-sm hover:bg-accent disabled:opacity-60 sm:min-h-0">
          <svg className={`h-4 w-4 ${refreshing ? "animate-spin motion-reduce:animate-none" : ""}`} fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden>
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
          </svg>
          {t("security.refresh")}
        </button>
      </div>

      {/* account cards */}
      <section aria-labelledby="sec-accounts">
        <div className="mb-2 flex items-center justify-between gap-3">
          <h2 id="sec-accounts" className="text-sm font-medium">{t("security.accounts")}</h2>
          <ModuleState query={summary} t={t} />
        </div>
        <QueryState query={summary} isEmpty={(d) => d.accounts.length === 0} emptyText={noSnapshot}
                    onRetry={() => void summary.refetch()}>
          {(data) => (
            <>
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
                {data.accounts.map((a) => <AccountCard key={a.account_name} a={a} t={t} />)}
              </div>
              {!scoped && data.unassigned_open_findings > 0 && (
                <p className="mt-2 text-xs text-muted-foreground">{fill(t("security.unassigned"), { n: data.unassigned_open_findings })}</p>
              )}
            </>
          )}
        </QueryState>
      </section>

      {/* trend + radar */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader className="flex-wrap gap-2">
            <span>{t("security.trend")}</span>
            <div className="flex flex-wrap items-center gap-3">
              <div role="group" aria-label={t("security.trend")} className="inline-flex overflow-hidden rounded-md border border-border text-xs">
                {TREND_RANGES.map((n) => (
                  <button key={n} type="button" aria-pressed={n === days} onClick={() => setDays(n)}
                          className={`px-2.5 py-1 ${n === days ? "bg-primary text-primary-foreground" : "hover:bg-accent"}`}>
                    {fill(t("security.trend.range"), { n })}
                  </button>
                ))}
              </div>
              <ModuleState query={trend} t={t} />
            </div>
          </CardHeader>
          <CardBody className="min-h-64">
            <QueryState query={trend} isEmpty={(d) => d.accounts.every((a) => a.points.length === 0)}
                        emptyText={fill(t("security.noTrend"), { n: days })} onRetry={() => void trend.refetch()}>
              {(data) => {
                const chart = trendChart(data, utcDayKey(new Date()));
                return (
                  <>
                    <TrendPlot chart={chart} t={t} />
                    <p className="mt-2 text-xs text-muted-foreground">{t("security.trend.note")}</p>
                    {chart.series.filter((s) => s.points === 0).map((s) => (
                      <p key={s.key} className="mt-1 text-xs text-status-warn [overflow-wrap:anywhere]">{fill(t("security.trend.noPoints"), { name: s.name })}</p>
                    ))}
                  </>
                );
              }}
            </QueryState>
          </CardBody>
        </Card>
        <Card>
          <CardHeader className="flex-wrap gap-2">
            <span>{t("security.categories")}</span>
            <ModuleState query={summary} t={t} />
          </CardHeader>
          <CardBody className="min-h-64">
            <QueryState query={summary} isEmpty={(d) => d.accounts.length === 0} emptyText={noSnapshot}
                        onRetry={() => void summary.refetch()}>
              {(data) => {
                const a = radarAccount(data.accounts, accountId ?? null, picked);
                if (!a) return <p className="text-sm text-muted-foreground">{noSnapshot}</p>;
                const rows = radarRows(a);
                const drawable = rows.some((r) => r.collected);
                return (
                  <>
                    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
                      {!scoped && data.accounts.length > 1 ? (
                        <label className="flex items-center gap-2">
                          <span className="text-muted-foreground">{t("security.radar.account")}</span>
                          <select className={FIELD} value={a.account_name} onChange={(e) => setPicked(e.target.value)}>
                            {data.accounts.map((x) => <option key={x.account_name} value={x.account_name}>{x.account_name}</option>)}
                          </select>
                        </label>
                      ) : (
                        <span className="font-medium [overflow-wrap:anywhere]">{a.account_name}</span>
                      )}
                      <span className="text-xs text-muted-foreground">{fill(t("security.radar.updated"), { time: formatShortDate(a.created_at) })}</span>
                    </div>
                    {drawable ? (
                      <div className="h-56">
                        <ResponsiveContainer width="100%" height="100%">
                          <RadarChart outerRadius="62%" data={rows.map((r) => ({ ...r, label: r.collected ? r.category : fill(t("security.radar.notCollected"), { category: r.category }) }))}>
                            <PolarGrid stroke={GRID} />
                            <PolarAngleAxis dataKey="label" tick={{ fill: INK, fontSize: 12 }} />
                            <PolarRadiusAxis domain={[0, 100]} tick={false} axisLine={false} />
                            <Radar dataKey="score" stroke="hsl(var(--primary))" fill="hsl(var(--primary))" fillOpacity={0.3} isAnimationActive={false} />
                          </RadarChart>
                        </ResponsiveContainer>
                      </div>
                    ) : (
                      <p className="mt-4 text-sm"><StatusText tone="danger">{t("security.unscored")}</StatusText> <span className="text-muted-foreground">· {t("security.unscored.why")}</span></p>
                    )}
                    <ul className="mt-1 flex flex-wrap gap-x-4 gap-y-0.5 text-xs text-muted-foreground">
                      {rows.map((r) => <li key={r.category}>{r.category}: {r.collected ? r.score.toFixed(1) : t("security.radar.none")}</li>)}
                    </ul>
                    <p className="mt-2 text-xs text-muted-foreground">{t("security.radar.meaning")}</p>
                  </>
                );
              }}
            </QueryState>
          </CardBody>
        </Card>
      </div>

      {/* findings */}
      <Card>
        <CardHeader className="flex-wrap gap-2">
          <span>{t("security.findings")}</span>
          <ModuleState query={findings} t={t} />
        </CardHeader>
        <CardBody>
          <form className="mb-3 flex flex-wrap items-center gap-2" onSubmit={(e) => { e.preventDefault(); filter({ q: draft }); }}>
            <select aria-label={t("security.filter.severity")} className={FIELD} value={query.severity} onChange={(e) => filter({ severity: e.target.value })}>
              <option value="">{t("security.filter.anySeverity")}</option>
              {SEVERITY_CHOICES.map((s) => <option key={s} value={s}>{t(`severity.${s}`)}</option>)}
            </select>
            <select aria-label={t("security.filter.status")} className={FIELD} value={query.status} onChange={(e) => filter({ status: e.target.value === "all" ? "all" : "open" })}>
              <option value="open">{t("security.filter.open")}</option>
              <option value="all">{t("security.filter.all")}</option>
            </select>
            <select aria-label={t("security.filter.reach")} className={FIELD} value={query.reach} onChange={(e) => filter({ reach: e.target.value })}>
              <option value="">{t("security.filter.anyReach")}</option>
              {REACH_CHOICES.map((r) => <option key={r} value={r}>{t(`security.reach.${r}`)}</option>)}
            </select>
            <input type="search" aria-label={t("security.filter.searchLabel")} placeholder={t("security.filter.search")} maxLength={200}
                   className={`${FIELD} min-w-0 flex-1 basis-40`} value={draft} onChange={(e) => setDraft(e.target.value)}
                   onBlur={() => { if (draft.trim() !== query.q) filter({ q: draft }); }} />
          </form>
          <QueryState query={findings} isEmpty={(d) => d.items.length === 0}
                      emptyText={filtered ? t("security.noFindings.filtered") : t("security.noFindings")} onRetry={() => void findings.refetch()}>
            {(data) => {
              const info = pageInfo(data.total, query.page);
              return (
                <>
                  <ul className={findings.isPlaceholderData ? "opacity-60" : ""}>
                    {data.items.map((f) => <FindingRow key={f.id} f={f} t={t} />)}
                  </ul>
                  <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
                    <span role="status">{fill(t("security.showing"), { from: info.from, to: info.to, total: data.total })}</span>
                    <div className="flex items-center gap-2">
                      <button type="button" disabled={info.page <= 1} onClick={() => setFilters({ ...query, page: info.page - 1 })}
                              className="min-h-11 rounded-md border border-border px-3 hover:bg-accent disabled:opacity-50 sm:min-h-8">{t("security.prev")}</button>
                      <span>{fill(t("security.page"), { page: info.page, pages: info.pages })}</span>
                      <button type="button" disabled={info.page >= info.pages} onClick={() => setFilters({ ...query, page: info.page + 1 })}
                              className="min-h-11 rounded-md border border-border px-3 hover:bg-accent disabled:opacity-50 sm:min-h-8">{t("security.next")}</button>
                    </div>
                  </div>
                </>
              );
            }}
          </QueryState>
        </CardBody>
      </Card>

      {/* recommendations */}
      <Card>
        <CardHeader className="flex-wrap gap-2">
          <span>{t("security.recommendations")}</span>
          <ModuleState query={recs} t={t} />
        </CardHeader>
        <CardBody>
          <QueryState query={recs} isEmpty={noItems} emptyText={t("security.noRecommendations")} onRetry={() => void recs.refetch()}>
            {(data) => data.map((r) => (
              <div key={r.id} className="py-1.5 text-sm border-b border-border/50 last:border-0">
                <div className="flex flex-wrap items-center gap-2">
                  <StatusText tone={SEV_TONE[r.severity] ?? "neutral"} className="text-xs">
                    {SEV_TONE[r.severity] ? t(`severity.${r.severity}`) : r.severity}
                  </StatusText>
                  <span className="font-medium [overflow-wrap:anywhere]">{r.title}</span>
                  <span className="text-xs text-muted-foreground">
                    {!scoped && <>{r.account_name} · </>}{r.critic_verdict} · {(r.confidence * 100).toFixed(0)}%
                  </span>
                </div>
                <div className="text-xs text-muted-foreground [overflow-wrap:anywhere]">{r.detail}</div>
              </div>
            ))}
          </QueryState>
        </CardBody>
      </Card>

      {/* attack paths */}
      <Card>
        <CardHeader className="flex-wrap gap-2">
          <span>{t("security.paths")}</span>
          <ModuleState query={paths} t={t} />
        </CardHeader>
        <CardBody>
          <QueryState query={paths} isEmpty={noItems} emptyText={t("security.noPaths")} onRetry={() => void paths.refetch()}>
            {(data) => data.map((p, i) => (
              <div key={i} className="flex flex-wrap items-center gap-2 py-1.5 text-sm font-mono border-b border-border/50 last:border-0">
                {reach(p.reachability)}
                <span className="min-w-0 [overflow-wrap:anywhere]">{(p.path ?? []).join(" → ") || p.resource_id}</span>
                <span className="text-xs text-muted-foreground">:{p.port}</span>
                {!scoped && <span className="font-sans text-xs text-muted-foreground">{p.account_name}</span>}
              </div>
            ))}
          </QueryState>
        </CardBody>
      </Card>
    </div>
  );
}
