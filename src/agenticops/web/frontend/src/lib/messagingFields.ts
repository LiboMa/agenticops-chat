// Pure helpers for the schema-driven Configure form (no React).

export interface FieldDescriptor {
  key: string;
  label: string;
  type: "text" | "password" | "number" | "list" | "select";
  required: boolean;
  secret: boolean;
}
export interface TypeDescriptor { type?: string; platform?: string; label: string; fields: FieldDescriptor[]; }
export interface MessagingSchema { app_platforms: TypeDescriptor[]; channel_types: TypeDescriptor[]; }

/** Find the field list for a channel type. */
export function channelFields(schema: MessagingSchema | undefined, type: string): FieldDescriptor[] {
  return schema?.channel_types.find((c) => c.type === type)?.fields ?? [];
}

/** Find the field list for an app platform. */
export function appFields(schema: MessagingSchema | undefined, platform: string): FieldDescriptor[] {
  return schema?.app_platforms.find((p) => p.platform === platform)?.fields ?? [];
}

/** Validate required fields against current values; returns missing field keys. */
export function missingRequired(fields: FieldDescriptor[], values: Record<string, string>): string[] {
  return fields.filter((f) => f.required && !String(values[f.key] ?? "").trim()).map((f) => f.key);
}

/**
 * Build the payload to send. Secret fields left blank are OMITTED (backend keeps existing).
 * `list` type fields are split on commas into arrays.
 */
export function buildConfigPayload(fields: FieldDescriptor[], values: Record<string, string>): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const f of fields) {
    const raw = values[f.key];
    if (raw == null || raw === "") {
      if (f.secret) continue;        // blank secret → keep existing (omit)
      if (!f.required) continue;     // blank optional → omit
    }
    if (f.type === "list") {
      out[f.key] = String(raw ?? "").split(",").map((s) => s.trim()).filter(Boolean);
    } else if (f.type === "number") {
      out[f.key] = raw === "" || raw == null ? undefined : Number(raw);
    } else {
      out[f.key] = raw;
    }
  }
  return out;
}
