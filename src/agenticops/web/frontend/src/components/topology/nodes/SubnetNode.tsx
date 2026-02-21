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
        "relative rounded-lg border-2 px-3 py-2 min-w-[180px] shadow-sm bg-white transition-all duration-200 hover:shadow-md hover:-translate-y-0.5",
        isPublic
          ? "border-green-400 bg-gradient-to-br from-green-50 to-emerald-50"
          : "border-gray-300 bg-gradient-to-br from-gray-50 to-slate-50",
        d.highlighted && "ring-2 ring-green-400 shadow-lg shadow-green-200/50",
        d.dimmed && "opacity-40 transition-opacity duration-300",
        selected && !d.highlighted && "ring-2 ring-pd-green-500",
        d.hasIssue && "border-red-500 animate-pulse"
      )}
    >
      {/* Colored accent bar */}
      <div
        className={cn(
          "absolute left-0 top-2 bottom-2 w-1 rounded-full",
          isPublic ? "bg-green-400" : "bg-gray-400"
        )}
      />
      <StatusBadge status={d.status} />
      <Handle type="target" position={Position.Top} className="!bg-gray-400" />
      <div className="flex items-center gap-2 pl-1.5">
        <span
          className={cn(
            "w-3 h-3 rounded-full flex-shrink-0",
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
