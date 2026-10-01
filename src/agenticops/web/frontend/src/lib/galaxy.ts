/**
 * Galaxy page logic (MVP-2.6.1 spec §3.E.5): the `?focus=` deep link and when a finished build should refresh
 * the drawn graphs. Pure, so node can test it.
 */
import type { GalaxyBuildInfo } from "@/api/types";

/** `?focus=` → a resource node id. Takes a cloud_resources id as `12`, `R12`, `R#12` or the node id `res:12`. */
export function focusNodeId(v: string | null): string | null {
  const m = (v ?? "").trim().match(/^(?:res:|R#?)?(\d+)$/i);
  return m ? `res:${m[1]}` : null;
}

export const galaxyFocusPath = (ref: number) => `/app/galaxy?focus=${ref}`;

type Build = Pick<GalaxyBuildInfo, "id" | "status">;

/**
 * True when the status poll shows a build that has just completed: a new completed build, or the running one
 * finishing. `prev` undefined is the first observation — whatever is loaded is already current.
 */
export function buildLanded(prev: Build | null | undefined, next: Build | null): boolean {
  if (prev === undefined || next?.status !== "completed") return false;
  return prev === null || prev.id !== next.id || prev.status !== "completed";
}
