import { describe, it, expect } from "vitest";
import { healthKey, lifecycleKey, resourceFilters, resourceHref, resourceParams } from "@/lib/resourceTable";

const f = (s: string) => resourceFilters(new URLSearchParams(s));

describe("resourceFilters: the URL → GET /api/resources (MVP-2.7.0 S4)", () => {
  it("defaults: page 1 of 50, present resources only", () => {
    expect(f("")).toEqual({ limit: 50, offset: 0, includeAbsent: false, page: 1, size: 50 });
  });
  it("reads type, region, search, absent, page and size; junk falls back", () => {
    expect(f("type=EC2&region=us-east-1&q=%20web%20&absent=1&page=3&size=100"))
      .toEqual({ type: "EC2", region: "us-east-1", search: "web", includeAbsent: true, limit: 100, offset: 200, page: 3, size: 100 });
    expect(f("size=7&page=-2&absent=yes")).toEqual({ limit: 50, offset: 0, includeAbsent: false, page: 1, size: 50 });
    expect(f("page=abc").page).toBe(1);
  });
  it("a filter change goes back to page 1; defaults leave the URL", () => {
    expect(resourceParams(new URLSearchParams("page=4&type=EC2"), "region", "us-east-1").toString()).toBe("type=EC2&region=us-east-1");
    expect(resourceParams(new URLSearchParams("type=EC2"), "type", "").toString()).toBe("");
    expect(resourceParams(new URLSearchParams("size=100"), "size", "50").toString()).toBe("");
    expect(resourceParams(new URLSearchParams("type=EC2"), "page", "2").toString()).toBe("type=EC2&page=2");
    expect(resourceParams(new URLSearchParams("page=2"), "page", "1").toString()).toBe("");
  });
});

describe("resource rows", () => {
  it("health is never 'healthy': no open issue reads unknown, as does a value we do not know", () => {
    expect(healthKey("unknown")).toBe("resources.health.unknown");
    expect(healthKey("notice")).toBe("resources.health.notice");
    expect(healthKey("warning")).toBe("resources.health.warning");
    expect(healthKey("critical")).toBe("resources.health.critical");
    expect(healthKey(null)).toBe("resources.health.unknown");
    expect(healthKey(undefined)).toBe("resources.health.unknown");
    expect(healthKey("healthy")).toBe("resources.health.unknown");
  });
  it("lifecycle: present unless the latest complete scan no longer saw it", () => {
    expect(lifecycleKey({ absent_since: null })).toBe("resources.lifecycle.present");
    expect(lifecycleKey({})).toBe("resources.lifecycle.present");
    expect(lifecycleKey({ absent_since: "2026-10-06T10:00:00" })).toBe("resources.lifecycle.absent");
  });
  it("a row links by its integer key only", () => {
    expect(resourceHref(9)).toBe("/app/resources/9");
  });
});
