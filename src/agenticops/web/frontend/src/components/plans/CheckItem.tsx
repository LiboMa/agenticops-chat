import { CommandBlock } from "./RunbookStep";

/** One declared check. `checkId` (pc-n, its position) is shown for post-checks: the id the executor reports
 *  against and a verdict's reason names. */
export function CheckItem({ item, checkId }: { item: unknown; checkId?: string }) {
  const isObj = typeof item === "object" && item !== null && !Array.isArray(item);
  const s = isObj ? (item as Record<string, unknown>) : null;
  const text = typeof item === "string" ? item : (s?.check ?? s?.description ?? s?.action);
  const command = s?.command as string | undefined;

  return (
    <li className="flex items-start gap-2 text-sm text-muted-foreground">
      <svg className="w-4 h-4 mt-0.5 flex-shrink-0 text-muted-foreground" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
      </svg>
      <div className="flex-1 min-w-0">
        {checkId && <span className="mr-1.5 font-mono text-xs text-muted-foreground">{checkId}</span>}
        <span>{typeof text === "string" ? text : JSON.stringify(item)}</span>
        {command && <CommandBlock command={command} />}
      </div>
    </li>
  );
}
