import { memo } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import { cn } from "@/lib/cn";
import type { BaseNodeData } from "../types";
import { StatusBadge } from "./StatusBadge";

function PeeringNodeInner({ data, selected }: NodeProps) {
  const d = data as BaseNodeData;
  const raw = d.raw as {
    requester_vpc?: string;
    accepter_vpc?: string;
    status?: string;
  };

  return (
    <div
      className={cn(
        "relative rounded-lg border-2 border-teal-400 bg-teal-50 px-3 py-2 min-w-[180px] shadow-sm",
        d.highlighted && "ring-2 ring-green-400 shadow-lg shadow-green-200/50",
        d.dimmed && "opacity-40 transition-opacity duration-300",
        selected && !d.highlighted && "ring-2 ring-pd-green-500"
      )}
    >
      <StatusBadge status={d.status} />
      <div className="flex items-center gap-2">
        {/* Link icon */}
        <svg
          className="w-4 h-4 text-teal-600 flex-shrink-0"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={2}
        >
          <path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71" />
          <path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71" />
        </svg>
        <div className="min-w-0">
          <div className="text-xs font-semibold text-teal-800 truncate">
            {d.label}
          </div>
          <div className="text-[10px] text-teal-500 truncate">
            {raw.requester_vpc} ↔ {raw.accepter_vpc}
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

export const PeeringNode = memo(PeeringNodeInner);
