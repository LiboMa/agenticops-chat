import { memo } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import { cn } from "@/lib/cn";
import type { BaseNodeData } from "../types";
import { StatusBadge } from "./StatusBadge";

function IGWNodeInner({ data, selected }: NodeProps) {
  const d = data as BaseNodeData;

  return (
    <div
      className={cn(
        "relative rounded-lg border-2 border-blue-400 bg-gradient-to-br from-blue-50 to-sky-50 px-3 py-2 min-w-[180px] shadow-sm transition-all duration-200 hover:shadow-md hover:-translate-y-0.5",
        d.highlighted && "ring-2 ring-green-400 shadow-lg shadow-green-200/50",
        d.dimmed && "opacity-40 transition-opacity duration-300",
        selected && !d.highlighted && "ring-2 ring-pd-green-500"
      )}
    >
      {/* Blue accent bar */}
      <div className="absolute left-0 top-2 bottom-2 w-1 rounded-full bg-blue-400" />
      <StatusBadge status={d.status} />
      <div className="flex items-center gap-2 pl-1.5">
        {/* Globe icon */}
        <svg
          className="w-5 h-5 text-blue-600 flex-shrink-0"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={2}
        >
          <circle cx="12" cy="12" r="10" />
          <path d="M2 12h20M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" />
        </svg>
        <div className="min-w-0">
          <div className="text-xs font-semibold text-blue-800 truncate">
            {d.label}
          </div>
          <div className="text-[10px] text-blue-500">Internet Gateway</div>
        </div>
      </div>
      <Handle
        type="source"
        position={Position.Bottom}
        className="!bg-blue-400"
      />
    </div>
  );
}

export const IGWNode = memo(IGWNodeInner);
