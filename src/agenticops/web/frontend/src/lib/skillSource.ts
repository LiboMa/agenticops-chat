/**
 * Client-side hint for how the server will treat a skill source URI.
 *
 * Mirrors the decision order in `skills/sources.py` (`_is_git` → http(s) → local path)
 * so the chip under the input never contradicts what the backend does. It is a HINT
 * only: the server is the sole authority, and a URL whose kind we cannot tell from its
 * shape is reported as plain "url" (the server then decides by content type).
 */
export type SkillSourceKind =
  | "git"
  | "archive-url"
  | "skill-md-url"
  | "url"
  | "unsupported-scheme"
  | "path"
  | "empty";

// Anything with a `scheme://` that is not http(s)/git/ssh. The server's last branch probes
// it as a filesystem path, which can never succeed for such a string — so telling the user
// up front is a truthful hint, not a second opinion.
const OTHER_SCHEME_RE = /^[a-z][a-z0-9+.-]*:\/\//i;

const ARCHIVE_SUFFIXES = [".zip", ".tar.gz", ".tgz"];
// Same shape as sources._GIT_HOST_RE: a bare github/gitlab/bitbucket repo URL is git.
const GIT_HOST_RE = /^https?:\/\/(?:www\.)?(?:github|gitlab|bitbucket)\.(?:com|org)\/[^/]+\/[^/]+/;

function endsWithAny(s: string, suffixes: string[]): boolean {
  const lower = s.toLowerCase();
  return suffixes.some((x) => lower.endsWith(x));
}

function isGit(uri: string): boolean {
  if (uri.startsWith("git+") || uri.startsWith("git@") || uri.startsWith("ssh://git@")) return true;
  const base = uri.split("#", 1)[0];
  if (base.endsWith(".git") || base.includes(".git@")) return true;
  return GIT_HOST_RE.test(base) && !endsWithAny(base, [...ARCHIVE_SUFFIXES, ".md"]);
}

export function detectSkillSource(raw: string): SkillSourceKind {
  const uri = raw.trim();
  if (!uri) return "empty";
  if (isGit(uri)) return "git";
  if (uri.startsWith("http://") || uri.startsWith("https://")) {
    const base = uri.split(/[?#]/, 1)[0];
    if (endsWithAny(base, ARCHIVE_SUFFIXES)) return "archive-url";
    if (base.toLowerCase().endsWith(".md")) return "skill-md-url";
    return "url";
  }
  if (OTHER_SCHEME_RE.test(uri)) return "unsupported-scheme";
  return "path";
}

/** "a, b  c,,a" → ["a", "b", "c"]: comma/whitespace separated, trimmed, de-duplicated. */
export function parseSkillNames(text: string): string[] {
  const out: string[] = [];
  for (const raw of text.split(/[\s,]+/)) {
    const n = raw.trim();
    if (n && !out.includes(n)) out.push(n);
  }
  return out;
}
