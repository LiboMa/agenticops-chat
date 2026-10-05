import { Link } from "react-router-dom";
import type { ChangeRequestDetail } from "@/api/types";
import { externalRefLink, sourceLabel, unresolvedHints } from "@/lib/changeDetail";
import { isBlank } from "@/lib/issueDetail";
import { formatFullDate } from "@/lib/formatDate";
import { renderMarkdown } from "@/lib/renderMarkdown";

type T = (key: string) => string;

/** ① Request: what was asked for — the description, who and when, the external ticket (linked only to an http(s)
 *  URL), the targets (a hint no inventory resource matched in amber), the justification and the requester's steps. */
export function RequestBody({ cr, t }: { cr: ChangeRequestDetail; t: T }) {
  const ext = externalRefLink(cr.external_ref);
  const hints = unresolvedHints(cr);
  const muted = "text-muted-foreground";
  return (
    <div className="space-y-4 text-sm">
      {!isBlank(cr.description) && (
        <div className="report-content" dangerouslySetInnerHTML={{ __html: renderMarkdown(cr.description) }} />
      )}
      <dl className="grid grid-cols-2 md:grid-cols-3 gap-4">
        <div>
          <dt className={muted}>{t("plans.requestedBy")}</dt>
          <dd className="font-mono break-all">{cr.requested_by}</dd>
        </div>
        {(cr.requested_at ?? cr.created_at) && (
          <div>
            <dt className={muted}>{t("issues.created")}</dt>
            <dd>{formatFullDate(cr.requested_at ?? cr.created_at)}</dd>
          </div>
        )}
        {!isBlank(cr.source) && (
          <div>
            <dt className={muted}>{t("changes.source")}</dt>
            <dd>{sourceLabel(cr.source, t)}</dd>
          </div>
        )}
      </dl>
      {ext && (
        <p>
          <span className={muted}>{t("changes.externalRef")}: </span>
          {ext.url ? (
            <a href={ext.url} target="_blank" rel="noopener noreferrer" className="font-mono text-primary hover:underline">
              {ext.label}
            </a>
          ) : (
            <span className="font-mono">{ext.label}</span>
          )}
          {ext.requestedBy && (
            <span className={muted}> · {t("changes.externalRequestedBy").replace("{name}", ext.requestedBy)}</span>
          )}
        </p>
      )}
      {(cr.target_resources.length > 0 || hints.length > 0) && (
        <div>
          <span className={`${muted} block mb-1`}>{t("changes.targets")}</span>
          <div className="flex flex-wrap gap-1">
            {cr.target_resources.map((x, i) => {
              const title = typeof x.evidence === "string" ? x.evidence : x.evidence.command;
              return x.db_id != null ? (
                <Link key={`${x.resource_id}-${i}`} to={`/app/resources/${x.db_id}`} title={title}
                      className="px-1.5 py-0.5 rounded bg-secondary text-xs font-mono hover:underline">
                  {x.resource_id}
                </Link>
              ) : (
                <span key={`${x.resource_id}-${i}`} title={title} className="px-1.5 py-0.5 rounded bg-secondary text-xs font-mono">
                  {x.resource_id}
                </span>
              );
            })}
            {hints.map((h, i) => (
              <span key={`hint-${i}`} title={t("changes.unresolved")}
                    className="px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-600 text-xs font-mono">
                {h}?
              </span>
            ))}
          </div>
        </div>
      )}
      {!isBlank(cr.justification) && (
        <div>
          <span className={`${muted} block`}>{t("changes.justification")}</span>
          <p className={muted}>{cr.justification}</p>
        </div>
      )}
      {(cr.proposed_steps?.length ?? 0) > 0 && (
        <div>
          <span className={`${muted} block mb-1`}>{t("changes.proposedSteps")}</span>
          <ol className="space-y-1">
            {cr.proposed_steps!.map((st, i) => (
              <li key={i} className="flex gap-2">
                <span className="font-mono text-xs text-muted-foreground pt-0.5">{i + 1}.</span>
                <div className="min-w-0">
                  {st.action && <div className="text-foreground">{st.action}</div>}
                  <code className="text-xs font-mono break-all">{st.command}</code>
                </div>
              </li>
            ))}
          </ol>
        </div>
      )}
    </div>
  );
}
