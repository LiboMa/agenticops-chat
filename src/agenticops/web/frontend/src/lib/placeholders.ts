/** A localized template with its `{name}` placeholders filled from params, in one pass: a value goes in as plain
 *  text (no `$` patterns, never filled again), a placeholder params do not name stays as it is. */
export function fillPlaceholders(template: string, params?: Record<string, string>): string {
  if (!params) return template;
  return template.replace(/\{(\w+)\}/g, (m, k: string) => (Object.prototype.hasOwnProperty.call(params, k) ? params[k] : m));
}
