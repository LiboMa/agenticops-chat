import { memo } from "react";
import {
  BaseEdge,
  EdgeLabelRenderer,
  getBezierPath,
  type EdgeProps,
} from "@xyflow/react";

type EdgeStyle = "solid" | "dashed" | "dotted" | "blackhole";

function TopologyEdgeInner({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  data,
  selected,
}: EdgeProps) {
  const style = ((data as Record<string, unknown>)?.style as EdgeStyle) ?? "solid";
  const label = ((data as Record<string, unknown>)?.label as string) ?? "";

  const [edgePath, labelX, labelY] = getBezierPath({
    sourceX,
    sourceY,
    targetX,
    targetY,
    sourcePosition,
    targetPosition,
  });

  const isBlackhole = style === "blackhole";

  // Stroke style
  const strokeColor = isBlackhole ? "#ef4444" : "#9ca3af";
  const strokeWidth = isBlackhole ? 2 : 1.5;
  const strokeDasharray =
    style === "dashed"
      ? "6 3"
      : style === "dotted"
        ? "2 4"
        : isBlackhole
          ? "8 4"
          : undefined;

  return (
    <>
      {/* Animated glow behind blackhole edges */}
      {isBlackhole && (
        <BaseEdge
          id={`${id}-glow`}
          path={edgePath}
          style={{
            stroke: "#ef4444",
            strokeWidth: 5,
            strokeDasharray: "8 4",
            opacity: 0.3,
            animation: "blackhole-flow 1s linear infinite",
          }}
        />
      )}

      <BaseEdge
        id={id}
        path={edgePath}
        style={{
          stroke: selected ? "#05A82D" : strokeColor,
          strokeWidth,
          strokeDasharray,
          ...(isBlackhole
            ? { animation: "blackhole-flow 1s linear infinite" }
            : {}),
        }}
        markerEnd={isBlackhole ? undefined : "url(#arrow)"}
      />

      {label && (
        <EdgeLabelRenderer>
          <div
            style={{
              position: "absolute",
              transform: `translate(-50%, -50%) translate(${labelX}px,${labelY}px)`,
              pointerEvents: "all",
            }}
            className={`text-[10px] font-mono px-1.5 py-0.5 rounded ${
              isBlackhole
                ? "bg-red-100 text-red-700 border border-red-300"
                : "bg-white text-gray-500 border border-gray-200"
            }`}
          >
            {label}
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  );
}

export const TopologyEdge = memo(TopologyEdgeInner);
