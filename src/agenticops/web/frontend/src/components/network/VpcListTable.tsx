import type { Vpc } from "@/api/types";

interface VpcListTableProps {
  region: string;
  vpcs: Vpc[];
  onUseVpc: (vpcId: string) => void;
}

export function VpcListTable({ region, vpcs, onUseVpc }: VpcListTableProps) {
  return (
    <div className="bg-gray-50 rounded-lg p-4">
      <h3 className="text-sm font-semibold text-gray-700 mb-2">
        VPCs in {region} ({vpcs.length})
      </h3>
      {vpcs.length > 0 ? (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-gray-500">
              <th className="pb-2 pr-4">VPC ID</th>
              <th className="pb-2 pr-4">CIDR</th>
              <th className="pb-2 pr-4">Name</th>
              <th className="pb-2 pr-4">State</th>
              <th className="pb-2 pr-4">Default</th>
              <th className="pb-2" />
            </tr>
          </thead>
          <tbody>
            {vpcs.map((v) => (
              <tr key={v.VpcId} className="border-t border-gray-200">
                <td className="py-2 pr-4 font-mono">{v.VpcId}</td>
                <td className="py-2 pr-4">{v.CidrBlock}</td>
                <td className="py-2 pr-4">{v.Name ?? "-"}</td>
                <td className="py-2 pr-4">{v.State}</td>
                <td className="py-2 pr-4">{v.IsDefault ? "Yes" : "No"}</td>
                <td className="py-2">
                  <button
                    onClick={() => onUseVpc(v.VpcId)}
                    className="text-pd-green-600 hover:text-pd-green-500 text-xs underline font-medium"
                  >
                    Use
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="text-gray-500 text-sm">No VPCs found in this region.</p>
      )}
    </div>
  );
}
