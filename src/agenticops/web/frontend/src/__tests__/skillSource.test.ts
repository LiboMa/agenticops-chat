import { describe, it, expect } from "vitest";
import { detectSkillSource, parseSkillNames } from "@/lib/skillSource";

// The chip under the import input must agree with skills/sources.py's decision order
// (_is_git → http(s) → path). Each case here is one branch of that order.
describe("detectSkillSource", () => {
  it("git+ prefix", () => {
    expect(detectSkillSource("git+https://github.com/org/repo.git@main#skills/foo")).toBe("git");
  });
  it("scp-style git@ and ssh://git@ prefixes", () => {
    expect(detectSkillSource("git@github.com:org/repo.git")).toBe("git");
    expect(detectSkillSource("ssh://git@example.com/org/repo")).toBe("git");
  });
  it(".git suffix and .git@ref on any host", () => {
    expect(detectSkillSource("https://example.com/org/repo.git")).toBe("git");
    expect(detectSkillSource("https://example.com/org/repo.git@v1#sub")).toBe("git");
  });
  it("bare github/gitlab/bitbucket repo URL is git (host rule)", () => {
    expect(detectSkillSource("https://github.com/org/repo")).toBe("git");
    expect(detectSkillSource("https://www.gitlab.com/org/repo")).toBe("git");
    expect(detectSkillSource("https://bitbucket.org/org/repo/")).toBe("git");
  });
  it("an archive or SKILL.md on a git host is NOT git — the suffix wins, like the server", () => {
    expect(detectSkillSource("https://github.com/org/repo/archive/main.zip")).toBe("archive-url");
    expect(detectSkillSource("https://github.com/org/repo/raw/main/SKILL.md")).toBe("skill-md-url");
  });
  it("archive URLs by suffix, case-insensitive, ignoring query/fragment", () => {
    expect(detectSkillSource("https://x.test/skills.tgz")).toBe("archive-url");
    expect(detectSkillSource("https://x.test/skills.TAR.GZ")).toBe("archive-url");
    expect(detectSkillSource("https://x.test/skills.zip?dl=1")).toBe("archive-url");
  });
  it("a single SKILL.md URL", () => {
    expect(detectSkillSource("https://x.test/foo/SKILL.md")).toBe("skill-md-url");
  });
  it("other http(s) → plain url (server decides by content type)", () => {
    expect(detectSkillSource("https://x.test/download/12345")).toBe("url");
  });
  it("anything else is a server-side path", () => {
    expect(detectSkillSource("/tmp/pkg")).toBe("path");
    expect(detectSkillSource("~/skills")).toBe("path");
  });
  it("a non-http/git scheme is flagged up front — the server's path probe can never accept it", () => {
    expect(detectSkillSource("ftp://example.invalid/x")).toBe("unsupported-scheme");
    expect(detectSkillSource("s3://bucket/skills.zip")).toBe("unsupported-scheme");
    expect(detectSkillSource("file:///tmp/pkg")).toBe("unsupported-scheme");
    // ssh://git@ is git (checked first), not an unsupported scheme
    expect(detectSkillSource("ssh://git@example.com/org/repo")).toBe("git");
  });
  it("blank → empty (trims first)", () => {
    expect(detectSkillSource("")).toBe("empty");
    expect(detectSkillSource("   ")).toBe("empty");
    expect(detectSkillSource("  /tmp/pkg  ")).toBe("path");
  });
});

describe("parseSkillNames", () => {
  it("splits on commas and whitespace, trims, de-duplicates, drops empties", () => {
    expect(parseSkillNames("a, b  c,,a")).toEqual(["a", "b", "c"]);
  });
  it("blank → []", () => {
    expect(parseSkillNames("")).toEqual([]);
    expect(parseSkillNames(" , ,\n")).toEqual([]);
  });
});
