import { useEffect, useState } from "react";
import { useLocale } from "@/i18n/LocaleContext";
import { JsonTree } from "./JsonTree";

/**
 * Second-layer right-side panel showing a resource's raw_data as a collapsible
 * JSON tree (wider than the key-info panel). Slides in over the node panel;
 * ESC / back returns to it. Fixed Nebula-dark to match the starfield.
 */
export function GalaxyRawDataPanel({
  title, subtitle, data, onBack,
}: {
  title: string; subtitle: string; data: unknown; onBack: () => void;
}) {
  const { t } = useLocale();
  const [q, setQ] = useState("");
  const [forceOpen, setForceOpen] = useState<number | null>(null);
  const [nonce, setNonce] = useState(0);
  const keyCount = data && typeof data === "object" ? Object.keys(data as object).length : 0;
  const sizeKb = (JSON.stringify(data ?? {}).length / 1024).toFixed(1);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") { e.stopPropagation(); onBack(); } };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [onBack]);

  const copyAll = () => {
    if (navigator.clipboard) navigator.clipboard.writeText(JSON.stringify(data, null, 2)).catch(() => {});
  };
  const expandAll = () => { setForceOpen(1); setNonce((n) => n + 1); };
  const collapseAll = () => { setForceOpen(0); setNonce((n) => n + 1); };

  return (
    <div className="absolute top-9 right-0 bottom-0 w-[520px] max-w-full z-30 flex flex-col
                    bg-[#15141f]/98 backdrop-blur border-l border-white/[0.13]
                    animate-[slideInRight_0.2s_ease-out]">
      {/* header */}
      <div className="flex items-center gap-2.5 px-4 py-3 border-b border-white/10">
        <button onClick={onBack} className="text-[#8ea2ff] hover:text-white text-[13px]">‹ {t("galaxy.back")}</button>
        <span className="text-[13px] font-semibold text-white truncate">
          {title}<small className="text-[#807c92] font-normal ml-1.5">{subtitle}</small>
        </span>
        <div className="ml-auto flex gap-1.5 shrink-0">
          <ToolBtn onClick={expandAll}>{t("galaxy.expandAll")}</ToolBtn>
          <ToolBtn onClick={collapseAll}>{t("galaxy.collapseAll")}</ToolBtn>
          <ToolBtn onClick={copyAll}>{t("galaxy.copy")}</ToolBtn>
        </div>
      </div>

      {/* search */}
      <div className="px-4 pt-3">
        <input value={q} onChange={(e) => setQ(e.target.value)}
               placeholder={`${t("galaxy.searchJson")} · ${keyCount} keys · ${sizeKb}KB`}
               className="w-full bg-black/60 border border-white/[0.13] text-[#e9e6f2] rounded-md px-2.5 py-1.5 text-xs
                          outline-none placeholder:text-[#807c92] focus:border-[#8ea2ff]/50" />
      </div>

      {/* tree */}
      <div className="flex-1 overflow-auto px-3.5 pb-5 pt-2.5 text-[#c9c2e6]">
        {data && (typeof data === "object") && keyCount > 0
          ? <JsonTree data={data} filter={q} forceOpen={forceOpen} nonce={nonce} />
          : <div className="text-xs text-[#807c92] px-1 py-2">{t("galaxy.noRawData")}</div>}
      </div>
    </div>
  );
}

function ToolBtn({ children, onClick }: { children: React.ReactNode; onClick: () => void }) {
  return (
    <button onClick={onClick}
            className="bg-white/5 border border-white/10 text-[#807c92] hover:text-white
                       rounded px-2 py-0.5 text-[11px]">{children}</button>
  );
}
