import { memo } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";
import { cn } from "@/lib/cn";
import type { TgwNodeData } from "../types";

function TgwHubNodeInner({ data, selected }: NodeProps) {
  const d = data as TgwNodeData;
  const isHealthy = d.state === "available";

  return (
    <div
      className={cn(
        "relative rounded-xl border-2 border-purple-400 bg-gradient-to-br from-purple-50 to-fuchsia-50 px-5 py-4 min-w-[220px] shadow-md transition-all duration-200 hover:shadow-lg hover:-translate-y-0.5",
        selected && "ring-2 ring-pd-green-500",
      )}
    >
      {/* Purple accent bar */}
      <div className="absolute left-0 top-3 bottom-3 w-1 rounded-full bg-purple-400" />
      <Handle type="target" position={Position.Top} className="!bg-purple-500" />
      <div className="flex items-center gap-3 pl-1">
        {/* TGW hub icon */}
        <div className="w-10 h-10 rounded-lg bg-purple-200 flex items-center justify-center flex-shrink-0">
          <svg
            className="w-6 h-6 text-purple-700"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={1.5}
          >
            <circle cx="12" cy="12" r="3" />
            <path d="M12 2v7M12 15v7M2 12h7M15 12h7" />
            <path d="M4.93 4.93l4.95 4.95M14.12 14.12l4.95 4.95M4.93 19.07l4.95-4.95M14.12 9.88l4.95-4.95" />
          </svg>
        </div>
        <div className="min-w-0">
          <div className="text-sm font-semibold text-purple-800 truncate">{d.label}</div>
          <div className="text-xs text-purple-500">
            Transit Gateway
          </div>
          <div className="text-[10px] text-gray-400 mt-0.5">
            {d.attachmentCount} attachments ·{" "}
            <span className={isHealthy ? "text-green-600" : "text-yellow-600"}>
              {d.state}
            </span>
          </div>
        </div>
      </div>
      <Handle type="source" position={Position.Bottom} className="!bg-purple-500" />
    </div>
  );
}

export const TgwHubNode = memo(TgwHubNodeInner);
