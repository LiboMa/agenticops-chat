import { Card, CardHeader } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import type { Subnet } from "@/api/types";

interface SubnetsTableProps {
  subnets: Subnet[];
}

export function SubnetsTable({ subnets }: SubnetsTableProps) {
  if (subnets.length === 0) return null;

  return (
    <Card>
      <CardHeader>
        <h3 className="text-lg font-semibold text-gray-900">
          Subnets ({subnets.length})
        </h3>
      </CardHeader>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-gray-50 text-left text-gray-500 text-xs uppercase tracking-wider">
              <th className="px-4 py-3">Subnet ID</th>
              <th className="px-4 py-3">Name</th>
              <th className="px-4 py-3">AZ</th>
              <th className="px-4 py-3">CIDR</th>
              <th className="px-4 py-3">Type</th>
              <th className="px-4 py-3">Available IPs</th>
              <th className="px-4 py-3">Route Table</th>
              <th className="px-4 py-3">Default Target</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {subnets.map((s) => (
              <tr key={s.subnet_id} className="hover:bg-gray-50">
                <td className="px-4 py-2 font-mono">{s.subnet_id}</td>
                <td className="px-4 py-2">{s.name ?? "-"}</td>
                <td className="px-4 py-2">{s.az}</td>
                <td className="px-4 py-2">{s.cidr}</td>
                <td className="px-4 py-2">
                  {s.type === "public" ? (
                    <Badge className="bg-green-100 text-green-800">
                      public
                    </Badge>
                  ) : (
                    <Badge className="bg-gray-200 text-gray-700">
                      private
                    </Badge>
                  )}
                </td>
                <td className="px-4 py-2">{s.available_ips}</td>
                <td className="px-4 py-2 font-mono text-xs">
                  {s.route_table_id ?? "-"}
                </td>
                <td className="px-4 py-2 text-xs">
                  {s.default_route_target ?? "-"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
