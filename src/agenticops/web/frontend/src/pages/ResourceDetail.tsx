import { useState } from "react";
import { useParams, Link } from "react-router-dom";
import { useResource, useResourceIssues, useResourceFixPlans, useResourceRelated } from "@/hooks/useResourceDetail";
import { Card, CardBody } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { StatusIndicator } from "@/components/ui/StatusIndicator";
import { SeverityBadge } from "@/components/ui/SeverityBadge";
import { Spinner } from "@/components/ui/Spinner";
import { ErrorBanner } from "@/components/ui/ErrorBanner";
import { formatShortDate } from "@/lib/formatDate";
import type { Anomaly, FixPlanWithExecutions, RelatedResourceItem } from "@/api/types";

const INFRA_TYPES = new Set([
  "VPC", "Subnet", "SecurityGroup", "RouteTable", "IGW", "NAT", "TGW",
  "InternetGateway", "NATGateway", "TransitGateway",
]);

type Tab = "overview" | "issues" | "fix-plans" | "network" | "tags";

export default function ResourceDetail() {
  const { id } = useParams<{ id: string }>();
  const resourceId = Number(id);
  const [tab, setTab] = useState<Tab>("overview");

  const resource = useResource(resourceId);
  const issues = useResourceIssues(resourceId, tab === "issues");
  const fixPlans = useResourceFixPlans(resourceId, tab === "fix-plans");
  const related = useResourceRelated(resourceId, tab === "network");

  if (resource.isLoading) return <Spinner label="Loading resource..." />;
  if (resource.error) return <ErrorBanner message={resource.error.message} onRetry={() => resource.refetch()} />;
  if (!resource.data) return <ErrorBanner message="Resource not found" />;

  const r = resource.data;
  const isInfra = INFRA_TYPES.has(r.resource_type);
  const networkTabLabel = isInfra ? "Contains" : "Network";

  const tabs: { key: Tab; label: string }[] = [
    { key: "overview", label: "Overview" },
    { key: "issues", label: "Issues" },
    { key: "fix-plans", label: "Fix Plans" },
    { key: "network", label: networkTabLabel },
    { key: "tags", label: "Tags" },
  ];

  return (
    <div className="space-y-4">
      <Link to="/app/resources" className="text-muted-foreground hover:text-foreground text-sm">
        &larr; Resources
      </Link>
      <Card>
        <div className="px-5 py-4 border-b">
          <div className="flex items-center gap-3 mb-2">
            <Badge className="bg-primary-100 text-primary-700">{r.resource_type}</Badge>
            <h1 className="text-lg font-semibold">{r.resource_name || r.resource_id}</h1>
          </div>
          <div className="flex items-center gap-6 text-sm text-muted-foreground">
            <span className="font-mono text-xs">{r.resource_id}</span>
            <span>{r.region}</span>
            <StatusIndicator status={r.status} />
          </div>
        </div>

        <div className="flex border-b px-5">
          {tabs.map((t) => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
                tab === t.key
                  ? "border-primary text-primary"
                  : "border-transparent text-muted-foreground hover:text-foreground"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>

        <CardBody>
          {tab === "overview" && <OverviewTab metadata={r.resource_metadata} />}
          {tab === "issues" && <IssuesTab data={issues.data} isLoading={issues.isLoading} />}
          {tab === "fix-plans" && <FixPlansTab data={fixPlans.data} isLoading={fixPlans.isLoading} />}
          {tab === "network" && <NetworkTab data={related.data} isLoading={related.isLoading} isInfra={isInfra} />}
          {tab === "tags" && <TagsTab tags={r.tags} />}
        </CardBody>
      </Card>
    </div>
  );
}

function OverviewTab({ metadata }: { metadata: Record<string, unknown> }) {
  const entries = Object.entries(metadata).filter(([, v]) => v != null && v !== "");
  if (entries.length === 0) return <p className="text-sm text-muted-foreground">No metadata available.</p>;
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-x-8 gap-y-1">
      {entries.map(([k, v]) => (
        <div key={k} className="flex justify-between py-1.5 border-b border-border/50">
          <span className="text-sm text-muted-foreground">{k.replace(/_/g, " ")}</span>
          <span className="text-sm font-mono truncate max-w-[50%] text-right">
            {typeof v === "object" ? JSON.stringify(v) : String(v)}
          </span>
        </div>
      ))}
    </div>
  );
}

function IssuesTab({ data, isLoading }: { data?: Anomaly[]; isLoading: boolean }) {
  if (isLoading) return <Spinner />;
  if (!data?.length) return <p className="text-sm text-muted-foreground">No issues found.</p>;
  return (
    <div className="space-y-1">
      {data.map((i) => (
        <Link
          key={i.id}
          to={`/app/issues/${i.id}`}
          className="flex items-center justify-between py-2 px-2 rounded-md hover:bg-accent transition-colors"
        >
          <div className="flex items-center gap-3">
            <SeverityBadge severity={i.severity} />
            <span className="text-sm">{i.title}</span>
          </div>
          <div className="flex items-center gap-3 text-xs text-muted-foreground">
            <span>{i.status}</span>
            <span>{formatShortDate(i.detected_at)}</span>
          </div>
        </Link>
      ))}
    </div>
  );
}

function FixPlansTab({ data, isLoading }: { data?: FixPlanWithExecutions[]; isLoading: boolean }) {
  if (isLoading) return <Spinner />;
  if (!data?.length) return <p className="text-sm text-muted-foreground">No fix plans found.</p>;
  return (
    <div className="space-y-1">
      {data.map((p) => (
        <Link
          key={p.id}
          to={`/app/fix-plans/${p.id}`}
          className="flex items-center justify-between py-2 px-2 rounded-md hover:bg-accent transition-colors"
        >
          <div className="flex items-center gap-3">
            <Badge className="text-xs">{p.risk_level}</Badge>
            <span className="text-sm">{p.title}</span>
          </div>
          <div className="flex items-center gap-3 text-xs text-muted-foreground">
            <span>{p.status}</span>
            {p.executions.length > 0 && <span>{p.executions[0].status}</span>}
          </div>
        </Link>
      ))}
    </div>
  );
}

function ResLink({ item }: { item: RelatedResourceItem }) {
  const inner = (
    <span className="flex items-center gap-2">
      <Badge className="text-[10px] px-1.5 py-0 bg-primary/10 text-primary">{item.resource_type}</Badge>
      <span className="text-sm">{item.resource_name || item.resource_id}</span>
    </span>
  );
  if (item.id) {
    return <Link to={`/app/resources/${item.id}`} className="text-primary hover:underline">{inner}</Link>;
  }
  return <span className="text-muted-foreground">{inner}</span>;
}

function NetworkTab({ data, isLoading, isInfra }: { data?: { network: RelatedResourceItem[]; contains: RelatedResourceItem[] }; isLoading: boolean; isInfra: boolean }) {
  if (isLoading) return <Spinner />;
  if (!data) return <p className="text-sm text-muted-foreground">No related resources.</p>;
  const items = isInfra ? data.contains : data.network;
  if (items.length === 0) return <p className="text-sm text-muted-foreground">No related resources found.</p>;
  return (
    <div className="space-y-1">
      {items.map((item, i) => (
        <div key={`${item.resource_id}-${i}`} className="flex items-center justify-between py-2 px-2 border-b border-border/50">
          <ResLink item={item} />
          {item.status && <StatusIndicator status={item.status} />}
        </div>
      ))}
    </div>
  );
}

function TagsTab({ tags }: { tags: Record<string, string> }) {
  const entries = Object.entries(tags);
  if (entries.length === 0) return <p className="text-sm text-muted-foreground">No tags.</p>;
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-x-8 gap-y-1">
      {entries.map(([k, v]) => (
        <div key={k} className="flex justify-between py-1.5 border-b border-border/50">
          <span className="text-sm text-muted-foreground">{k}</span>
          <span className="text-sm font-mono">{v}</span>
        </div>
      ))}
    </div>
  );
}
