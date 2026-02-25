import { cn } from "@/lib/cn";

interface StatCardProps {
  label: string;
  value: number | string;
  colorClass?: string;
}

export function StatCard({
  label,
  value,
  colorClass = "text-gray-900",
}: StatCardProps) {
  return (
    <div className="bg-white rounded-lg shadow-card p-6">
      <div className="text-sm font-medium text-gray-500 uppercase tracking-wider">
        {label}
      </div>
      <div className={cn("text-3xl font-bold mt-1", colorClass)}>{value}</div>
    </div>
  );
}
