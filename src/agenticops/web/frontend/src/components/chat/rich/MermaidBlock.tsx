import { useEffect, useState } from "react";
import { useLocale } from "@/i18n/LocaleContext";
import { useTheme } from "@/hooks/useTheme";
import { mermaidSource } from "@/lib/richBlocks";
import { peekMermaid, renderMermaidCached } from "@/lib/mermaidCache";
import { ZoomDialog } from "./ZoomDialog";

/** mermaid is loaded only when an answer holds a flowchart (a separate chunk), and always runs strict: no scripts,
 *  no click handlers, labels sanitized. Init directives are stripped first (mermaidSource). */
async function renderSvg(id: string, src: string, theme: "light" | "dark"): Promise<string> {
  const { default: mermaid } = await import("mermaid");
  mermaid.initialize({ startOnLoad: false, securityLevel: "strict", theme: theme === "dark" ? "dark" : "default" });
  await mermaid.parse(src);            // throws on a syntax error before render touches the DOM
  const { svg } = await mermaid.render(id, src);
  return svg;
}

export function MermaidBlock({ source }: { source: string }) {
  const { t } = useLocale();
  const { theme } = useTheme();
  const src = mermaidSource(source);
  const [svg, setSvg] = useState<string | undefined>(() => peekMermaid(src, theme));
  const [failed, setFailed] = useState(false);
  const [zoom, setZoom] = useState(false);

  useEffect(() => {
    let alive = true;
    setFailed(false);
    const cached = peekMermaid(src, theme);
    if (cached) { setSvg(cached); return; }
    renderMermaidCached(src, theme, (id, s) => renderSvg(id, s, theme))
      .then((out) => { if (alive) setSvg(out); }, () => { if (alive) setFailed(true); });
    return () => { alive = false; };
  }, [src, theme]);

  if (failed) {
    return (
      <div className="my-3">
        <pre className="md-pre"><code>{source}</code></pre>
        <p className="-mt-2 mb-3 text-xs text-muted-foreground">{t("chat.rich.mermaidFailed")}</p>
      </div>
    );
  }
  return (
    <div className="my-3 rounded-xl border border-border bg-card">
      {svg ? (
        <button type="button" onClick={() => setZoom(true)} title={t("chat.rich.enlarge")}
                className="aiops-mermaid block w-full cursor-zoom-in overflow-x-auto p-3 text-left"
                dangerouslySetInnerHTML={{ __html: svg }} />
      ) : (
        <div className="flex min-h-[120px] items-center justify-center text-xs text-muted-foreground">…</div>
      )}
      {zoom && svg && (
        <ZoomDialog title={t("chat.rich.flowchart")} onClose={() => setZoom(false)}>
          <div className="aiops-mermaid aiops-mermaid-zoom" dangerouslySetInnerHTML={{ __html: svg }} />
        </ZoomDialog>
      )}
    </div>
  );
}
