import { memo } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import { cn } from "@/lib/cn";
import type { BaseNodeData } from "../types";
import { StatusBadge } from "./StatusBadge";

function Ec2NodeInner({ data, selected }: NodeProps) {
  const d = data as BaseNodeData;
  const raw = d.raw as { instance_type?: string; state?: string };

  return (
    <div
      className={cn(
        "relative rounded-lg border-2 border-orange-400 bg-gradient-to-br from-orange-50 to-amber-50 px-3 py-2 min-w-[180px] shadow-sm transition-all duration-200 hover:shadow-md hover:-translate-y-0.5",
        d.highlighted && "ring-2 ring-green-400 shadow-lg shadow-green-200/50",
        d.dimmed && "opacity-40 transition-opacity duration-300",
        selected && !d.highlighted && "ring-2 ring-pd-green-500"
      )}
    >
      {/* Orange accent bar */}
      <div className="absolute left-0 top-2 bottom-2 w-1 rounded-full bg-orange-400" />
      <StatusBadge status={d.status} />
      <Handle type="target" position={Position.Top} className="!bg-orange-400" />
      <div className="flex items-center gap-2 pl-1.5">
        {/* Server icon */}
        <svg
          className="w-5 h-5 text-orange-600 flex-shrink-0"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={2}
        >
          <rect x="2" y="3" width="20" height="8" rx="2" />
          <rect x="2" y="13" width="20" height="8" rx="2" />
          <path d="M6 7h.01M6 17h.01" />
        </svg>
        <div className="min-w-0">
          <div className="text-xs font-semibold text-orange-800 truncate">
            {d.label}
          </div>
          <div className="text-[10px] text-orange-500">
            {raw.instance_type ?? "EC2"} &middot; {raw.state ?? "unknown"}
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

export const Ec2Node = memo(Ec2NodeInner);
