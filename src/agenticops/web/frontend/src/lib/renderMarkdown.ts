/**
 * Lightweight markdown-to-HTML renderer for report content.
 * Handles headings, bold, italic, inline code, code blocks, tables,
 * lists, horizontal rules, and links.
 *
 * Security: link hrefs are restricted to an allowlist (http(s), root-relative,
 * or fragment) so `javascript:`/`data:`/`vbscript:` links render as plain text
 * instead of clickable anchors. Ref autolinks: I#N → issue, R#N → resource,
 * C#N → change request.
 */

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// Allowlist for link hrefs. Strip leading control/space chars and any embedded
// tab/newline/CR (all of which browsers ignore inside a scheme) before testing,
// so obfuscated `java\tscript:` / " javascript:" cannot slip past. Anything that
// is not http(s), root-relative (/…), or a fragment (#…) is rejected.
function isSafeHref(href: string): boolean {
  const h = href
    .replace(/^[\u0000- ]+/, "")
    .replace(/[\t\n\r]/g, "")
    .toLowerCase();
  return /^(https?:|\/|#)/.test(h);
}

export function renderMarkdown(md: string): string {
  const lines = md.split("\n");
  const out: string[] = [];
  let inCodeBlock = false;
  let codeLang = "";
  let inTable = false;
  let inList: "ul" | "ol" | null = null;

  function closeList() {
    if (inList) {
      out.push(inList === "ul" ? "</ul>" : "</ol>");
      inList = null;
    }
  }

  function closeTable() {
    if (inTable) {
      out.push("</tbody></table></div>");
      inTable = false;
    }
  }

  function inlineFormat(text: string): string {
    // Strip NUL first: it is our anchor-placeholder delimiter, so any NUL in the
    // source must not survive to be mistaken for one.
    let s = escapeHtml(text.replace(/\u0000/g, ""));
    // inline code
    s = s.replace(/`([^`]+)`/g, '<code class="md-code">$1</code>');
    // bold + italic
    s = s.replace(/\*\*\*(.+?)\*\*\*/g, "<strong><em>$1</em></strong>");
    // bold
    s = s.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
    // italic
    s = s.replace(/\*(.+?)\*/g, "<em>$1</em>");
    // Links: only allowlisted hrefs become anchors; anything else falls back to
    // its label text. Each accepted anchor is parked behind a NUL-delimited
    // placeholder so the ref-autolink passes below never rewrite an href or a
    // link label (e.g. a "C#2" label or a "#C#1" fragment).
    const anchors: string[] = [];
    s = s.replace(/\[([^\]]+)\]\(([^)]+)\)/g, (_m, label: string, href: string) => {
      if (!isSafeHref(href)) return label;
      anchors.push(`<a href="${href}" class="md-link" target="_blank" rel="noopener">${label}</a>`);
      return `\u0000${anchors.length - 1}\u0000`;
    });
    // Auto-link I#N → /app/issues/N
    s = s.replace(/\bI#(\d+)\b/g,
      '<a href="/app/issues/$1" class="md-link md-ref" title="Issue #$1">I#$1</a>');
    // Auto-link R#N → /app/resources/N
    s = s.replace(/\bR#(\d+)\b/g,
      '<a href="/app/resources/$1" class="md-link md-ref" title="Resource #$1">R#$1</a>');
    // Auto-link C#N → /app/changes/N
    s = s.replace(/\bC#(\d+)\b/g,
      '<a href="/app/changes/$1" class="md-link md-ref" title="Change #$1">C#$1</a>');
    // Restore parked anchors.
    s = s.replace(/\u0000(\d+)\u0000/g, (_m, i: string) => anchors[Number(i)] ?? "");
    return s;
  }

  for (let i = 0; i < lines.length; i++) {
    const raw = lines[i];

    // Code blocks
    if (raw.trimStart().startsWith("```")) {
      if (inCodeBlock) {
        out.push("</code></pre>");
        inCodeBlock = false;
        codeLang = "";
      } else {
        closeList();
        closeTable();
        inCodeBlock = true;
        codeLang = raw.trimStart().slice(3).trim().toLowerCase();
        const langAttr = codeLang ? ` data-lang="${escapeHtml(codeLang)}"` : "";
        out.push(`<pre class="md-pre"${langAttr}><code>`);
      }
      continue;
    }
    if (inCodeBlock) {
      out.push(escapeHtml(raw));
      continue;
    }

    const trimmed = raw.trim();

    // Blank line
    if (trimmed === "") {
      closeList();
      closeTable();
      continue;
    }

    // Horizontal rule
    if (/^-{3,}$|^\*{3,}$/.test(trimmed)) {
      closeList();
      closeTable();
      out.push('<hr class="md-hr" />');
      continue;
    }

    // Table row
    if (trimmed.startsWith("|") && trimmed.endsWith("|")) {
      // Skip separator rows like |---|---|
      if (/^\|[\s\-:|]+\|$/.test(trimmed)) continue;

      const cells = trimmed
        .slice(1, -1)
        .split("|")
        .map((c) => c.trim());

      if (!inTable) {
        closeList();
        out.push(
          '<div class="md-table-wrap"><table class="md-table"><thead><tr>',
        );
        for (const cell of cells) {
          out.push(`<th>${inlineFormat(cell)}</th>`);
        }
        out.push("</tr></thead><tbody>");
        inTable = true;
      } else {
        out.push("<tr>");
        for (const cell of cells) {
          out.push(`<td>${inlineFormat(cell)}</td>`);
        }
        out.push("</tr>");
      }
      continue;
    } else if (inTable) {
      closeTable();
    }

    // Headings
    const headingMatch = trimmed.match(/^(#{1,6})\s+(.+)/);
    if (headingMatch) {
      closeList();
      const level = headingMatch[1].length;
      out.push(
        `<h${level} class="md-h${level}">${inlineFormat(headingMatch[2])}</h${level}>`,
      );
      continue;
    }

    // Unordered list
    if (/^[-*]\s+/.test(trimmed)) {
      if (inList !== "ul") {
        closeList();
        inList = "ul";
        out.push('<ul class="md-ul">');
      }
      out.push(`<li>${inlineFormat(trimmed.replace(/^[-*]\s+/, ""))}</li>`);
      continue;
    }

    // Ordered list
    const olMatch = trimmed.match(/^(\d+)\.\s+(.*)/);
    if (olMatch) {
      if (inList !== "ol") {
        closeList();
        inList = "ol";
        out.push('<ol class="md-ol">');
      }
      out.push(`<li>${inlineFormat(olMatch[2])}</li>`);
      continue;
    }

    // Paragraph
    closeList();
    out.push(`<p class="md-p">${inlineFormat(trimmed)}</p>`);
  }

  closeList();
  closeTable();
  if (inCodeBlock) out.push("</code></pre>");

  return out.join("\n");
}
