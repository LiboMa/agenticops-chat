import { memo } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import { cn } from "@/lib/cn";
import type { BaseNodeData } from "../types";
import { StatusBadge } from "./StatusBadge";

function EndpointNodeInner({ data, selected }: NodeProps) {
  const d = data as BaseNodeData;
  const raw = d.raw as { type?: string; state?: string; service_name?: string };

  return (
    <div
      className={cn(
        "relative rounded-lg border-2 border-indigo-400 bg-gradient-to-br from-indigo-50 to-violet-50 px-3 py-2 min-w-[180px] shadow-sm transition-all duration-200 hover:shadow-md hover:-translate-y-0.5",
        d.highlighted && "ring-2 ring-green-400 shadow-lg shadow-green-200/50",
        d.dimmed && "opacity-40 transition-opacity duration-300",
        selected && !d.highlighted && "ring-2 ring-pd-green-500"
      )}
    >
      {/* Indigo accent bar */}
      <div className="absolute left-0 top-2 bottom-2 w-1 rounded-full bg-indigo-400" />
      <StatusBadge status={d.status} />
      <Handle
        type="target"
        position={Position.Top}
        className="!bg-indigo-400"
      />
      <div className="flex items-center gap-2 pl-1.5">
        {/* Puzzle-piece icon */}
        <svg
          className="w-5 h-5 text-indigo-600 flex-shrink-0"
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
