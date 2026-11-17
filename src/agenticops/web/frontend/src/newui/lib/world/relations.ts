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
