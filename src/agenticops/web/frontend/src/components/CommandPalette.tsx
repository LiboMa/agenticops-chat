import { useState, useEffect, useRef, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { useSearch } from "@/hooks/useSearch";
import type { SearchResultItem } from "@/api/types";

interface CommandPaletteProps {
  open: boolean;
  onClose: () => void;
}

const ENTITY_STYLES: Record<string, { label: string; badge: string }> = {
  issue: { label: "Issues", badge: "text-red-700 bg-red-100" },
  fix_plan: { label: "Fix Plans", badge: "text-blue-700 bg-blue-100" },
  report: { label: "Reports", badge: "text-emerald-700 bg-emerald-100" },
  resource: { label: "Resources", badge: "text-cyan-700 bg-cyan-100" },
};

function entityRoute(item: SearchResultItem): string {
  switch (item.entity_type) {
    case "issue":
      return `/app/issues/${item.id}`;
    case "fix_plan":
      return `/app/issues/${item.parent_id ?? item.id}`;
    case "report":
      return `/app/reports/${item.id}`;
    case "resource":
      return `/app/resources/${item.id}`;
  }
}

function badgeText(item: SearchResultItem): string {
  return item.severity ?? item.status ?? item.report_type ?? item.entity_type;
}

export function CommandPalette({ open, onClose }: CommandPaletteProps) {
  const navigate = useNavigate();
  const inputRef = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [selectedIndex, setSelectedIndex] = useState(0);

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedQuery(query), 300);
    return () => clearTimeout(timer);
  }, [query]);

  useEffect(() => {
    if (open) {
      setQuery("");
      setDebouncedQuery("");
      setSelectedIndex(0);
      setTimeout(() => inputRef.current?.focus(), 0);
    }
  }, [open]);

  const { data, isLoading } = useSearch(debouncedQuery);

  const flatResults = useMemo(() => {
    if (!data?.results) return [];
    return [
      ...data.results.issues,
      ...data.results.fix_plans,
      ...data.results.reports,
      ...(data.results.resources ?? []),
    ];
  }, [data]);

  useEffect(() => {
    setSelectedIndex(0);
  }, [flatResults]);

  function navigateToItem(item: SearchResultItem) {
    navigate(entityRoute(item));
    onClose();
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Escape") {
      onClose();
      return;
    }
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setSelectedIndex((i) => (flatResults.length ? (i + 1) % flatResults.length : 0));
      return;
    }
    if (e.key === "ArrowUp") {
      e.preventDefault();
      setSelectedIndex((i) => (flatResults.length ? (i - 1 + flatResults.length) % flatResults.length : 0));
      return;
    }
    if (e.key === "Enter" && flatResults[selectedIndex]) {
      e.preventDefault();
      navigateToItem(flatResults[selectedIndex]);
    }
  }

  if (!open) return null;

  const issues = data?.results.issues ?? [];
  const fixPlans = data?.results.fix_plans ?? [];
  const reports = data?.results.reports ?? [];
  const resources = data?.results.resources ?? [];

  let runningIndex = 0;

  function renderSection(label: string, items: SearchResultItem[], entityType: string) {
    if (items.length === 0) return null;
    const startIdx = runningIndex;
    runningIndex += items.length;
    const style = ENTITY_STYLES[entityType];
    return (
      <div key={entityType}>
        <div className="px-3 py-1.5 text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">
          {label} ({items.length})
        </div>
        {items.map((item, i) => {
          const idx = startIdx + i;
          return (
            <div
              key={`${entityType}-${item.id}`}
              onClick={() => navigateToItem(item)}
              className={`px-3 py-2 cursor-pointer flex items-center gap-3 ${
                idx === selectedIndex ? "bg-accent" : "hover:bg-accent/50"
              }`}
            >
              <div className="flex-1 min-w-0">
                <div className="font-medium text-sm truncate">{item.title}</div>
                <div className="text-xs text-muted-foreground truncate">{item.subtitle}</div>
              </div>
              <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded-md whitespace-nowrap ${style.badge}`}>
                {badgeText(item)}
              </span>
            </div>
          );
        })}
      </div>
    );
  }

  return (
    <div className="fixed inset-0 z-50 bg-black/40" onClick={onClose}>
      <div className="flex items-start justify-center pt-[20vh]">
        <div
          className="bg-background rounded-xl shadow-2xl w-full max-w-lg mx-4 border border-border overflow-hidden"
          onClick={(e) => e.stopPropagation()}
          onKeyDown={handleKeyDown}
        >
          <div className="flex items-center border-b px-3">
            <svg className="h-4 w-4 text-muted-foreground shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
            <input
              ref={inputRef}
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search issues, fix plans, reports, resources..."
              className="flex-1 bg-transparent py-3 px-3 text-sm outline-none placeholder:text-muted-foreground"
            />
            <kbd className="text-[10px] text-muted-foreground bg-secondary px-1.5 py-0.5 rounded font-mono border border-border">
              ESC
            </kbd>
          </div>

          <div className="max-h-[60vh] overflow-y-auto">
            {!debouncedQuery && (
              <div className="py-12 text-center text-sm text-muted-foreground">
                Type to search...
              </div>
            )}

            {debouncedQuery && isLoading && (
              <div className="py-12 flex justify-center">
                <div className="h-5 w-5 border-2 border-primary border-t-transparent rounded-full animate-spin" />
              </div>
            )}

            {debouncedQuery && !isLoading && flatResults.length === 0 && (
              <div className="py-12 text-center text-sm text-muted-foreground">
                No results for &apos;{debouncedQuery}&apos;
              </div>
            )}

            {debouncedQuery && !isLoading && flatResults.length > 0 && (
              <div className="py-1">
                {renderSection(ENTITY_STYLES.issue.label, issues, "issue")}
                {renderSection(ENTITY_STYLES.fix_plan.label, fixPlans, "fix_plan")}
                {renderSection(ENTITY_STYLES.report.label, reports, "report")}
                {renderSection(ENTITY_STYLES.resource.label, resources, "resource")}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
