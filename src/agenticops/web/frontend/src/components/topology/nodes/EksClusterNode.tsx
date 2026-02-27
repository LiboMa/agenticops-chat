import { memo } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import { cn } from "@/lib/cn";
import type { BaseNodeData } from "../types";
import { StatusBadge } from "./StatusBadge";

function EksClusterNodeInner({ data, selected }: NodeProps) {
  const d = data as BaseNodeData;
  const raw = d.raw as { version?: string; status?: string };

  return (
    <div
      className={cn(
        "relative rounded-lg border-2 border-teal-400 bg-gradient-to-br from-teal-50 to-cyan-50 px-3 py-2 min-w-[200px] shadow-sm transition-all duration-200 hover:shadow-md hover:-translate-y-0.5",
        d.highlighted && "ring-2 ring-green-400 shadow-lg shadow-green-200/50",
        d.dimmed && "opacity-40 transition-opacity duration-300",
        selected && !d.highlighted && "ring-2 ring-pd-green-500"
      )}
    >
      {/* Teal accent bar */}
      <div className="absolute left-0 top-2 bottom-2 w-1 rounded-full bg-teal-400" />
      <StatusBadge status={d.status} />
      <Handle type="target" position={Position.Top} className="!bg-teal-400" />
      <div className="flex items-center gap-2 pl-1.5">
        {/* Kubernetes wheel icon */}
        <svg
          className="w-5 h-5 text-teal-600 flex-shrink-0"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={2}
        >
          <circle cx="12" cy="12" r="9" />
          <circle cx="12" cy="12" r="3" />
          <path d="M12 3v6M12 15v6M3 12h6M15 12h6M5.6 5.6l4.3 4.3M14.1 14.1l4.3 4.3M5.6 18.4l4.3-4.3M14.1 9.9l4.3-4.3" />
        </svg>
        <div className="min-w-0">
          <div className="text-xs font-semibold text-teal-800 truncate">
            {d.label}
          </div>
          <div className="text-[10px] text-teal-500">
            {d.resourceType} {raw.version ? `v${raw.version}` : ""} &middot; {raw.status ?? "unknown"}
          </div>
        </div>
      </div>
      <Handle
        type="source"
        position={Position.Bottom}
        className="!bg-teal-400"
      />
    </div>
  );
}

export const EksClusterNode = memo(EksClusterNodeInner);
