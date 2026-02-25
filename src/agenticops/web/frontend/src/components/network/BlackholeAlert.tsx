import type { BlackholeRoute } from "@/api/types";

interface BlackholeAlertProps {
  routes: BlackholeRoute[];
}

export function BlackholeAlert({ routes }: BlackholeAlertProps) {
  if (routes.length === 0) return null;

  return (
    <div className="bg-red-50 border border-red-300 rounded-lg shadow-card p-6">
      <h3 className="text-lg font-semibold text-red-800 mb-3">
        Blackhole Routes
      </h3>
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-red-700">
            <th className="pb-2 pr-4">Route Table</th>
            <th className="pb-2 pr-4">Destination</th>
            <th className="pb-2 pr-4">Target</th>
            <th className="pb-2">Affected Subnets</th>
          </tr>
        </thead>
        <tbody>
          {routes.map((bh, i) => (
            <tr key={i} className="border-t border-red-200">
              <td className="py-2 pr-4 font-mono">{bh.route_table_id}</td>
              <td className="py-2 pr-4">{bh.destination}</td>
              <td className="py-2 pr-4">{bh.target}</td>
              <td className="py-2 text-xs font-mono">
                {bh.affected_subnets.length > 0
                  ? bh.affected_subnets.join(", ")
                  : "-"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
