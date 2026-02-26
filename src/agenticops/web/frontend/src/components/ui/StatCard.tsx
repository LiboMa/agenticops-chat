import { cn } from "@/lib/cn";

interface StatCardProps {
  label: string;
  value: number | string;
  colorClass?: string;
}

export function StatCard({
  label,
  value,
  colorClass = "text-slate-900",
}: StatCardProps) {
  return (
    <div className="bg-white border border-slate-200 rounded-xl shadow-card p-6">
      <div className="text-sm font-medium text-slate-500">
        {label}
      </div>
      <div className={cn("text-3xl font-semibold mt-1", colorClass)}>{value}</div>
    </div>
  );
}
