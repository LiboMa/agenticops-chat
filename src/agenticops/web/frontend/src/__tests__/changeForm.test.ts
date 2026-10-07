import { describe, it, expect } from "vitest";
import { cleanExternalRef, cleanProposedSteps } from "@/lib/changeForm";

describe("cleanProposedSteps", () => {
  it("trims the rows and drops the blank ones", () => {
    expect(cleanProposedSteps([
      { action: " scale down ", command: " kubectl scale deploy/web --replicas=2 " },
      { action: "", command: "   " },
      { action: "", command: "kubectl rollout status deploy/web" },
    ])).toEqual({ ok: true, value: [
      { action: "scale down", command: "kubectl scale deploy/web --replicas=2" },
      { action: "", command: "kubectl rollout status deploy/web" },
    ] });
  });

  it("no rows (or only blank ones) sends no steps", () => {
    expect(cleanProposedSteps([])).toEqual({ ok: true, value: undefined });
    expect(cleanProposedSteps([{ action: " ", command: "" }])).toEqual({ ok: true, value: undefined });
  });

  it("a step with a description but no command is refused, by its 1-based row", () => {
    expect(cleanProposedSteps([{ action: "a", command: "ls" }, { action: "restart", command: "" }]))
      .toEqual({ ok: false, error: "noCommand", row: 2 });
  });
});

describe("cleanExternalRef", () => {
  it("all blank sends no ref", () => {
    expect(cleanExternalRef({ system: " ", ticket_id: "", url: "" })).toEqual({ ok: true, value: undefined });
  });

  it("a system and a ticket id, the url only when given", () => {
    expect(cleanExternalRef({ system: " jira ", ticket_id: " OPS-12 ", url: "" }))
      .toEqual({ ok: true, value: { system: "jira", ticket_id: "OPS-12" } });
    expect(cleanExternalRef({ system: "jira", ticket_id: "OPS-12", url: " https://jira.example/OPS-12 " }))
      .toEqual({ ok: true, value: { system: "jira", ticket_id: "OPS-12", url: "https://jira.example/OPS-12" } });
  });

  it("refuses what the API would: a bad system name, a missing ticket id, a non-http(s) url", () => {
    expect(cleanExternalRef({ system: "Jira Cloud", ticket_id: "1", url: "" })).toEqual({ ok: false, error: "badSystem" });
    expect(cleanExternalRef({ system: "jira", ticket_id: "", url: "" })).toEqual({ ok: false, error: "noTicket" });
    expect(cleanExternalRef({ system: "", ticket_id: "OPS-1", url: "" })).toEqual({ ok: false, error: "badSystem" });
    expect(cleanExternalRef({ system: "jira", ticket_id: "1", url: "ftp://x" })).toEqual({ ok: false, error: "badUrl" });
  });
});
