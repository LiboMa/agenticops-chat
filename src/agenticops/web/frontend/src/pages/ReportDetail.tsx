import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { useReport } from "@/hooks/useReport";
import { useNotificationChannels } from "@/hooks/useNotifications";
import { useRendering, useRequestTranslation } from "@/hooks/useRendering";
import { useLocale } from "@/i18n/LocaleContext";
import { Badge } from "@/components/ui/Badge";
import { Spinner } from "@/components/ui/Spinner";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import { formatFullDate } from "@/lib/formatDate";
import { renderMarkdown } from "@/lib/renderMarkdown";
import { LANGS, canExport, paperState, type Lang } from "@/lib/reportView";
import { publishableChannels } from "@/lib/publish";
import ShareDialog from "@/components/ShareDialog";
import { ExportDialog } from "@/components/reportview/ExportDialog";
import { PublishDialog } from "@/components/reportview/PublishDialog";
import type { ContentRendering, Report } from "@/api/types";

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

  if (isLoading) return <Spinner label={t("common.loading")} />;
  if (error) return <ErrorBanner message={error.message} onRetry={() => refetch()} actionLabel={t("common.retry")} />;
  if (!report) return null;

  const exportable = canExport(lang, renderings);
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
          <button type="button" className={`${tool} bg-secondary text-foreground hover:bg-muted`} onClick={() => setDialog("share")}>
            {t("reports.share")}</button>
          {publishable.length > 0 && (
            <button type="button" className={`${tool} bg-secondary text-foreground hover:bg-muted`} disabled={!exportable}
                    onClick={() => setDialog("publish")}>{t("reports.publish.button")}</button>
          )}
        </div>
      </header>

      <Paper key={lang} report={report} lang={lang} source={source} rendering={renderings[lang]} version={version} t={t}
             onReadSource={() => setLang(source)} />

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

function Paper({ report, lang, source, rendering, version, t, onReadSource }: {
  report: Report; lang: Lang; source: Lang; rendering: ContentRendering | undefined; version: number;
  t: (k: string) => string; onReadSource: () => void;
}) {
  const state = paperState(rendering);
  const request = useRequestTranslation(report.id);
  if (state === "ready") {
    return (
      <article className="paper rounded-lg border border-border bg-card p-6" lang={lang}>
        <div className="mb-3 text-[11px] text-muted-foreground">
          AgenticOps · R#{report.id} · v{version} · {t(`reports.lang.${lang}`)}
        </div>
        <div className="report-content" dangerouslySetInnerHTML={{ __html: renderMarkdown(rendering!.body_markdown ?? "") }} />
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
        {(state === "notPrepared" || state === "failed" || state === "stale") && (
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
