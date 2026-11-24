/** One line of the model's latest thinking summary (2026-11-08, Claude 4.7+ "display": "summarized"): the last
 *  sentence — finished or still being written — on one line, cut from the left when it is long. */
export function thinkingTail(text: string, max = 160): string {
  const pieces = text.match(/[^.。!?！？\n]+[.。!?！？]?/g) ?? [];
  let last = "";
  for (let i = pieces.length - 1; i >= 0; i--) {
    const t = pieces[i].trim();
    if (t) { last = t; break; }
  }
  last = last.replace(/\s+/g, " ");
  return last.length > max ? "…" + last.slice(last.length - (max - 1)) : last;
}
