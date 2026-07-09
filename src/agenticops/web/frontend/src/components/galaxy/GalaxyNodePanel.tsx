import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useLocale } from "@/i18n/LocaleContext";
import { useResource, useResourceIssues } from "@/hooks/useResourceDetail";
import { IssueStatusBadge } from "@/components/ui/IssueStatusBadge";
import { GalaxyIssueDialog } from "@/components/galaxy/GalaxyIssueDialog";
import { GalaxyRawDataPanel } from "@/components/galaxy/GalaxyRawDataPanel";
import type { Anomaly, GalaxyGraphNode, GalaxyHealth } from "@/api/types";

const HEALTH_STYLE: Record<GalaxyHealth, { bg: string; fg: string; sym: string }> = {
  healthy: { bg: "rgba(125,133,144,0.18)", fg: "#b9c0c9", sym: "●" },
  warning: { bg: "rgba(250,178,25,0.16)", fg: "#fab219", sym: "⚠" },
  critical: { bg: "rgba(208,59,59,0.18)", fg: "#f08a8a", sym: "⨯" },
};
const SEV_BORDER: Record<string, string> = {
  critical: "#d03b3b", high: "#fab219", medium: "#fab219", low: "#7d8590",
};

function resourcePk(nodeId: string): number {
  const m = /^res:(\d+)$/.exec(nodeId);
  return m ? parseInt(m[1], 10) : 0;
}

export function GalaxyNodePanel({ node, onClose }: { node: GalaxyGraphNode; onClose: () => void }) {
  const { t } = useLocale();
  const navigate = useNavigate();
  const isResource = node.kind === "resource";
  const pk = isResource ? resourcePk(node.id) : 0;

  const resource = useResource(pk);
  const issues = useResourceIssues(pk, isResource);
  const [openIssue, setOpenIssue] = useState<Anomaly | null>(null);
  const [showRaw, setShowRaw] = useState(false);

  // Panel ESC closes the panel — but ONLY when no second-layer surface (issue
  // dialog or raw-data panel) is open. Those own ESC via capture-phase while
  // mounted, so a first ESC dismisses them, a second ESC closes this panel.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape" && !openIssue && !showRaw) onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, openIssue, showRaw]);

  const rawData = (resource.data?.resource_metadata ?? {}) as Record<string, unknown>;
  const rawCount = Object.keys(rawData).length;

  const health = (node.health || "healthy") as GalaxyHealth;
  const hs = HEALTH_STYLE[health];
  const r = resource.data;

  return (
    <div className="absolute top-9 right-0 bottom-0 w-80 z-20 overflow-y-auto p-4
                    bg-[#0f0e17]/95 backdrop-blur border-l border-white/10
                    animate-[slideInRight_0.2s_ease-out]">
      <button onClick={onClose} aria-label="close"
              className="absolute top-3 right-3 text-[#9691a8] hover:text-white text-base">✕</button>

      {isResource ? (
        <>
          <div className="text-[11px] uppercase tracking-wider text-[#9691a8]">{t("galaxy.resource")} · {node.type}</div>
          <div className="text-[15px] font-semibold text-white mt-0.5 mb-3 break-all">
            {r?.resource_name || node.name || r?.resource_id || node.id}
          </div>
          <span className="inline-flex items-center gap-1.5 text-xs font-semibold px-2.5 py-0.5 rounded-full mb-3.5"
                style={{ background: hs.bg, color: hs.fg }}>
            {hs.sym} {t(`galaxy.health.${health}`)}
          </span>

          <Row k={t("galaxy.resourceId")} v={r?.resource_id ?? "…"} />
          <Row k={t("galaxy.type")} v={r?.resource_type ?? node.type} />
          <Row k={t("galaxy.region")} v={r?.region ?? "…"} />
          <Row k={t("galaxy.cloud")} v={r?.provider ?? "…"} />
          <Row k={t("galaxy.runStatus")} v={r?.status ?? "…"} />

          <div className="text-[11px] uppercase tracking-wider text-[#9691a8] mt-4 mb-1.5">
            {t("galaxy.openIssues")}{issues.data ? ` (${issues.data.length})` : ""}
          </div>
          {issues.isLoading ? (
            <div className="text-xs text-[#9691a8]">…</div>
          ) : issues.data && issues.data.length > 0 ? (
            issues.data.slice(0, 8).map((it) => (
              <button key={it.id} onClick={() => setOpenIssue(it)}
                    className="block w-full text-left text-xs px-2.5 py-1.5 rounded mb-1.5 bg-white/[0.04] hover:bg-white/[0.09] transition-colors"
                    style={{ borderLeft: `2px solid ${SEV_BORDER[it.severity] || "#7d8590"}` }}>
                <div className="flex items-center justify-between gap-2 mb-0.5">
                  <span className="text-[10px] uppercase text-[#9691a8]">{it.severity}</span>
                  <IssueStatusBadge status={it.status} />
                </div>
                <div className="text-white">{it.title}</div>
              </button>
            ))
          ) : (
            <div className="text-xs text-[#9691a8]">{t("galaxy.noIssues")}</div>
          )}

          <div className="text-[11px] uppercase tracking-wider text-[#9691a8] mt-4 mb-1.5">{t("galaxy.data")}</div>
          <button onClick={() => setShowRaw(true)} disabled={rawCount === 0}
                  className="flex items-center justify-between w-full px-3 py-2.5 rounded-lg text-[13px]
                             bg-violet-400/10 border border-violet-400/25 text-violet-200
                             hover:bg-violet-400/20 disabled:opacity-40 disabled:cursor-default">
            <span>{t("galaxy.viewRaw")}</span>
            <span className="text-[11px] text-[#807c92]">
              {rawCount} keys · {(JSON.stringify(rawData).length / 1024).toFixed(1)}KB ›
            </span>
          </button>

          <button onClick={() => navigate(`/app/resources/${pk}`)}
                  className="inline-block mt-3.5 text-xs text-violet-300 hover:underline">
            {t("galaxy.openResource")} →
          </button>
        </>
      ) : (
        <>
          <div className="text-[11px] uppercase tracking-wider text-[#9691a8]">
            {node.kind === "account" ? t("galaxy.account") : t("galaxy.group")}
          </div>
          <div className="text-[15px] font-semibold text-white mt-0.5 mb-3 break-all">{node.name || node.id}</div>
          {node.kind === "group" && <Row k={t("galaxy.members")} v={String(node.members ?? 0)} />}
          {node.kind === "account" && <Row k={t("galaxy.account")} v={`#${node.acct}`} />}
          <div className="text-[11px] text-[#9691a8] mt-2">{t("galaxy.dblFocusHint")}</div>
        </>
      )}

      {openIssue && <GalaxyIssueDialog issue={openIssue} onClose={() => setOpenIssue(null)} />}
      {showRaw && (
        <GalaxyRawDataPanel
          title="raw_data"
          subtitle={`${node.type} · ${r?.resource_id ?? node.name}`}
          data={rawData}
          onBack={() => setShowRaw(false)}
        />
      )}
    </div>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex justify-between gap-3 py-1.5 border-b border-white/[0.06] text-xs">
      <span className="text-[#9691a8]">{k}</span>
      <span className="text-white text-right break-all">{v}</span>
    </div>
  );
}
