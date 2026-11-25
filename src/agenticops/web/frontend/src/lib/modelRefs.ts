/** Model references and the settings that hold them (MVP-2.9.0 N35). A reference is `<provider>::<model id>`, split at
 *  the FIRST «::» (the model id may hold more); a value without one is a Bedrock model id — the server's
 *  llm/refs.parse_ref, the same examples in __tests__/modelRefs.test.ts. */
import { ApiError } from "@/api/client";

type T = (key: string) => string;

export const REF_SEP = "::";

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
