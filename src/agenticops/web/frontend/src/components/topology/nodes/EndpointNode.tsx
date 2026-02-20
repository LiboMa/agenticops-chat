import { memo } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import { cn } from "@/lib/cn";
import type { BaseNodeData } from "../mapTopologyToGraph";

function EndpointNodeInner({ data, selected }: NodeProps) {
  const d = data as BaseNodeData;
  const raw = d.raw as { type?: string; state?: string; service_name?: string };

  return (
    <div
      className={cn(
        "rounded-lg border-2 border-indigo-400 bg-indigo-50 px-3 py-2 min-w-[180px] shadow-sm",
        selected && "ring-2 ring-pd-green-500"
      )}
    >
      <Handle
        type="target"
        position={Position.Top}
        className="!bg-indigo-400"
      />
      <div className="flex items-center gap-2">
        {/* Puzzle-piece icon */}
        <svg
          className="w-4 h-4 text-indigo-600 flex-shrink-0"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={2}
        >
          <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" />
        </svg>
        <div className="min-w-0">
          <div className="text-xs font-semibold text-indigo-800 truncate">
            {d.label}
          </div>
          <div className="text-[10px] text-indigo-500 truncate">
            {raw.type} &middot; {raw.state}
          </div>
        </div>
      </div>
    </div>
  );
}

export const EndpointNode = memo(EndpointNodeInner);
