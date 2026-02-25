import { Card, CardBody } from "@/components/ui/Card";
import type { VpcTopology } from "@/api/types";
import { cn } from "@/lib/cn";

interface TopologySummaryProps {
  topology: VpcTopology;
}

export function TopologySummary({ topology }: TopologySummaryProps) {
  const rs = topology.reachability_summary;

  const cards = [
    {
      label: "Internet Gateway",
      value: rs.has_internet_gateway ? "Yes" : "No",
      color: rs.has_internet_gateway ? "text-green-600" : "text-gray-400",
    },
    {
      label: "Public Subnets",
      value: rs.public_subnet_count,
      color: "text-pd-green-600",
    },
    {
      label: "Private Subnets",
      value: rs.private_subnet_count,
      color: "text-gray-700",
    },
    {
      label: "NAT Gateways",
      value: rs.nat_gateway_count,
      color: "text-orange-600",
    },
    {
      label: "Transit Gateways",
      value: rs.transit_gateway_attachments,
      color: "text-gray-600",
    },
    {
      label: "VPC Peering",
      value: rs.vpc_peering_count,
      color: "text-gray-600",
    },
    {
      label: "VPC Endpoints",
      value: rs.vpc_endpoint_count,
      color: "text-gray-600",
    },
    {
      label: "Issues",
      value: rs.issues.length,
      color: rs.issues.length > 0 ? "text-red-600" : "text-green-600",
    },
  ];

  return (
    <Card>
      <CardBody>
        <h3 className="text-lg font-semibold text-gray-900 mb-4">
          Reachability Summary
        </h3>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {cards.map((c) => (
            <div key={c.label} className="text-center p-3 bg-gray-50 rounded-lg">
              <div className={cn("text-2xl font-bold", c.color)}>{c.value}</div>
              <div className="text-xs text-gray-500 mt-1">{c.label}</div>
            </div>
          ))}
        </div>

        {rs.issues.length > 0 && (
          <div className="mt-4 p-3 bg-red-50 border border-red-200 rounded-lg">
            <h4 className="text-sm font-semibold text-red-800 mb-1">Issues</h4>
            <ul className="text-sm text-red-700 list-disc list-inside space-y-0.5">
              {rs.issues.map((issue, i) => (
                <li key={i}>{issue}</li>
              ))}
            </ul>
          </div>
        )}
      </CardBody>
    </Card>
  );
}
