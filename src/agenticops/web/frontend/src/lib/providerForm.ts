/** The model provider form (MVP-2.9.0 N35, Settings → Model providers): what is checked before sending — the
 *  server's own rules (llm/registry), said next to the field — and the body sent. A key is never shown back: an edit
 *  leaves the key field empty («saved»), and an empty field keeps the stored key; a stored header's value comes back
 *  as the mask, which the server reads as «keep it». */

export const MASK = "****";
const NAME_RE = /^[a-z][a-z0-9-]{1,31}$/;
const RESERVED = new Set(["bedrock"]);
const HEADER_NAME_RE = /^[!#$%&'*+.^_`|~0-9A-Za-z-]+$/;
const DEFAULT_TIMEOUT = "60";

export type ProviderKind = "openai_compatible" | "anthropic_compatible";

export interface PresetLike {
  preset: string;
  kind: ProviderKind;
  base_url: string;
  needs_key: boolean;
}

export interface ProviderForm {
  name: string;
  displayName: string;
  preset: string;
  kind: ProviderKind;
  baseUrl: string;
  apiKey: string;
  headersText: string;
  timeout: string;
}

/** What the list gives of a provider (GET /api/model-providers) that the form reads. */
export interface ProviderRowLike {
  name: string;
  display_name: string;
  kind: ProviderKind;
  preset: string;
  base_url: string;
  timeout_seconds: number;
  header_names: string[];
  has_api_key: boolean;
}

export type FormProblem = { field: "name" | "baseUrl" | "apiKey" | "headers" | "timeout"; reason: string };

export function emptyForm(p: PresetLike): ProviderForm {
  return { name: "", displayName: "", preset: p.preset, kind: p.kind, baseUrl: p.base_url, apiKey: "",
           headersText: "", timeout: DEFAULT_TIMEOUT };
}

export function formFromRow(row: ProviderRowLike): ProviderForm {
  return { name: row.name, displayName: row.display_name, preset: row.preset, kind: row.kind, baseUrl: row.base_url,
           apiKey: "", headersText: headersToText(row.header_names), timeout: String(row.timeout_seconds) };
}

function cleanUrl(url: string): string {
  return url.trim().replace(/\/+$/, "");
}

function urlOk(url: string): boolean {
  try {
    const u = new URL(url.trim());
    return (u.protocol === "http:" || u.protocol === "https:") && u.host !== "";
  } catch {
    return false;
  }
}

function timeoutOf(text: string): number | null {
  if (!/^\d+$/.test(text.trim())) return null;
  const n = Number(text.trim());
  return n >= 5 && n <= 600 ? n : null;
}

/** One «Name: value» per line, split at the first colon; blank lines skipped. The line number of the first bad one. */
export function headersFromText(text: string): { headers: Record<string, string> } | { error: { line: number } } {
  const headers: Record<string, string> = {};
  const lines = text.split("\n");
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trim();
    if (!line) continue;
    const at = line.indexOf(":");
    const name = at > 0 ? line.slice(0, at).trim() : "";
    if (!name || !HEADER_NAME_RE.test(name)) return { error: { line: i + 1 } };
    headers[name] = line.slice(at + 1).trim();
  }
  return { headers };
}

export function headersToText(names: string[]): string {
  return names.map((n) => `${n}: ${MASK}`).join("\n");
}

export function validateProviderForm(
  form: ProviderForm, opts: { isNew: boolean; needsKey: boolean; hasStoredKey: boolean },
): FormProblem | null {
  if (opts.isNew) {
    if (!NAME_RE.test(form.name)) return { field: "name", reason: "name" };
    if (RESERVED.has(form.name)) return { field: "name", reason: "nameReserved" };
  }
  if (!urlOk(form.baseUrl)) return { field: "baseUrl", reason: "baseUrl" };
  if (opts.needsKey && !form.apiKey.trim() && !opts.hasStoredKey) return { field: "apiKey", reason: "apiKey" };
  if ("error" in headersFromText(form.headersText)) return { field: "headers", reason: "headers" };
  if (timeoutOf(form.timeout) === null) return { field: "timeout", reason: "timeout" };
  return null;
}

/** POST /api/model-providers. Call after validateProviderForm. */
export function createBody(form: ProviderForm): Record<string, unknown> {
  const parsed = headersFromText(form.headersText);
  const body: Record<string, unknown> = {
    name: form.name, display_name: form.displayName.trim() || form.name, preset: form.preset, kind: form.kind,
    base_url: cleanUrl(form.baseUrl), extra_headers: "headers" in parsed ? parsed.headers : {},
    timeout_seconds: timeoutOf(form.timeout) ?? Number(DEFAULT_TIMEOUT),
  };
  if (form.apiKey.trim()) body.api_key = form.apiKey.trim();
  return body;
}

/** PATCH /api/model-providers/{name}: only what changed; the key only when one was typed, or its removal. */
export function patchFromForm(before: ProviderRowLike, form: ProviderForm, opts: { clearKey?: boolean } = {}): Record<string, unknown> {
  const body: Record<string, unknown> = {};
  const display = form.displayName.trim() || before.name;
  if (display !== before.display_name) body.display_name = display;
  if (form.kind !== before.kind) body.kind = form.kind;
  if (form.preset !== before.preset) body.preset = form.preset;
  if (cleanUrl(form.baseUrl) !== before.base_url) body.base_url = cleanUrl(form.baseUrl);
  const timeout = timeoutOf(form.timeout);
  if (timeout !== null && timeout !== before.timeout_seconds) body.timeout_seconds = timeout;
  if (opts.clearKey) body.clear_api_key = true;
  else if (form.apiKey.trim()) body.api_key = form.apiKey.trim();
  if (form.headersText.trim() !== headersToText(before.header_names)) {
    const parsed = headersFromText(form.headersText);
    if ("headers" in parsed) body.extra_headers = parsed.headers;
  }
  return body;
}

export type TestNote = { key: string; error?: string } | { text: string };

/** What «Save and test» says after the list read and the test: the list's failure is kept beside the test's — a
 *  wrong address or key fails the list first, and the test then has no model to try (`no_model`). */
export function testNotes(listError: string | null, test: { code?: string; message: string } | null): TestNote[] {
  const out: TestNote[] = [];
  if (listError) out.push({ key: "settings.providers.listFailed", error: listError });
  if (test) out.push(test.code === "no_model" ? { key: "settings.providers.noModelYet" } : { text: test.message });
  return out;
}
