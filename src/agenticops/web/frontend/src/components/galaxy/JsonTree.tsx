import { useState, useMemo } from "react";

/**
 * Restrained, collapsible JSON tree for the Galaxy raw_data panel.
 * - objects/arrays collapse (top level open); leaves show typed, truncated values
 * - per-node copy (value for leaves, sub-tree JSON for containers)
 * - `filter` (lowercased) hides non-matching branches and highlights hits
 * Near-monochrome by design (one soft accent for keys) — no rainbow.
 */

const MAX_STR = 140;

type Json = unknown;

function typeName(v: Json): string {
  if (v === null) return "null";
  if (Array.isArray(v)) return "array";
  return typeof v;
}
function isLeaf(v: Json): boolean {
  const t = typeName(v);
  return t !== "object" && t !== "array";
}

function copy(text: string) {
  if (navigator.clipboard) navigator.clipboard.writeText(text).catch(() => {});
}

function Highlight({ text, q }: { text: string; q: string }) {
  if (!q) return <>{text}</>;
  const i = text.toLowerCase().indexOf(q);
  if (i < 0) return <>{text}</>;
  return (
    <>
      {text.slice(0, i)}
      <span className="rounded-sm bg-amber-400/25">{text.slice(i, i + q.length)}</span>
      {text.slice(i + q.length)}
    </>
  );
}

function Leaf({ v, q }: { v: Json; q: string }) {
  const t = typeName(v);
  if (t === "string") {
    const s = v as string;
    const shown = s.length > MAX_STR ? s.slice(0, MAX_STR) + "…" : s;
    return <span className="text-[#9fb8d6] whitespace-pre-wrap break-all">"<Highlight text={shown} q={q} />"</span>;
  }
  if (t === "number") return <span className="text-[#c7b088]"><Highlight text={String(v)} q={q} /></span>;
  if (t === "boolean") return <span className="text-[#cc9999]">{String(v)}</span>;
  return <span className="text-[#6b6880]">null</span>;
}

/** Does this subtree contain a match? (key or leaf value) */
function subtreeMatches(key: string | null, val: Json, q: string): boolean {
  if (!q) return true;
  if (key !== null && key.toLowerCase().includes(q)) return true;
  if (isLeaf(val)) return String(val ?? "").toLowerCase().includes(q);
  const entries = Array.isArray(val) ? (val as Json[]).map((v, i) => [String(i), v] as const)
                                     : Object.entries(val as Record<string, Json>);
  return entries.some(([k, v]) => subtreeMatches(k, v, q));
}

function TreeNode({ k, v, depth, q, seedOpen }: {
  k: string | null; v: Json; depth: number; q: string; seedOpen: number | null;
}) {
  const leaf = isLeaf(v);
  // initial open state: expand-all/collapse-all seed wins, else top level open.
  // The whole tree remounts when the seed changes, so after that each node is
  // freely toggleable again (seed only sets the starting state).
  const [open, setOpen] = useState(seedOpen === 1 ? true : seedOpen === 0 ? (depth < 1) : depth < 1);
  const searching = q.length > 0;
  const effectiveOpen = searching ? true : open;

  if (searching && !subtreeMatches(k, v, q)) return null;

  const keyEl = k !== null ? (
    <><span className="text-[#c9c2e6]"><Highlight text={k} q={q} /></span><span className="text-[#807c92]">: </span></>
  ) : null;

  if (leaf) {
    return (
      <div className="relative pl-4 group/leaf">
        <span className="inline-block w-3" />
        {keyEl}
        <Leaf v={v} q={q} />
        <button className="ml-2 opacity-0 group-hover/leaf:opacity-60 hover:!opacity-100 text-[#807c92] hover:text-white text-[11px]"
                title="复制值" onClick={() => copy(typeof v === "string" ? v : JSON.stringify(v))}>⧉</button>
      </div>
    );
  }

  const entries = Array.isArray(v) ? (v as Json[]).map((x, i) => [String(i), x] as const)
                                   : Object.entries(v as Record<string, Json>);
  const preview = Array.isArray(v) ? `[${(v as Json[]).length}]` : `{${entries.length}}`;

  return (
    <div className="relative pl-4">
      <div className="flex items-center rounded hover:bg-white/[0.04] cursor-pointer group/line"
           onClick={() => setOpen((o) => !o)}>
        <span className="w-3 shrink-0 text-[#807c92] select-none transition-transform"
              style={{ transform: effectiveOpen ? "rotate(90deg)" : "none" }}>▸</span>
        {keyEl}
        <span className="text-[#807c92]">{preview}</span>
        <button className="ml-2 opacity-0 group-hover/line:opacity-60 hover:!opacity-100 text-[#807c92] hover:text-white text-[11px]"
                title="复制此节点" onClick={(e) => { e.stopPropagation(); copy(JSON.stringify(v, null, 2)); }}>⧉</button>
      </div>
      {effectiveOpen && (
        <div className="ml-0.5 border-l border-white/[0.06]">
          {entries.map(([ck, cv]) => (
            <TreeNode key={ck} k={ck} v={cv} depth={depth + 1} q={q} seedOpen={seedOpen} />
          ))}
        </div>
      )}
    </div>
  );
}

export function JsonTree({ data, filter = "", forceOpen = null, nonce = 0 }: {
  data: Json; filter?: string; forceOpen?: number | null; nonce?: number;
}) {
  const q = filter.trim().toLowerCase();
  // remount the tree whenever expand/collapse-all fires (nonce bumps), so seedOpen re-seeds
  const rootKey = useMemo(() => `${forceOpen}:${nonce}`, [forceOpen, nonce]);
  return (
    <div className="font-mono text-xs leading-[1.7]">
      <TreeNode key={rootKey} k={null} v={data} depth={0} q={q} seedOpen={forceOpen} />
    </div>
  );
}
