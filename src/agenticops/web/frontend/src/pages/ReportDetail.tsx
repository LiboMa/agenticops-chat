import { useEffect, useMemo, useState } from "react";
import { useLocation, useNavigate, useParams, Link } from "react-router-dom";
import { useReport } from "@/hooks/useReport";
import { useNotificationChannels } from "@/hooks/useNotifications";
import { useRendering, useRequestTranslation } from "@/hooks/useRendering";
import { useLocale } from "@/i18n/LocaleContext";
import { Badge } from "@/components/ui/Badge";
import { Spinner } from "@/components/ui/Spinner";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import { formatFullDate } from "@/lib/formatDate";
import { renderMarkdown, type Heading } from "@/lib/renderMarkdown";
import { LANGS, canExport, paperState, type Lang } from "@/lib/reportView";
import { coverageView } from "@/lib/reports";
import { StatusText } from "@/components/ui/StatusText";
import { publishableChannels } from "@/lib/publish";
import ShareDialog from "@/components/ShareDialog";
import { ExportDialog } from "@/components/reportview/ExportDialog";
import { PublishDialog } from "@/components/reportview/PublishDialog";
import type { ContentRendering, Report } from "@/api/types";
import { useReadOnly } from "@/hooks/useBootstrap";

const TYPE_COLORS: Record<string, string> = {
  daily: "bg-blue-100 text-blue-700",
  incident: "bg-red-100 text-red-700",
  inventory: "bg-emerald-100 text-emerald-700",
  weekly: "bg-purple-100 text-purple-700",
  newsletter: "bg-amber-100 text-amber-700",
  conversation: "bg-violet-100 text-violet-700",
  anomaly: "bg-orange-100 text-orange-700",
  "security-review": "bg-rose-100 text-rose-700",
};

/** A report as its reader needs it (MVP-2.7.0 S6): one paper, bound to the report's version, in the language the
 *  中文 / English toggle picks (your UI language first) — never the two side by side (owner, 2026-10-08). A language
 *  that is not ready says so and offers the source language; it is never silently replaced by the other. Export,
 *  print and publish use exactly what is shown. */
export default function ReportDetail() {
  const readOnly = useReadOnly();  // a viewer account: no write controls (the server refuses them)
  const { id } = useParams<{ id: string }>();
  const reportId = Number(id);
  const { t, locale } = useLocale();
  const uiLang: Lang = locale === "zh" ? "zh" : "en";
  const { data: report, isLoading, error, refetch } = useReport(reportId);
  const version = report?.content_version ?? 1;
  const zh = useRendering(reportId, report ? version : undefined, "zh");
  const en = useRendering(reportId, report ? version : undefined, "en");
  const renderings: Partial<Record<Lang, ContentRendering>> = { zh: zh.data, en: en.data };
  const [lang, setLang] = useState<Lang>(uiLang);
  useEffect(() => setLang(uiLang), [uiLang]);   // switching the interface language moves the paper too
  const [dialog, setDialog] = useState<"export" | "publish" | "share" | null>(null);
  const { data: channels } = useNotificationChannels();
  const publishable = publishableChannels(channels);
  // The paper's HTML and its outline come from ONE pass over the language on screen (lib/renderMarkdown): what
  // the outline links to is what is shown — and what is exported is that same body.
  const shown = renderings[lang];
  const body = paperState(shown) === "ready" ? shown?.body_markdown ?? "" : null;
  const paper = useMemo(() => {
    if (body === null) return null;
    const headings: Heading[] = [];
    return { html: renderMarkdown(body, { headings }), headings };
  }, [body]);
  const location = useLocation();
  const navigate = useNavigate();
  const goTo = (id: string) => {
    const calm = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    document.getElementById(id)?.scrollIntoView({ behavior: calm ? "auto" : "smooth", block: "start" });
    navigate({ search: location.search, hash: `#${id}` }, { replace: true, state: location.state });
  };
  useEffect(() => {      // a link that names a section opens on it, once the paper is on the page
    const id = decodeURIComponent(location.hash.slice(1));
    if (id && paper) document.getElementById(id)?.scrollIntoView({ block: "start" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [paper]);

  if (isLoading) return <Spinner label={t("common.loading")} />;
  if (error) return <ErrorBanner message={error.message} onRetry={() => refetch()} actionLabel={t("common.retry")} />;
  if (!report) return null;

  const exportable = canExport(lang, renderings);
  const coverage = coverageView(report.coverage);
  const outline = paper?.headings ?? [];
  const source = (report.source_language ?? "en") as Lang;
  const sessionId = typeof report.report_metadata?.source_session_id === "string" ? report.report_metadata.source_session_id : null;
  const tool = "inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium disabled:opacity-50";

  return (
    <div className="mx-auto max-w-[1280px] space-y-4 report-page">
      <Link to="/app/reports" className="report-chrome text-sm text-muted-foreground hover:text-foreground">← {t("reports.title")}</Link>

      <header className="report-chrome rounded-lg border border-border bg-card p-4">
        <div className="flex flex-wrap items-start gap-3">
          <Badge className={TYPE_COLORS[report.report_type] ?? "bg-secondary text-muted-foreground"}>{report.report_type}</Badge>
          <div className="min-w-0 flex-1">
            <h1 className="text-2xl font-semibold leading-tight text-foreground">{report.title}</h1>
            <p className="mt-1 text-xs text-muted-foreground">
              <span className="font-mono">R#{report.id} · v{version}</span>
              {" · "}{t("reports.generated").replace("{date}", formatFullDate(report.created_at))}
              {" · "}{t("reports.sourceLanguage").replace("{language}", t(`reports.lang.${report.source_language ?? "en"}`))}
              {report.visibility === "private" && <> · {t("reports.private")}</>}
              {sessionId && <> · <Link className="text-primary hover:underline" to={`/app/chat/${sessionId}`}>{t("reports.fromChat")}</Link></>}
            </p>
          </div>
        </div>

        {/* Toolbar: what is shown is what is exported, printed and published */}
        <div className="report-toolbar mt-4 flex flex-wrap items-center gap-2">
          <div role="group" aria-label={t("reports.view.label")} className="flex rounded-md border border-border p-0.5">
            {LANGS.map((l) => (
              <button key={l} type="button" lang={l} aria-pressed={lang === l} onClick={() => setLang(l)}
                      className={`rounded px-2.5 py-1 text-xs ${lang === l ? "bg-selected font-semibold text-primary" : "text-muted-foreground hover:text-foreground"}`}>
                {t(`reports.view.${l}`)}
              </button>
            ))}
          </div>
          <span className="flex-1" />
          <button type="button" className={`${tool} bg-primary text-primary-foreground hover:bg-primary-hover`} disabled={!exportable}
                  title={exportable ? undefined : t("reports.notReadyHint")} onClick={() => setDialog("export")}>
            {t("reports.export.button")}
          </button>
          <button type="button" className={`${tool} bg-secondary text-foreground hover:bg-muted`} disabled={!exportable}
                  onClick={() => window.print()}>{t("reports.print")}</button>
          {!readOnly && (
            <button type="button" className={`${tool} bg-secondary text-foreground hover:bg-muted`} onClick={() => setDialog("share")}>
              {t("reports.share")}</button>
          )}
          {publishable.length > 0 && !readOnly && (
            <button type="button" className={`${tool} bg-secondary text-foreground hover:bg-muted`} disabled={!exportable}
                    onClick={() => setDialog("publish")}>{t("reports.publish.button")}</button>
          )}
        </div>
      </header>

      <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1fr)_16rem]">
        {(coverage || outline.length > 0) && (
          <aside className="report-chrome space-y-4 lg:sticky lg:top-[calc(var(--topbar-h)+1rem)] lg:order-2 lg:max-h-[calc(100vh-var(--topbar-h)-2rem)] lg:overflow-y-auto">
            {coverage && (
              <section aria-labelledby="report-coverage" className="rounded-lg border border-border bg-card p-4 text-sm">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <h2 id="report-coverage" className="font-medium">{t("reports.coverage.title")}</h2>
                  <StatusText tone={coverage.tone === "none" ? "neutral" : coverage.tone} className="text-xs">{t(coverage.stateKey)}</StatusText>
                </div>
                <dl className="mt-2 space-y-1 text-xs text-muted-foreground">
                  <div><dt className="inline">{t("reports.coverage.accounts")}: </dt>
                    <dd className="inline text-foreground [overflow-wrap:anywhere]">{coverage.accounts.join(", ") || t("reports.coverage.none")}</dd></div>
                  <div><dt className="inline">{t("reports.coverage.regions")}: </dt>
                    <dd className="inline text-foreground [overflow-wrap:anywhere]">{coverage.regions.join(", ") || t("reports.coverage.none")}</dd></div>
                  <div>{t("reports.coverage.readAt").replace("{time}", formatFullDate(coverage.readAt))}</div>
                </dl>
                {coverage.partial.length > 0 && (
                  <ul className="mt-2 list-disc space-y-0.5 pl-4 text-xs text-status-warn">
                    {coverage.partial.map((p) => <li key={p.key}>{t(p.key).replace("{n}", String(p.n))}</li>)}
                  </ul>
                )}
                {coverage.tone === "warn" && <p className="mt-2 text-xs text-status-warn">{t("reports.coverage.partialNote")}</p>}
                <p className="mt-2 text-xs text-muted-foreground">{t("reports.coverage.by")}</p>
              </section>
            )}
            {outline.length > 0 && (
              <>
                <nav aria-label={t("reports.outline")} className="hidden rounded-lg border border-border bg-card p-4 lg:block">
                  <h2 className="mb-2 text-sm font-medium">{t("reports.outline")}</h2>
                  <Outline headings={outline} onGo={goTo} />
                </nav>
                <details className="rounded-lg border border-border bg-card p-4 lg:hidden">
                  <summary className="cursor-pointer text-sm font-medium">{t("reports.outline")} · {outline.length}</summary>
                  <div className="mt-2"><Outline headings={outline} onGo={goTo} /></div>
                </details>
              </>
            )}
          </aside>
        )}
        <div className="min-w-0 lg:order-1">
          <Paper key={lang} report={report} lang={lang} source={source} rendering={renderings[lang]} version={version} t={t}
                 html={paper?.html ?? null} onReadSource={() => setLang(source)} />
        </div>
      </div>

      <p className="report-chrome text-xs text-muted-foreground">{t("reports.note")}</p>

      <ExportDialog open={dialog === "export"} onOpenChange={(o) => setDialog(o ? "export" : null)}
                    reportId={report.id} version={version} language={lang} />
      {publishable.length > 0 && (
        <PublishDialog open={dialog === "publish"} onOpenChange={(o) => setDialog(o ? "publish" : null)}
                       reportId={report.id} version={version} language={lang} channels={publishable} />
      )}
      {dialog === "share" && (
        <ShareDialog defaultSubject={`R#${report.id} v${version} · ${report.title}`}
                     defaultBody={renderings[lang]?.body_markdown || report.content_markdown}
                     onClose={() => setDialog(null)} />
      )}
    </div>
  );
}

/** The paper's sections (h2, and h3 indented): each jumps to its heading. */
function Outline({ headings, onGo }: { headings: Heading[]; onGo: (id: string) => void }) {
  return (
    <ol className="space-y-1 text-sm">
      {headings.map((h) => (
        <li key={h.id} className={h.level === 3 ? "pl-4" : ""}>
          <a href={`#${h.id}`} onClick={(e) => { e.preventDefault(); onGo(h.id); }}
             className="block rounded px-1 py-0.5 text-muted-foreground [overflow-wrap:anywhere] hover:bg-accent hover:text-foreground">
            {h.text}
          </a>
        </li>
      ))}
    </ol>
  );
}

function Paper({ report, lang, source, rendering, version, t, html, onReadSource }: {
  report: Report; lang: Lang; source: Lang; rendering: ContentRendering | undefined; version: number;
  t: (k: string) => string; html: string | null; onReadSource: () => void;
}) {
  const readOnly = useReadOnly();  // a viewer account: no write controls (the server refuses them)
  const state = paperState(rendering);
  const request = useRequestTranslation(report.id);
  if (state === "ready") {
    return (
      <article className="paper rounded-lg border border-border bg-card p-6" lang={lang}>
        <div className="mb-3 text-[11px] text-muted-foreground">
          AgenticOps · R#{report.id} · v{version} · {t(`reports.lang.${lang}`)}
        </div>
        <div className="report-content" dangerouslySetInnerHTML={{ __html: html ?? renderMarkdown(rendering!.body_markdown ?? "") }} />
      </article>
    );
  }
  const retry = () => request.mutate({ version, languages: [lang] });
  return (
    <section className="paper-state rounded-lg border border-dashed border-border bg-card p-6 text-sm" lang={lang}>
      <p className="font-medium text-foreground">{t(`reports.lang.${lang}`)} · {t(`reports.state.${state}`)}</p>
      <p className="mt-1 text-muted-foreground">
        {state === "failed" && rendering?.error_code ? t(`reports.error.${rendering.error_code}`) : t(`reports.stateHint.${state}`)}
      </p>
      <div className="mt-3 flex flex-wrap gap-2">
        {(state === "notPrepared" || state === "failed" || state === "stale") && !readOnly && (
          <button type="button" onClick={retry} disabled={request.isPending}
                  className="rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary-hover disabled:opacity-50">
            {state === "failed" ? t("reports.retry") : t("reports.prepare")}
          </button>
        )}
        {lang !== source && (
          <button type="button" onClick={onReadSource} className="rounded-md bg-secondary px-3 py-1.5 text-xs text-foreground hover:bg-muted">
            {t("reports.readSource").replace("{language}", t(`reports.lang.${source}`))}
          </button>
        )}
      </div>
    </section>
  );
}
