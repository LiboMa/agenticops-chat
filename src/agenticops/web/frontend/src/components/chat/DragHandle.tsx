import { useCallback, useRef, useEffect } from "react";

interface Props {
  onResize: (fraction: number) => void;
  min?: number;
  max?: number;
}

export function DragHandle({ onResize, min = 0.3, max = 0.7 }: Props) {
  const dragging = useRef(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    dragging.current = true;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
  }, []);

  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (!dragging.current) return;
      const parent = containerRef.current?.parentElement;
      if (!parent) return;
      const rect = parent.getBoundingClientRect();
      const fraction = (e.clientX - rect.left) / rect.width;
      onResize(Math.min(max, Math.max(min, fraction)));
    };

    const handleMouseUp = () => {
      if (dragging.current) {
        dragging.current = false;
        document.body.style.cursor = "";
        document.body.style.userSelect = "";
      }
    };

    window.addEventListener("mousemove", handleMouseMove);
    window.addEventListener("mouseup", handleMouseUp);
    return () => {
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("mouseup", handleMouseUp);
    };
  }, [onResize, min, max]);

  return (
    <div
      ref={containerRef}
      onMouseDown={handleMouseDown}
      className="w-[6px] flex-shrink-0 cursor-col-resize group flex items-center justify-center hover:bg-indigo-500/20 transition-colors"
    >
      <div className="w-[2px] h-8 rounded-full bg-slate-600 group-hover:bg-indigo-400 transition-colors" />
    </div>
  );
}
