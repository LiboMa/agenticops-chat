interface VpcSelectorProps {
  region: string;
  regions: { code: string; name: string }[];
  vpcId: string;
  onRegionChange: (region: string) => void;
  onVpcIdChange: (vpcId: string) => void;
  onListVpcs: () => void;
  onAnalyze: () => void;
  onScanRegion?: () => void;
  isLoadingVpcs: boolean;
  isLoadingTopology: boolean;
  isLoadingRegionTopology?: boolean;
}

export function VpcSelector({
  region,
  regions,
  vpcId,
  onRegionChange,
  onVpcIdChange,
  onListVpcs,
  onAnalyze,
  onScanRegion,
  isLoadingVpcs,
  isLoadingTopology,
  isLoadingRegionTopology,
}: VpcSelectorProps) {
  return (
    <div className="flex flex-wrap items-end gap-4">
      <div>
        <label className="block text-sm text-gray-600 mb-1">Region</label>
        <select
          value={region}
          onChange={(e) => onRegionChange(e.target.value)}
          className="border border-gray-300 rounded-md px-3 py-2 w-64 text-sm focus:outline-none focus:ring-2 focus:ring-pd-green-500"
        >
          {regions.map((r) => (
            <option key={r.code} value={r.code}>
              {r.code} — {r.name}
            </option>
          ))}
        </select>
      </div>
      {onScanRegion && (
        <button
          onClick={onScanRegion}
          disabled={isLoadingRegionTopology}
          className="bg-purple-600 text-white px-4 py-2 rounded-md hover:bg-purple-500 text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {isLoadingRegionTopology ? "Scanning..." : "Scan Region"}
        </button>
      )}
      <div className="w-px h-8 bg-gray-300" />
      <div>
        <label className="block text-sm text-gray-600 mb-1">VPC ID</label>
        <input
          type="text"
          value={vpcId}
          onChange={(e) => onVpcIdChange(e.target.value)}
          className="border border-gray-300 rounded-md px-3 py-2 w-64 text-sm focus:outline-none focus:ring-2 focus:ring-pd-green-500"
          placeholder="vpc-0abc123..."
        />
      </div>
      <button
        onClick={onAnalyze}
        disabled={isLoadingTopology || !vpcId.trim()}
        className="bg-pd-green-600 text-white px-4 py-2 rounded-md hover:bg-pd-green-500 text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
      >
        {isLoadingTopology ? "Analyzing..." : "Analyze Topology"}
      </button>
      <button
        onClick={onListVpcs}
        disabled={isLoadingVpcs}
        className="bg-gray-600 text-white px-4 py-2 rounded-md hover:bg-gray-500 text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
      >
        {isLoadingVpcs ? "Loading..." : "List VPCs"}
      </button>
    </div>
  );
}
