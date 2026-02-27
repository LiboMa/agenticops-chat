import { memo } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import { cn } from "@/lib/cn";
import type { BaseNodeData } from "../types";
import { StatusBadge } from "./StatusBadge";

function RdsNodeInner({ data, selected }: NodeProps) {
  const d = data as BaseNodeData;
  const raw = d.raw as { engine?: string; status?: string };

  return (
    <div
      className={cn(
        "relative rounded-lg border-2 border-violet-400 bg-gradient-to-br from-violet-50 to-purple-50 px-3 py-2 min-w-[180px] shadow-sm transition-all duration-200 hover:shadow-md hover:-translate-y-0.5",
        d.highlighted && "ring-2 ring-green-400 shadow-lg shadow-green-200/50",
        d.dimmed && "opacity-40 transition-opacity duration-300",
        selected && !d.highlighted && "ring-2 ring-pd-green-500"
      )}
    >
      {/* Violet accent bar */}
      <div className="absolute left-0 top-2 bottom-2 w-1 rounded-full bg-violet-400" />
      <StatusBadge status={d.status} />
      <Handle type="target" position={Position.Top} className="!bg-violet-400" />
      <div className="flex items-center gap-2 pl-1.5">
        {/* Database cylinder icon */}
        <svg
          className="w-5 h-5 text-violet-600 flex-shrink-0"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={2}
        >
          <ellipse cx="12" cy="5" rx="9" ry="3" />
          <path d="M21 12c0 1.66-4.03 3-9 3s-9-1.34-9-3" />
          <path d="M3 5v14c0 1.66 4.03 3 9 3s9-1.34 9-3V5" />
        </svg>
        <div className="min-w-0">
          <div className="text-xs font-semibold text-violet-800 truncate">
            {d.label}
          </div>
          <div className="text-[10px] text-violet-500">
            {raw.engine ?? "RDS"} &middot; {raw.status ?? "unknown"}
          </div>
        </div>
      </div>
      <Handle
        type="source"
        position={Position.Bottom}
        className="!bg-violet-400"
      />
    </div>
  );
}

export const RdsNode = memo(RdsNodeInner);
