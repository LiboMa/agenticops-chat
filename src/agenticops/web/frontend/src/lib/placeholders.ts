/** A localized template with its `{name}` placeholders filled from params, in one pass: a value goes in as plain
 *  text (no `$` patterns, never filled again; a number as its text), every occurrence of a placeholder is filled,
 *  a placeholder params do not name stays as it is. The one way a template is filled (`__tests__/noReplaceFill`). */
export function fillPlaceholders(template: string, params?: Record<string, string | number>): string {
  if (!params) return template;
  return template.replace(/\{(\w+)\}/g, (m, k: string) => (Object.prototype.hasOwnProperty.call(params, k) ? String(params[k]) : m));
}
