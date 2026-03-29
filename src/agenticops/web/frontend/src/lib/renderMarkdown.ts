/**
 * Lightweight markdown-to-HTML renderer for report content.
 * Handles headings, bold, italic, inline code, code blocks, tables,
 * lists, horizontal rules, and links.
 */

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
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
    let s = escapeHtml(text);
    // inline code
    s = s.replace(/`([^`]+)`/g, '<code class="md-code">$1</code>');
    // bold + italic
    s = s.replace(/\*\*\*(.+?)\*\*\*/g, "<strong><em>$1</em></strong>");
    // bold
    s = s.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
    // italic
    s = s.replace(/\*(.+?)\*/g, "<em>$1</em>");
    // links
    s = s.replace(
      /\[([^\]]+)\]\(([^)]+)\)/g,
      '<a href="$2" class="md-link" target="_blank" rel="noopener">$1</a>',
    );
    // Auto-link I#N → /app/issues/N
    s = s.replace(/\bI#(\d+)\b/g,
      '<a href="/app/issues/$1" class="md-link md-ref" title="Issue #$1">I#$1</a>');
    // Auto-link R#N → /app/resources/N
    s = s.replace(/\bR#(\d+)\b/g,
      '<a href="/app/resources/$1" class="md-link md-ref" title="Resource #$1">R#$1</a>');
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
