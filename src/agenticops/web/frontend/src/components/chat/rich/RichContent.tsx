import { memo, useMemo } from "react";
import { useLocale } from "@/i18n/LocaleContext";
import { renderMarkdown } from "@/lib/renderMarkdown";
import { splitRichBlocks } from "@/lib/richBlocks";
import { copyText } from "@/lib/clipboard";
import { ChartBlock } from "./ChartBlock";
import { MermaidBlock } from "./MermaidBlock";

interface Props {
  text: string;
  /** still being written: nothing is cached (the text changes on every token) */
  streaming?: boolean;
  /** a stored message's id: its markdown HTML is cached for good (messages never change) */
  cacheKey?: string | number;
}

const htmlCache = new Map<string, string>();

/** A chat answer: markdown (tables, code with a copy button, refs) with ```chart and ```mermaid blocks drawn in place
 *  (2026-11-07). Ref links (I#/R#/C#) keep bubbling to the message list, which routes them. */
export const RichContent = memo(function RichContent({ text, streaming, cacheKey }: Props) {
  const { t } = useLocale();
  const copyLabel = t("chat.rich.copy");
  const segments = useMemo(() => splitRichBlocks(text), [text]);

  const html = (md: string, i: number) => {
    const opts = { copyButtons: true, copyLabel };
    if (streaming || cacheKey === undefined) return renderMarkdown(md, opts);
    const key = `${cacheKey}\u0000${i}\u0000${copyLabel}`;
    let hit = htmlCache.get(key);
    if (hit === undefined) {
      hit = renderMarkdown(md, opts);
      htmlCache.set(key, hit);
    }
    return hit;
  };

  const onClick = (e: React.MouseEvent) => {
    const btn = (e.target as HTMLElement).closest("[data-md-copy]") as HTMLButtonElement | null;
    if (!btn) return;
    e.preventDefault();
    const code = btn.parentElement?.querySelector("pre")?.textContent ?? "";
    void copyText(code).then((ok) => {
      if (!ok) return;
      btn.textContent = t("chat.rich.copied");
      window.setTimeout(() => { btn.textContent = copyLabel; }, 1500);
    });
  };

  return (
    <div className="report-content max-w-none text-[15px] leading-relaxed text-foreground" onClick={onClick}>
      {segments.map((s, i) =>
        s.kind === "md" ? <div key={i} dangerouslySetInnerHTML={{ __html: html(s.text, i) }} />
        : s.kind === "chart" ? <ChartBlock key={i} spec={s.spec} source={s.source} />
        : <MermaidBlock key={i} source={s.source} />)}
    </div>
  );
});
