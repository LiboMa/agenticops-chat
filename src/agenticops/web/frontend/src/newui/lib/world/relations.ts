/** Which way a fault travels along a relation written src → dst — the back end's registry (graph/relations.py),
 *  copied here because the graph API sends relation names, not directions. The two copies are held together by
 *  tests/fixtures/relation_propagation.json: pytest checks the registry against it, vitest this table. */
export type Propagation = "forward" | "reverse" | "both" | "none";

export const PROPAGATION: Record<string, Propagation> = {
  contains: "forward",
  secured_by: "reverse",
  attached_to: "forward",
  routes_to: "reverse",
  manages: "both",
  uses: "reverse",
  restricts: "forward",
  runs_on: "reverse",
  same_as: "both",
  references: "none",
  inferred_group: "none",
};

export interface Relation { r: string; p: "rule" | "llm" }

/** The direction to draw on a link. A relation a model inferred has none, whatever its name: an inferred relation
 *  is advisory and the map never draws it as a known dependency. */
export function flow(e: Relation): Propagation {
  return e.p === "llm" ? "none" : PROPAGATION[e.r] ?? "none";
}

/** Which way the moving dots run on a link of the OPEN resource (the flat map): true = away from it, false =
 *  towards it; a two-way relation gets one each way, a relation with no known direction none. `out` = the link is
 *  written from the open resource to the other end. The same answer as `side`: away from it towards what is
 *  downstream of it, towards it from what is upstream. */
export function dotWays(e: Relation, out: boolean): boolean[] {
  const way = flow(e);
  return way === "none" ? [] : way === "both" ? [true, false] : [(way === "forward") === out];
}

/** The ends the 3D engine is given for a link written a → b. Its particles run source → target, so a relation whose
 *  fault travels the other way round is handed over reversed; `particles` = it has one known direction to show (a
 *  two-way relation gets none: the engine could only draw one of the two). */
export function engineEnds(e: Relation, a: number, b: number): { source: number; target: number; particles: boolean } {
  const way = flow(e), back = way === "reverse";
  return { source: back ? b : a, target: back ? a : b, particles: way === "forward" || way === "reverse" };
}

export type Side = "up" | "down" | "both" | "inferred" | "unknown";

/** What the other end of a link is to the resource being looked at. `out` = the link is written from the resource
 *  to the other end. up = a fault there reaches this resource; down = this resource's fault reaches it. */
export function side(e: Relation, out: boolean): Side {
  if (e.p === "llm") return "inferred";
  const p = PROPAGATION[e.r] ?? "none";
  if (p === "none") return "unknown";
  if (p === "both") return "both";
  return (p === "forward") === out ? "down" : "up";
}
