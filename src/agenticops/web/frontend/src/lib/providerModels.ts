/** The models of a provider as Settings → Model providers → Models shows and edits them (MVP-2.9.0 N35). What an
 *  admin changes is sent as the server's types (llm/catalog._check_fields) and only when it changed; the server
 *  then keeps it over what a refresh of the model list says. */
import type { ProviderModel, Purpose, Reasoning } from "@/hooks/useModelProviders";

export type ToolsChoice = "unknown" | "yes" | "no";

export interface ModelDraft {
  label: string;
  purpose: Purpose;
  contextWindow: string;
  maxOutput: string;
  tools: ToolsChoice;
  images: boolean;
  documents: boolean;
  reasoning: Reasoning;
  priceInput: string;
  priceOutput: string;
  priceCacheRead: string;
  priceCacheWrite: string;
}

const num = (v: number | null) => (v === null || v === undefined ? "" : String(v));

export function draftOf(m: ProviderModel): ModelDraft {
  return {
    label: m.label, purpose: m.purpose, contextWindow: num(m.context_window), maxOutput: num(m.max_output_tokens),
    tools: m.supports_tools === null ? "unknown" : m.supports_tools ? "yes" : "no",
    images: m.supports_images, documents: m.supports_documents, reasoning: m.reasoning,
    priceInput: num(m.price_input), priceOutput: num(m.price_output), priceCacheRead: num(m.price_cache_read),
    priceCacheWrite: num(m.price_cache_write),
  };
}

/** «does it call tools», as the server answers it: an admin's value, else the connection test's, else not known. */
export function toolsState(m: ProviderModel): "yes" | "no" | "untested" {
  return m.tools === true ? "yes" : m.tools === false ? "no" : "untested";
}

/** «$in / $out» per million tokens, or null when the provider listed no price (the cost then counts 0). */
export function priceLabel(m: ProviderModel): string | null {
  if (m.price_input === null && m.price_output === null) return null;
  return `$${m.price_input ?? 0} / $${m.price_output ?? 0}`;
}

export function filterModels(models: ProviderModel[], f: { purpose: "all" | Purpose; query: string }): ProviderModel[] {
  const q = f.query.trim().toLowerCase();
  return models.filter((m) => (f.purpose === "all" || m.purpose === f.purpose)
    && (!q || m.model_id.toLowerCase().includes(q) || m.label.toLowerCase().includes(q)));
}

type Field = keyof ModelDraft;

/** a positive whole number; "" = none; undefined = cannot be sent */
function count(text: string): number | null | undefined {
  const s = text.trim();
  if (!s) return null;
  return /^\d+$/.test(s) && Number(s) > 0 ? Number(s) : undefined;
}

/** a price of zero or more; "" = none; undefined = cannot be sent */
function price(text: string): number | null | undefined {
  const s = text.trim();
  if (!s) return null;
  return /^\d+(\.\d+)?$/.test(s) ? Number(s) : undefined;
}

/** PATCH /api/model-providers/{name}/models/{id}: what changed, or the first field that cannot be sent. */
export function modelPatch(m: ProviderModel, d: ModelDraft): Record<string, unknown> | { error: Field } {
  const out: Record<string, unknown> = {};
  if (d.label.trim() !== m.label) out.label = d.label.trim();
  if (d.purpose !== m.purpose) out.purpose = d.purpose;
  const numbers: [Field, string, (t: string) => number | null | undefined, number | null][] = [
    ["contextWindow", "context_window", count, m.context_window],
    ["maxOutput", "max_output_tokens", count, m.max_output_tokens],
    ["priceInput", "price_input", price, m.price_input],
    ["priceOutput", "price_output", price, m.price_output],
    ["priceCacheRead", "price_cache_read", price, m.price_cache_read],
    ["priceCacheWrite", "price_cache_write", price, m.price_cache_write],
  ];
  for (const [field, key, read, before] of numbers) {
    const value = read(d[field] as string);
    if (value === undefined) return { error: field };
    if (value !== before) out[key] = value;
  }
  const tools = d.tools === "unknown" ? null : d.tools === "yes";
  if (tools !== m.supports_tools) out.supports_tools = tools;
  if (d.images !== m.supports_images) out.supports_images = d.images;
  if (d.documents !== m.supports_documents) out.supports_documents = d.documents;
  if (d.reasoning !== m.reasoning) out.reasoning = d.reasoning;
  return out;
}
