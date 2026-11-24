/** Times in NewUI are UTC and say so. */

/** "09:32" — the UTC hour and minute of a moment (ms since the epoch, a Date, or an API string). */
export function utcHm(at: number | Date | string | null | undefined): string {
  const d = at == null ? null : at instanceof Date ? at : new Date(typeof at === "string" && !/[zZ]|[+-]\d\d:?\d\d$/.test(at) ? at + "Z" : at);
  return d && !Number.isNaN(d.getTime()) ? d.toISOString().slice(11, 16) : "—";
}

/** "11-16 09:32" — the UTC day and time; the year only when it is not `now`'s. */
export function utcStamp(at: number | Date | string | null | undefined, now: number = Date.now()): string {
  const d = at == null ? null : at instanceof Date ? at : new Date(typeof at === "string" && !/[zZ]|[+-]\d\d:?\d\d$/.test(at) ? at + "Z" : at);
  if (!d || Number.isNaN(d.getTime())) return "—";
  const iso = d.toISOString(), sameYear = iso.slice(0, 4) === new Date(now).toISOString().slice(0, 4);
  return `${sameYear ? iso.slice(5, 10) : iso.slice(0, 10)} ${iso.slice(11, 16)}`;
}
