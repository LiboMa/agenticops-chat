import { cn } from "@/lib/cn";

interface StatCardProps {
  label: string;
  value: number | string;
  colorClass?: string;
}

export function StatCard({
  label,
  value,
  colorClass = "text-foreground",
}: StatCardProps) {
  return (
    <div className="bg-card border rounded-lg px-5 py-4">
      <div className="text-[11px] font-medium tracking-[0.1em] uppercase text-muted-foreground mb-1.5">
        {label}
      </div>
      <div className={cn("text-3xl font-light tracking-tight font-mono", colorClass)}>
        {value}
      </div>
    </div>
  );
}
