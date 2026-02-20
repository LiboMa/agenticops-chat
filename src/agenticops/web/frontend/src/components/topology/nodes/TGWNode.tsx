import { memo } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import { cn } from "@/lib/cn";
import type { BaseNodeData } from "../mapTopologyToGraph";

function TGWNodeInner({ data, selected }: NodeProps) {
  const d = data as BaseNodeData;
  const raw = d.raw as { transit_gateway_id?: string; state?: string };

  return (
    <div
      className={cn(
        "rounded-lg border-2 border-purple-400 bg-purple-50 px-3 py-2 min-w-[180px] shadow-sm",
        selected && "ring-2 ring-pd-green-500"
      )}
    >
      <div className="flex items-center gap-2">
        {/* Hub icon */}
        <svg
          className="w-4 h-4 text-purple-600 flex-shrink-0"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={2}
        >
          <circle cx="12" cy="12" r="3" />
          <path d="M12 2v7M12 15v7M2 12h7M15 12h7" />
        </svg>
        <div className="min-w-0">
          <div className="text-xs font-semibold text-purple-800 truncate">
            {raw.transit_gateway_id}
          </div>
          <div className="text-[10px] text-purple-500">
            Transit Gateway &middot; {raw.state}
          </div>
        </div>
      </div>
      <Handle
        type="source"
        position={Position.Bottom}
        className="!bg-purple-400"
      />
    </div>
  );
}

export const TGWNode = memo(TGWNodeInner);
