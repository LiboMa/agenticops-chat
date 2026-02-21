import { memo } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import { cn } from "@/lib/cn";
import type { VpcNodeData } from "../types";

function VpcGroupNodeInner({ data, selected }: NodeProps) {
  const d = data as VpcNodeData;
  const isExternal = d.state === "external";

  return (
    <div
      className={cn(
        "relative rounded-xl border-2 px-5 py-4 min-w-[220px] shadow-md",
        isExternal
          ? "border-dashed border-gray-300 bg-gray-50"
          : "border-emerald-400 bg-emerald-50",
        selected && "ring-2 ring-pd-green-500",
      )}
    >
      <Handle type="target" position={Position.Top} className="!bg-emerald-500" />
      <div className="flex items-center gap-3">
        {/* VPC icon */}
        <div
          className={cn(
            "w-10 h-10 rounded-lg flex items-center justify-center flex-shrink-0",
            isExternal ? "bg-gray-200" : "bg-emerald-200",
          )}
        >
          <svg
            className={cn("w-5 h-5", isExternal ? "text-gray-500" : "text-emerald-700")}
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={1.5}
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M2.25 15a4.5 4.5 0 004.5 4.5H18a3.75 3.75 0 001.332-7.257 3 3 0 00-3.758-3.848 5.25 5.25 0 00-10.233 2.33A4.502 4.502 0 002.25 15z"
            />
          </svg>
        </div>
        <div className="min-w-0">
          <div className="text-sm font-semibold text-gray-800 truncate">{d.label}</div>
          <div className="text-xs text-gray-500 font-mono">{d.cidr}</div>
          {!isExternal && (
            <div className="text-[10px] text-gray-400 mt-0.5">
              {d.subnetCount} subnets{d.isDefault ? " · default" : ""}
            </div>
          )}
        </div>
      </div>
      <Handle type="source" position={Position.Bottom} className="!bg-emerald-500" />
    </div>
  );
}

export const VpcGroupNode = memo(VpcGroupNodeInner);
