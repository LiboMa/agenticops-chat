import { describe, expect, it } from "vitest";
import { queryView } from "@/lib/queryState";

const isEmpty = (d: unknown) => !Array.isArray(d) || d.length === 0;
const q = (over: Partial<{ isPending: boolean; isError: boolean; data: unknown; dataUpdatedAt: number }>) => ({
  isPending: false, isError: false, data: undefined, dataUpdatedAt: 0, ...over,
});

describe("queryView — four data states (MVP-2.8.0 S1)", () => {
  it("is loading while the first request is pending", () => {
    expect(queryView(q({ isPending: true }), isEmpty)).toEqual({ kind: "loading", stale: false, asOf: null });
  });

  it("is an error when the request failed and nothing was ever fetched", () => {
    expect(queryView(q({ isError: true }), isEmpty)).toEqual({ kind: "error", stale: false, asOf: null });
  });

  it("is empty only after a successful request returned an empty collection", () => {
    expect(queryView(q({ data: [], dataUpdatedAt: 1000 }), isEmpty)).toEqual({ kind: "empty", stale: false, asOf: 1000 });
  });

  it("is ready with data, not stale", () => {
    expect(queryView(q({ data: [1], dataUpdatedAt: 2000 }), isEmpty)).toEqual({ kind: "ready", stale: false, asOf: 2000 });
  });

  it("keeps the last good data when a refresh fails — stale, never an error page or an empty state", () => {
    expect(queryView(q({ isError: true, data: [1, 2], dataUpdatedAt: 3000 }), isEmpty))
      .toEqual({ kind: "ready", stale: true, asOf: 3000 });
    expect(queryView(q({ isError: true, data: [], dataUpdatedAt: 4000 }), isEmpty))
      .toEqual({ kind: "empty", stale: true, asOf: 4000 });
  });
});
