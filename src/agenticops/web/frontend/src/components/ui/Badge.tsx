import React from "react";
import { cn } from "@/lib/cn";

interface BadgeProps {
  children: React.ReactNode;
  className?: string;
}

export const Badge = React.memo(function Badge({
  children,
  className,
}: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center px-2.5 py-0.5 rounded-full border border-slate-200 text-xs font-medium",
        className,
      )}
    >
      {children}
    </span>
  );
});
