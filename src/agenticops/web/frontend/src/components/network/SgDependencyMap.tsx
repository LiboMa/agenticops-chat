import { useState, useMemo } from "react";
import { Card } from "@/components/ui/Card";
import type { SgDependencyMap as SgDependencyMapType } from "@/api/types";

interface SgDependencyMapProps {
  dependencies: SgDependencyMapType;
}

export function SgDependencyMap({ dependencies }: SgDependencyMapProps) {
  const [isOpen, setIsOpen] = useState(false);

  const entries = useMemo(
    () => Object.entries(dependencies),
    [dependencies],
  );

  if (entries.length === 0) return null;

  return (
    <Card>
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="w-full px-6 py-4 flex items-center justify-between hover:bg-gray-50 transition-colors"
      >
        <span className="text-lg font-semibold text-gray-900">
          Security Group Dependencies ({entries.length})
        </span>
        <svg
          className={`h-5 w-5 text-gray-400 transition-transform ${isOpen ? "rotate-180" : ""}`}
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={2}
            d="M19 9l-7 7-7-7"
          />
        </svg>
      </button>

      {isOpen && (
        <div className="px-6 pb-4 overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-gray-500 text-xs uppercase tracking-wider">
                <th className="pb-2 pr-4">SG ID</th>
                <th className="pb-2 pr-4">Name</th>
                <th className="pb-2 pr-4">References (outbound to)</th>
                <th className="pb-2">Referenced By (inbound from)</th>
              </tr>
            </thead>
            <tbody>
              {entries.map(([sgId, sg]) => (
                <tr key={sgId} className="border-t border-gray-200">
                  <td className="py-2 pr-4 font-mono">{sgId}</td>
                  <td className="py-2 pr-4">{sg.name ?? "-"}</td>
                  <td className="py-2 pr-4 text-xs">
                    {sg.references.length > 0
                      ? sg.references.join(", ")
                      : "-"}
                  </td>
                  <td className="py-2 text-xs">
                    {sg.referenced_by.length > 0
                      ? sg.referenced_by.join(", ")
                      : "-"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
