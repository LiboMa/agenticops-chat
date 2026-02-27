import { memo } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import { cn } from "@/lib/cn";
import type { BaseNodeData } from "../types";
import { StatusBadge } from "./StatusBadge";

function EcsClusterNodeInner({ data, selected }: NodeProps) {
  const d = data as BaseNodeData;
  const raw = d.raw as { status?: string };

  return (
    <div
      className={cn(
        "relative rounded-lg border-2 border-cyan-400 bg-gradient-to-br from-cyan-50 to-sky-50 px-3 py-2 min-w-[200px] shadow-sm transition-all duration-200 hover:shadow-md hover:-translate-y-0.5",
        d.highlighted && "ring-2 ring-green-400 shadow-lg shadow-green-200/50",
        d.dimmed && "opacity-40 transition-opacity duration-300",
        selected && !d.highlighted && "ring-2 ring-pd-green-500"
      )}
    >
      {/* Cyan accent bar */}
      <div className="absolute left-0 top-2 bottom-2 w-1 rounded-full bg-cyan-400" />
      <StatusBadge status={d.status} />
      <Handle type="target" position={Position.Top} className="!bg-cyan-400" />
      <div className="flex items-center gap-2 pl-1.5">
        {/* Container icon */}
        <svg
          className="w-5 h-5 text-cyan-600 flex-shrink-0"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={2}
        >
          <path d="M21 16V8a2 2 0 00-1-1.73l-7-4a2 2 0 00-2 0l-7 4A2 2 0 003 8v8a2 2 0 001 1.73l7 4a2 2 0 002 0l7-4A2 2 0 0021 16z" />
          <path d="M3.27 6.96L12 12.01l8.73-5.05M12 22.08V12" />
        </svg>
        <div className="min-w-0">
          <div className="text-xs font-semibold text-cyan-800 truncate">
            {d.label}
          </div>
          <div className="text-[10px] text-cyan-500">
            {d.resourceType} &middot; {raw.status ?? "unknown"}
          </div>
        </div>
      </div>
      <Handle
        type="source"
        position={Position.Bottom}
        className="!bg-cyan-400"
      />
    </div>
  );
}

export const EcsClusterNode = memo(EcsClusterNodeInner);
