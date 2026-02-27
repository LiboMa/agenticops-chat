import { memo } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import { cn } from "@/lib/cn";
import type { BaseNodeData } from "../types";
import { StatusBadge } from "./StatusBadge";

function CacheNodeInner({ data, selected }: NodeProps) {
  const d = data as BaseNodeData;
  const raw = d.raw as { engine?: string; protocol?: string };

  return (
    <div
      className={cn(
        "relative rounded-lg border-2 border-pink-400 bg-gradient-to-br from-pink-50 to-rose-50 px-3 py-2 min-w-[180px] shadow-sm transition-all duration-200 hover:shadow-md hover:-translate-y-0.5",
        d.highlighted && "ring-2 ring-green-400 shadow-lg shadow-green-200/50",
        d.dimmed && "opacity-40 transition-opacity duration-300",
        selected && !d.highlighted && "ring-2 ring-pd-green-500"
      )}
    >
      {/* Pink accent bar */}
      <div className="absolute left-0 top-2 bottom-2 w-1 rounded-full bg-pink-400" />
      <StatusBadge status={d.status} />
      <Handle type="target" position={Position.Top} className="!bg-pink-400" />
      <div className="flex items-center gap-2 pl-1.5">
        {/* Lightning/cache icon */}
        <svg
          className="w-5 h-5 text-pink-600 flex-shrink-0"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={2}
        >
          <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z" />
        </svg>
        <div className="min-w-0">
          <div className="text-xs font-semibold text-pink-800 truncate">
            {d.label}
          </div>
          <div className="text-[10px] text-pink-500">
            {d.resourceType} &middot; {raw.engine ?? raw.protocol ?? ""}
          </div>
        </div>
      </div>
      <Handle
        type="source"
        position={Position.Bottom}
        className="!bg-pink-400"
      />
    </div>
  );
}

export const CacheNode = memo(CacheNodeInner);
