import { useState, useEffect, useLayoutEffect, useRef, useMemo, useId } from "react";
import * as Dialog from "@radix-ui/react-dialog";
import { useNavigate } from "react-router-dom";
import { useSearch } from "@/hooks/useSearch";
import { isComposingKey } from "@/lib/composerKeys";
import { useLocale } from "@/i18n/LocaleContext";
import type { SearchResultItem } from "@/api/types";

interface CommandPaletteProps {
  open: boolean;
  onClose: () => void;
}

// label = a locale key (palette.group.*)
const ENTITY_STYLES: Record<string, { label: string; badge: string }> = {
  issue: { label: "palette.group.issue", badge: "text-red-700 bg-red-100" },
  fix_plan: { label: "palette.group.fix_plan", badge: "text-blue-700 bg-blue-100" },
  report: { label: "palette.group.report", badge: "text-emerald-700 bg-emerald-100" },
  resource: { label: "palette.group.resource", badge: "text-cyan-700 bg-cyan-100" },
  change_plan: { label: "palette.group.change_plan", badge: "text-violet-700 bg-violet-100" },
  change_request: { label: "palette.group.change_request", badge: "text-violet-700 bg-violet-100" },
};

function entityRoute(item: SearchResultItem): string {
  switch (item.entity_type) {
    case "issue":
      return `/app/issues/${item.id}`;
    case "fix_plan":
      return `/app/plans/${item.id}`;
    case "report":
      return `/app/reports/${item.id}`;
    case "resource":
      return `/app/resources/${item.id}`;
    case "change_request":
      return `/app/changes/${item.id}`;
    case "change_plan":
      return item.parent_id != null ? `/app/changes/${item.parent_id}` : "/app/changes";
  }
}

function badgeText(item: SearchResultItem): string {
  return item.severity ?? item.status ?? item.report_type ?? item.entity_type;
}

/** The global search (MVP-2.8.0 S1): a Radix dialog (focus kept inside, Esc closes, focus returns to what opened it)
 *  around a combobox — the input owns the active option (aria-activedescendant), the results are a listbox, the
 *  count is announced, and a failed search says so instead of "no results". */
export function CommandPalette({ open, onClose }: CommandPaletteProps) {
  const { t } = useLocale();
  const navigate = useNavigate();
  const inputRef = useRef<HTMLInputElement>(null);
  const listboxId = useId();
  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [selectedIndex, setSelectedIndex] = useState(0);

  useEffect(() => {
    const timer = setTimeout(() => setDebouncedQuery(query), 300);
    return () => clearTimeout(timer);
  }, [query]);

  // Radix gives focus back to its Dialog.Trigger on close; the palette opens from a top-bar button or ⌘K, so it keeps
  // the opener itself — captured in a layout effect, before the dialog's focus scope moves focus into the input.
  const openerRef = useRef<HTMLElement | null>(null);
  useLayoutEffect(() => {
    if (open) openerRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  }, [open]);

  useEffect(() => {
    if (open) {
      setQuery("");
      setDebouncedQuery("");
      setSelectedIndex(0);
    }
  }, [open]);

  const { data, isLoading, isError, refetch } = useSearch(debouncedQuery);

  const flatResults = useMemo(() => {
    if (!data?.results) return [];
    return [
      ...data.results.issues,
      ...data.results.fix_plans,
      ...(data.results.change_requests ?? []),
      ...data.results.reports,
      ...(data.results.resources ?? []),
    ];
  }, [data]);

  useEffect(() => {
    setSelectedIndex(0);
  }, [flatResults]);

  const optionId = (idx: number) => `${listboxId}-opt-${idx}`;
  useEffect(() => {
    if (!open || !flatResults.length) return;
    document.getElementById(optionId(selectedIndex))?.scrollIntoView({ block: "nearest" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedIndex, open, flatResults.length]);

  function navigateToItem(item: SearchResultItem) {
    navigate(entityRoute(item));
    onClose();
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (isComposingKey(e.nativeEvent)) return; // an IME candidate key, not the palette's
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

  const issues = data?.results.issues ?? [];
  const fixPlans = data?.results.fix_plans ?? [];
  const changeRequests = data?.results.change_requests ?? [];
  const reports = data?.results.reports ?? [];
  const resources = data?.results.resources ?? [];
  const searching = !!debouncedQuery && isLoading;
  const failed = !!debouncedQuery && !isLoading && isError && !data;
  const showResults = !!debouncedQuery && !isLoading && !failed;
  const announce = !debouncedQuery || searching ? ""
    : failed ? t("palette.failed")
    : flatResults.length ? t("palette.resultCount").replace("{n}", String(flatResults.length))
    : t("palette.noResults").replace("{q}", () => debouncedQuery);

  let runningIndex = 0;

  function renderSection(label: string, items: SearchResultItem[], entityType: string) {
    if (items.length === 0) return null;
    const startIdx = runningIndex;
    runningIndex += items.length;
    const style = ENTITY_STYLES[entityType];
    return (
      <div key={entityType} role="group" aria-label={label}>
        <div role="presentation" className="px-3 py-1.5 text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">
          {label} ({items.length})
        </div>
        {items.map((item, i) => {
          const idx = startIdx + i;
          return (
            <div
              key={`${entityType}-${item.id}`}
              id={optionId(idx)}
              role="option"
              aria-selected={idx === selectedIndex}
              onClick={() => navigateToItem(item)}
              onMouseMove={() => setSelectedIndex(idx)}
              className={`px-3 py-2 cursor-pointer flex items-center gap-3 ${
                idx === selectedIndex ? "bg-accent" : "hover:bg-accent/50"
              }`}
            >
              <div className="flex-1 min-w-0">
                <div className="font-medium text-sm truncate">{item.title}</div>
                <div className="text-xs text-muted-foreground truncate">{item.subtitle}</div>
              </div>
              <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded-md whitespace-nowrap ${(ENTITY_STYLES[item.entity_type] ?? style).badge}`}>
                {badgeText(item)}
              </span>
            </div>
          );
        })}
      </div>
    );
  }

  return (
    <Dialog.Root open={open} onOpenChange={(v) => { if (!v) onClose(); }}>
      <Dialog.Portal>
        {/* centred by the overlay, not by a translate: the slideInRight keyframe owns `transform` */}
        <Dialog.Overlay className="fixed inset-0 z-50 grid items-start justify-items-center overflow-y-auto bg-black/40 px-4 pt-[20vh]">
        <Dialog.Content
          onOpenAutoFocus={(e) => { e.preventDefault(); inputRef.current?.focus(); }}
          onCloseAutoFocus={(e) => {
            const opener = openerRef.current;
            if (opener?.isConnected && opener !== document.body) { e.preventDefault(); opener.focus(); }
          }}
          onKeyDown={handleKeyDown}
          className="w-full max-w-lg overflow-hidden rounded-xl border border-border bg-background shadow-2xl animate-[slideInRight_0.2s_ease-out]"
        >
          <Dialog.Title className="sr-only">{t("palette.title")}</Dialog.Title>
          <Dialog.Description className="sr-only">{t("palette.hint")}</Dialog.Description>
          <div className="flex items-center border-b px-3">
            <svg className="h-4 w-4 text-muted-foreground shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden>
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
            <input
              ref={inputRef}
              type="text"
              role="combobox"
              aria-label={t("palette.title")}
              aria-expanded={showResults && flatResults.length > 0}
              aria-controls={listboxId}
              aria-autocomplete="list"
              aria-activedescendant={showResults && flatResults.length ? optionId(selectedIndex) : undefined}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder={t("palette.placeholder")}
              className="flex-1 bg-transparent py-3 px-3 text-sm outline-none placeholder:text-muted-foreground"
            />
            <kbd className="text-[10px] text-muted-foreground bg-secondary px-1.5 py-0.5 rounded font-mono border border-border">
              ESC
            </kbd>
          </div>

          <div aria-live="polite" className="sr-only">{announce}</div>

          <div id={listboxId} role="listbox" aria-label={t("palette.title")} className="max-h-[60vh] overflow-y-auto">
            {!debouncedQuery && (
              <div role="presentation" className="py-12 text-center text-sm text-muted-foreground">
                {t("palette.typeToSearch")}
              </div>
            )}

            {searching && (
              <div role="presentation" className="py-12 flex justify-center">
                <div className="h-5 w-5 border-2 border-primary border-t-transparent rounded-full animate-spin" />
              </div>
            )}

            {failed && (
              <div role="presentation" className="flex flex-col items-center gap-3 py-10 text-sm text-status-danger">
                {t("palette.failed")}
                <button type="button" onClick={() => void refetch()}
                        className="rounded-md border border-border px-3 py-1 text-xs text-foreground hover:bg-accent">
                  {t("common.retry")}
                </button>
              </div>
            )}

            {showResults && flatResults.length === 0 && (
              <div role="presentation" className="py-12 text-center text-sm text-muted-foreground">
                {t("palette.noResults").replace("{q}", () => debouncedQuery)}
              </div>
            )}

            {showResults && flatResults.length > 0 && (
              <div className="py-1">
                {renderSection(t(ENTITY_STYLES.issue.label), issues, "issue")}
                {renderSection(t(ENTITY_STYLES.fix_plan.label), fixPlans, "fix_plan")}
                {renderSection(t(ENTITY_STYLES.change_request.label), changeRequests, "change_request")}
                {renderSection(t(ENTITY_STYLES.report.label), reports, "report")}
                {renderSection(t(ENTITY_STYLES.resource.label), resources, "resource")}
              </div>
            )}
          </div>
        </Dialog.Content>
        </Dialog.Overlay>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
