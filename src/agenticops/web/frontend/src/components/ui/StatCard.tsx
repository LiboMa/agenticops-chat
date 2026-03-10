import { cn } from "@/lib/cn";

interface StatCardProps {
  label: string;
  value: number | string;
  colorClass?: string;
}

export function StatCard({
  label,
  value,
  colorClass = "text-[#ececec]",
}: StatCardProps) {
  return (
    <div className="bg-[#2f2f2f] border border-[#424242] rounded-xl p-6">
      <div className="text-xs font-medium text-[#9b9b9b] uppercase tracking-wider">
        {label}
      </div>
      <div className={cn("text-[32px] font-semibold mt-1", colorClass)}>{value}</div>
    </div>
  );
}
