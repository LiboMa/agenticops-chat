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
  const isHighlighted = ((data as Record<string, unknown>)?.highlighted as boolean) ?? false;

  // Smoother curves with increased curvature offset
  const curvatureOffset = Math.abs(targetX - sourceX) * 0.15;
  const [edgePath, labelX, labelY] = getBezierPath({
    sourceX,
    sourceY,
    targetX,
    targetY,
    sourcePosition,
    targetPosition,
    curvature: curvatureOffset > 20 ? 0.35 : 0.25,
  });

  const isBlackhole = style === "blackhole";

  // Stroke style — blackhole edges are never overridden by highlight
  const strokeColor = isBlackhole
    ? "#ef4444"
    : isHighlighted
      ? "#4ade80"
      : "#9ca3af";
  const strokeWidth = isBlackhole ? 2 : isHighlighted ? 3 : 1.5;
  const hoverStrokeWidth = isBlackhole ? 3 : isHighlighted ? 4 : 2.5;
  const strokeDasharray =
    style === "dashed"
      ? "6 3"
      : style === "dotted"
        ? "2 4"
        : isBlackhole
          ? "8 4"
          : undefined;

  const markerEnd = isBlackhole
    ? undefined
    : isHighlighted
      ? "url(#arrow-highlighted)"
      : "url(#arrow)";

  return (
    <>
      {/* Invisible wider hit area for hover detection */}
      <BaseEdge
        id={`${id}-hitarea`}
        path={edgePath}
        style={{
          stroke: "transparent",
          strokeWidth: 12,
          fill: "none",
        }}
        className="group"
      />

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

      {/* Green glow behind highlighted edges */}
      {isHighlighted && !isBlackhole && (
        <BaseEdge
          id={`${id}-highlight-glow`}
          path={edgePath}
          style={{
            stroke: "#4ade80",
            strokeWidth: 6,
            opacity: 0.25,
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
          transition: "stroke-width 150ms ease",
          ...(isBlackhole
            ? { animation: "blackhole-flow 1s linear infinite" }
            : {}),
        }}
        markerEnd={markerEnd}
        className="hover:[stroke-width:var(--hover-width)]"
        interactionWidth={12}
      />

      {/* CSS variable for hover width */}
      <style>{`
        [data-id="${id}"]:hover { stroke-width: ${hoverStrokeWidth}; }
      `}</style>

      {label && (
        <EdgeLabelRenderer>
          <div
            style={{
              position: "absolute",
              transform: `translate(-50%, -50%) translate(${labelX}px,${labelY}px)`,
              pointerEvents: "all",
            }}
            className={`text-[10px] font-mono px-1.5 py-0.5 rounded backdrop-blur-sm ${
              isBlackhole
                ? "bg-red-100/90 text-red-700 border border-red-300"
                : "bg-white/80 text-gray-500 border border-gray-200"
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
