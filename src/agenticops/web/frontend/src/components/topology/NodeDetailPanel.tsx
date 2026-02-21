import { memo } from "react";
import type { Node } from "@xyflow/react";
import type { BaseNodeData } from "./types";

interface NodeDetailPanelProps {
  node: Node<BaseNodeData> | null;
  onClose: () => void;
}

/** Key-value row in the detail panel */
function DetailRow({ label, value }: { label: string; value: string | number | boolean | null | undefined }) {
  if (value === null || value === undefined) return null;
  return (
    <div className="flex justify-between gap-2 py-1 border-b border-gray-100 last:border-0">
      <span className="text-xs text-gray-500 flex-shrink-0">{label}</span>
      <span className="text-xs font-mono text-gray-800 text-right truncate">
        {String(value)}
      </span>
    </div>
  );
}

function NodeDetailPanelInner({ node, onClose }: NodeDetailPanelProps) {
  if (!node) return null;

  const d = node.data;
  const raw = d.raw as Record<string, unknown>;

  // Flatten raw fields for display, skipping complex nested objects
  const entries = Object.entries(raw).filter(
    ([, v]) => typeof v !== "object" || v === null
  );

  // Arrays of strings (like associated_subnets, route_table_ids) — show as comma-separated
  const arrayEntries = Object.entries(raw).filter(
    ([, v]) => Array.isArray(v) && v.every((item) => typeof item === "string")
  );

  return (
    <div className="absolute top-0 right-0 w-72 h-full bg-white border-l border-gray-200 shadow-lg overflow-y-auto z-10">
      {/* Header */}
      <div className="sticky top-0 bg-white border-b border-gray-200 px-4 py-3 flex items-center justify-between">
        <div>
          <div className="text-sm font-semibold text-gray-900">{d.label}</div>
          <div className="text-xs text-gray-500">{d.resourceType}</div>
        </div>
        <button
          onClick={onClose}
          className="text-gray-400 hover:text-gray-600 transition-colors"
          aria-label="Close panel"
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      {/* Issue banner */}
      {d.hasIssue && (
        <div className="mx-4 mt-3 px-3 py-2 bg-red-50 border border-red-200 rounded text-xs text-red-700">
          This resource has blackhole routes
        </div>
      )}

      {/* Scalar fields */}
      <div className="px-4 py-3">
        <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">
          Properties
        </h4>
        {entries.map(([key, value]) => (
          <DetailRow key={key} label={key} value={value as string | number | boolean | null} />
        ))}
      </div>

      {/* Array fields */}
      {arrayEntries.length > 0 && (
        <div className="px-4 pb-3">
          <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">
            Associations
          </h4>
          {arrayEntries.map(([key, value]) => (
            <div key={key} className="mb-2">
              <div className="text-xs text-gray-500 mb-1">{key}</div>
              <div className="flex flex-wrap gap-1">
                {(value as string[]).map((item) => (
                  <span
                    key={item}
                    className="text-[10px] font-mono bg-gray-100 text-gray-700 px-1.5 py-0.5 rounded"
                  >
                    {item}
                  </span>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export const NodeDetailPanel = memo(NodeDetailPanelInner);
