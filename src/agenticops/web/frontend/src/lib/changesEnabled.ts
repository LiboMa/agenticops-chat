/** Whether change management is on (MVP-2.9.0 N22). Three pages read `settings.data?.change_management_enabled ===
 *  true` and said «disabled» whenever it was not — also while the settings were still loading (it flashed on every
 *  open) and when they could not be read. «Off» is said only when the settings say so. Pure, so node can test it. */
export type ChangesState = "loading" | "failed" | "on" | "off";

export function changesState(q: { data?: { change_management_enabled?: boolean } | undefined; isError: boolean }): ChangesState {
  if (q.data) return q.data.change_management_enabled === true ? "on" : "off";
  return q.isError ? "failed" : "loading";
}
