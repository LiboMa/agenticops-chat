/** Model references and the settings that hold them (MVP-2.9.0 N35). A reference is `<provider>::<model id>`, split at
 *  the FIRST «::» (the model id may hold more); a value without one is a Bedrock model id — the server's
 *  llm/refs.parse_ref, the same examples in __tests__/modelRefs.test.ts. The model list (`model_presets` of
 *  GET /api/settings, `presets` of GET /api/kb/embedding) is grouped by provider — Bedrock first — for the one
 *  picker every model setting uses (components/models/ModelPicker). */
import { ApiError } from "@/api/client";

type T = (key: string) => string;

export const REF_SEP = "::";
const NAME_RE = /^[a-z][a-z0-9-]{1,31}$/;
const RESERVED = new Set(["bedrock"]);
export const BEDROCK = "bedrock";

export type Purpose = "chat" | "embedding";

export interface ModelCapabilities {
  tools: boolean | null;
  images: boolean;
  documents: boolean;
  reasoning: string;
}

/** One entry of the model list. An older server sends only label / value / context_window: such an entry is a
 *  Bedrock chat model whose capabilities are not known. */
export interface ModelPreset {
  label: string;
  value: string;
  context_window?: number | null;
  provider?: string;
  provider_label?: string;
  purpose?: Purpose;
  capabilities?: ModelCapabilities;
  priced?: boolean;
}

export interface ModelIssue {
  setting: string;
  value: string;
  reason: string;
  inherited?: boolean;
}

export interface PresetGroup {
  provider: string;
  label: string;
  items: ModelPreset[];
}

/** null = not a reference the server would take. */
export function parseRef(value: string): { provider: string | null; model: string } | null {
  const v = (value ?? "").trim();
  if (!v) return null;
  const at = v.indexOf(REF_SEP);
  if (at === -1) return { provider: null, model: v };
  const provider = v.slice(0, at);
  const model = v.slice(at + REF_SEP.length);
  if (!NAME_RE.test(provider) || RESERVED.has(provider) || !model.trim()) return null;
  return { provider, model };
}

const providerOf = (p: ModelPreset) => p.provider ?? BEDROCK;
const purposeOf = (p: ModelPreset) => p.purpose ?? "chat";

export function groupPresets(presets: ModelPreset[], opts: { query: string; purpose?: Purpose }): PresetGroup[] {
  const q = opts.query.trim().toLowerCase();
  const want = opts.purpose ?? "chat";
  const groups = new Map<string, PresetGroup>();
  for (const p of presets) {
    if (purposeOf(p) !== want) continue;
    const provider = providerOf(p);
    const label = p.provider_label ?? (provider === BEDROCK ? "Amazon Bedrock" : provider);
    if (q && ![p.label, p.value, provider, label].some((s) => s.toLowerCase().includes(q))) continue;
    if (!groups.has(provider)) groups.set(provider, { provider, label, items: [] });
    groups.get(provider)!.items.push(p);
  }
  return [...groups.values()].sort((a, b) =>
    a.provider === BEDROCK ? -1 : b.provider === BEDROCK ? 1 : a.provider.localeCompare(b.provider));
}

export type Badge = "tools" | "noTools" | "toolsUnknown" | "images" | "documents" | "reasoning" | "unpriced";

/** What a model can do, as the list says it — nothing claimed when the list says nothing. */
export function badges(p: ModelPreset): Badge[] {
  const c = p.capabilities;
  if (!c) return [];
  const out: Badge[] = [c.tools === true ? "tools" : c.tools === false ? "noTools" : "toolsUnknown"];
  if (c.images) out.push("images");
  if (c.documents) out.push("documents");
  if (c.reasoning && c.reasoning !== "none") out.push("reasoning");
  if (p.priced === false) out.push("unpriced");
  return out;
}

/** What is wrong with a setting's value: «unavailable» — the server lists the setting among the model issues, or a
 *  provider's model that is not on the list (that list is the provider's whole catalogue); «noTools» — the model is
 *  listed as calling no tools. A Bedrock id off the list is no issue here: the picker says «not on the list». */
export function issueOf(value: string, presets: ModelPreset[], modelIssues: ModelIssue[] | undefined,
                        setting: string): "unavailable" | "noTools" | null {
  if (!value) return null;
  if ((modelIssues ?? []).some((i) => i.setting === setting && i.value === value)) return "unavailable";
  const p = presets.find((x) => x.value === value);
  if (!p) return parseRef(value)?.provider ? "unavailable" : null;
  return p.capabilities?.tools === false ? "noTools" : null;
}

/** A model setting's name as people read it (`agent_main_model_id` → «Main agent»); the field itself when unknown. */
export function settingName(t: T, field: string): string {
  const key = `settings.providers.setting.${field}`;
  const text = t(key);
  return text === key ? field : text;
}

/** A refusal in words: «in use by» names the settings (the server's `refs`), anything else is the server's sentence. */
export function refusalText(t: T, e: ApiError): string {
  const refs = e.data?.refs;
  if (e.code === "in_use" && Array.isArray(refs)) {
    return t("settings.providers.inUse").replace("{refs}", refs.map((r) => settingName(t, String(r))).join(", "));
  }
  return e.message;
}
