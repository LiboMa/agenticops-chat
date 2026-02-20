import { memo } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import { cn } from "@/lib/cn";
import type { BaseNodeData } from "../mapTopologyToGraph";

function NATNodeInner({ data, selected }: NodeProps) {
  const d = data as BaseNodeData;
  const raw = d.raw as { az?: string; state?: string };

  return (
    <div
      className={cn(
        "rounded-lg border-2 border-orange-400 bg-orange-50 px-3 py-2 min-w-[180px] shadow-sm",
        selected && "ring-2 ring-pd-green-500"
      )}
    >
      <Handle type="target" position={Position.Top} className="!bg-orange-400" />
      <div className="flex items-center gap-2">
        {/* Arrow-right-from-bracket icon */}
        <svg
          className="w-4 h-4 text-orange-600 flex-shrink-0"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={2}
        >
          <path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7" />
        </svg>
        <div className="min-w-0">
          <div className="text-xs font-semibold text-orange-800 truncate">
            {d.label}
          </div>
          <div className="text-[10px] text-orange-500">
            {raw.az} &middot; {raw.state}
          </div>
        </div>
      </div>
      <Handle
        type="source"
        position={Position.Bottom}
        className="!bg-orange-400"
      />
    </div>
  );
}

export const NATNode = memo(NATNodeInner);
