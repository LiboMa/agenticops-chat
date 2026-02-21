import { memo } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import { cn } from "@/lib/cn";
import type { BaseNodeData } from "../types";
import { StatusBadge } from "./StatusBadge";

function SubnetNodeInner({ data, selected }: NodeProps) {
  const d = data as BaseNodeData;
  const raw = d.raw as { type?: string; az?: string; cidr?: string };
  const isPublic = raw.type === "public";

  return (
    <div
      className={cn(
        "relative rounded-lg border-2 px-3 py-2 min-w-[180px] shadow-sm bg-white",
        isPublic
          ? "border-green-400 bg-green-50"
          : "border-gray-300 bg-gray-50",
        d.highlighted && "ring-2 ring-green-400 shadow-lg shadow-green-200/50",
        d.dimmed && "opacity-40 transition-opacity duration-300",
        selected && !d.highlighted && "ring-2 ring-pd-green-500",
        d.hasIssue && "border-red-500 animate-pulse"
      )}
    >
      <StatusBadge status={d.status} />
      <Handle type="target" position={Position.Top} className="!bg-gray-400" />
      <div className="flex items-center gap-2">
        <span
          className={cn(
            "w-2.5 h-2.5 rounded-full flex-shrink-0",
            isPublic ? "bg-green-500" : "bg-gray-400"
          )}
        />
        <div className="min-w-0">
          <div className="text-xs font-semibold text-gray-800 truncate">
            {d.label}
          </div>
          <div className="text-[10px] text-gray-500 font-mono">
            {raw.az} &middot; {raw.cidr}
          </div>
        </div>
      </div>
      <Handle
        type="source"
        position={Position.Bottom}
        className="!bg-gray-400"
      />
    </div>
  );
}

export const SubnetNode = memo(SubnetNodeInner);
