import { memo } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import { cn } from "@/lib/cn";
import type { BaseNodeData } from "../types";
import { StatusBadge } from "./StatusBadge";

function RouteTableNodeInner({ data, selected }: NodeProps) {
  const d = data as BaseNodeData;
  const raw = d.raw as { is_main?: boolean; routes?: unknown[] };

  return (
    <div
      className={cn(
        "relative rounded border-2 border-slate-300 bg-slate-50 px-2.5 py-1.5 min-w-[150px] shadow-sm",
        d.highlighted && "ring-2 ring-green-400 shadow-lg shadow-green-200/50",
        d.dimmed && "opacity-40 transition-opacity duration-300",
        selected && !d.highlighted && "ring-2 ring-pd-green-500",
        d.hasIssue && "border-red-500 animate-pulse"
      )}
    >
      <StatusBadge status={d.status} />
      <Handle type="target" position={Position.Top} className="!bg-slate-400" />
      <div className="flex items-center gap-1.5">
        {/* Table icon */}
        <svg
          className={cn(
            "w-3.5 h-3.5 flex-shrink-0",
            d.hasIssue ? "text-red-500" : "text-slate-500"
          )}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={2}
        >
          <rect x="3" y="3" width="18" height="18" rx="2" />
          <path d="M3 9h18M3 15h18M9 3v18" />
        </svg>
        <div className="min-w-0">
          <div className="text-[11px] font-semibold text-slate-700 truncate">
            {d.label}
          </div>
          <div className="text-[10px] text-slate-400">
            {raw.is_main ? "Main" : "Custom"} &middot;{" "}
            {raw.routes?.length ?? 0} routes
          </div>
        </div>
      </div>
      <Handle
        type="source"
        position={Position.Bottom}
        className="!bg-slate-400"
      />
    </div>
  );
}

export const RouteTableNode = memo(RouteTableNodeInner);
