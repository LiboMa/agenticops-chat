import { describe, it, expect } from "vitest";
import { renderMarkdown } from "@/lib/renderMarkdown";

describe("renderMarkdown", () => {
  describe("headings", () => {
    it("renders h1 with class md-h1", () => {
      expect(renderMarkdown("# Hello")).toContain('<h1 class="md-h1">Hello</h1>');
    });

    it("renders h2 with class md-h2", () => {
      expect(renderMarkdown("## Subtitle")).toContain('<h2 class="md-h2">Subtitle</h2>');
    });

    it("renders h3 with class md-h3", () => {
      expect(renderMarkdown("### Section")).toContain('<h3 class="md-h3">Section</h3>');
    });

    it("renders h4 with class md-h4", () => {
      expect(renderMarkdown("#### Subsection")).toContain('<h4 class="md-h4">Subsection</h4>');
    });

    it("renders h5 with class md-h5", () => {
      expect(renderMarkdown("##### Minor")).toContain('<h5 class="md-h5">Minor</h5>');
    });

    it("renders h6 with class md-h6", () => {
      expect(renderMarkdown("###### Smallest")).toContain('<h6 class="md-h6">Smallest</h6>');
    });

    it("applies inline formatting within headings", () => {
      const result = renderMarkdown("# **Bold** heading");
      expect(result).toContain("<strong>Bold</strong>");
      expect(result).toContain('<h1 class="md-h1">');
    });
  });

  describe("inline formatting", () => {
    it("renders **bold** as <strong>", () => {
      expect(renderMarkdown("**bold text**")).toContain("<strong>bold text</strong>");
    });

    it("renders *italic* as <em>", () => {
      expect(renderMarkdown("*italic text*")).toContain("<em>italic text</em>");
    });

    it("renders ***bold+italic*** as <strong><em>", () => {
      const result = renderMarkdown("***both***");
      expect(result).toContain("<strong><em>both</em></strong>");
    });

    it("renders `code` as <code> with md-code class", () => {
      expect(renderMarkdown("`inline code`")).toContain(
        '<code class="md-code">inline code</code>',
      );
    });

    it("handles multiple inline formats in one line", () => {
      const result = renderMarkdown("**bold** and *italic* and `code`");
      expect(result).toContain("<strong>bold</strong>");
      expect(result).toContain("<em>italic</em>");
      expect(result).toContain('<code class="md-code">code</code>');
    });
  });

  describe("links", () => {
    it("renders [text](url) as <a> with target=_blank and rel=noopener", () => {
      const result = renderMarkdown("[Click here](https://example.com)");
      expect(result).toContain('href="https://example.com"');
      expect(result).toContain('target="_blank"');
      expect(result).toContain('rel="noopener"');
      expect(result).toContain(">Click here</a>");
    });

    it("renders I#N as auto-link to /app/issues/N", () => {
      const result = renderMarkdown("See I#42 for details");
      expect(result).toContain('href="/app/issues/42"');
      expect(result).toContain("md-ref");
      expect(result).toContain(">I#42</a>");
    });

    it("renders R#N as auto-link to /app/resources/N", () => {
      const result = renderMarkdown("Check R#7 resource");
      expect(result).toContain('href="/app/resources/7"');
      expect(result).toContain("md-ref");
      expect(result).toContain(">R#7</a>");
    });

    it("auto-links have title attribute", () => {
      const result = renderMarkdown("I#100");
      expect(result).toContain('title="Issue #100"');
    });

    it("does not auto-link partial matches without word boundary", () => {
      // "AI#5" should not match because I#5 is not at a word boundary
      const result = renderMarkdown("AI#5");
      expect(result).not.toContain('href="/app/issues/5"');
    });
  });

  describe("code blocks", () => {
    it("renders fenced code blocks with <pre> and data-lang", () => {
      const md = "```javascript\nconst x = 1;\n```";
      const result = renderMarkdown(md);
      expect(result).toContain('<pre class="md-pre" data-lang="javascript"><code>');
      expect(result).toContain("const x = 1;");
      expect(result).toContain("</code></pre>");
    });

    it("renders code blocks without language", () => {
      const md = "```\nplain code\n```";
      const result = renderMarkdown(md);
      expect(result).toContain('<pre class="md-pre"><code>');
      expect(result).toContain("plain code");
    });

    it("HTML-escapes content within code blocks", () => {
      const md = "```\n<script>alert('xss')</script>\n```";
      const result = renderMarkdown(md);
      expect(result).toContain("&lt;script&gt;");
      expect(result).not.toContain("<script>");
    });

    it("normalizes language name to lowercase", () => {
      const md = "```TypeScript\nlet y = 2;\n```";
      const result = renderMarkdown(md);
      expect(result).toContain('data-lang="typescript"');
    });
  });

  describe("tables", () => {
    it("renders pipe-delimited rows as <table> with thead and tbody", () => {
      const md = "| Name | Age |\n|------|-----|\n| Alice | 30 |\n| Bob | 25 |";
      const result = renderMarkdown(md);
      expect(result).toContain('<table class="md-table">');
      expect(result).toContain("<thead>");
      expect(result).toContain("<th>Name</th>");
      expect(result).toContain("<th>Age</th>");
      expect(result).toContain("<tbody>");
      expect(result).toContain("<td>Alice</td>");
      expect(result).toContain("<td>30</td>");
      expect(result).toContain("<td>Bob</td>");
      expect(result).toContain("<td>25</td>");
    });

    it("skips separator rows", () => {
      const md = "| H1 | H2 |\n|---|---|\n| D1 | D2 |";
      const result = renderMarkdown(md);
      expect(result).not.toContain("---");
    });

    it("applies inline formatting inside table cells", () => {
      const md = "| Header |\n|--------|\n| **bold** |";
      const result = renderMarkdown(md);
      expect(result).toContain("<strong>bold</strong>");
    });
  });

  describe("unordered lists", () => {
    it("renders - items as <ul class='md-ul'> with <li>", () => {
      const md = "- Item 1\n- Item 2\n- Item 3";
      const result = renderMarkdown(md);
      expect(result).toContain('<ul class="md-ul">');
      expect(result).toContain("<li>Item 1</li>");
      expect(result).toContain("<li>Item 2</li>");
      expect(result).toContain("<li>Item 3</li>");
      expect(result).toContain("</ul>");
    });

    it("renders * items as <ul class='md-ul'> with <li>", () => {
      const md = "* Alpha\n* Beta";
      const result = renderMarkdown(md);
      expect(result).toContain('<ul class="md-ul">');
      expect(result).toContain("<li>Alpha</li>");
      expect(result).toContain("<li>Beta</li>");
    });

    it("applies inline formatting inside list items", () => {
      const md = "- **Bold item**\n- *Italic item*";
      const result = renderMarkdown(md);
      expect(result).toContain("<strong>Bold item</strong>");
      expect(result).toContain("<em>Italic item</em>");
    });
  });

  describe("ordered lists", () => {
    it("renders numbered items as <ol class='md-ol'> with <li>", () => {
      const md = "1. First\n2. Second\n3. Third";
      const result = renderMarkdown(md);
      expect(result).toContain('<ol class="md-ol">');
      expect(result).toContain("<li>First</li>");
      expect(result).toContain("<li>Second</li>");
      expect(result).toContain("<li>Third</li>");
      expect(result).toContain("</ol>");
    });

    it("applies inline formatting inside ordered list items", () => {
      const md = "1. `code item`";
      const result = renderMarkdown(md);
      expect(result).toContain('<code class="md-code">code item</code>');
    });
  });

  describe("horizontal rules", () => {
    it("renders --- as <hr class='md-hr'>", () => {
      const result = renderMarkdown("---");
      expect(result).toContain('<hr class="md-hr" />');
    });

    it("renders *** as <hr class='md-hr'>", () => {
      const result = renderMarkdown("***");
      expect(result).toContain('<hr class="md-hr" />');
    });

    it("renders long dashes as hr", () => {
      const result = renderMarkdown("-----");
      expect(result).toContain('<hr class="md-hr" />');
    });
  });

  describe("HTML escaping", () => {
    it("escapes < to &lt;", () => {
      const result = renderMarkdown("a < b");
      expect(result).toContain("&lt;");
      expect(result).not.toContain("a < b");
    });

    it("escapes > to &gt;", () => {
      const result = renderMarkdown("a > b");
      expect(result).toContain("&gt;");
    });

    it("escapes & to &amp;", () => {
      const result = renderMarkdown("a & b");
      expect(result).toContain("&amp;");
    });

    it('escapes " to &quot;', () => {
      const result = renderMarkdown('say "hello"');
      expect(result).toContain("&quot;");
    });

    it("escapes HTML tags in inline content", () => {
      const result = renderMarkdown("<div>injected</div>");
      expect(result).toContain("&lt;div&gt;");
      expect(result).not.toContain("<div>");
    });
  });

  describe("paragraphs", () => {
    it("wraps plain text in <p class='md-p'>", () => {
      const result = renderMarkdown("Hello world");
      expect(result).toContain('<p class="md-p">Hello world</p>');
    });

    it("separates multiple paragraphs by blank lines", () => {
      const md = "First paragraph\n\nSecond paragraph";
      const result = renderMarkdown(md);
      expect(result).toContain('<p class="md-p">First paragraph</p>');
      expect(result).toContain('<p class="md-p">Second paragraph</p>');
    });

    it("applies inline formatting in paragraphs", () => {
      const result = renderMarkdown("This is **important**");
      expect(result).toContain('<p class="md-p">This is <strong>important</strong></p>');
    });
  });

  describe("complex documents", () => {
    it("renders a document mixing multiple element types", () => {
      const md = [
        "# Title",
        "",
        "A paragraph with **bold** text.",
        "",
        "- List item 1",
        "- List item 2",
        "",
        "---",
        "",
        "```python",
        "print('hello')",
        "```",
      ].join("\n");
      const result = renderMarkdown(md);
      expect(result).toContain('<h1 class="md-h1">Title</h1>');
      expect(result).toContain("<strong>bold</strong>");
      expect(result).toContain('<ul class="md-ul">');
      expect(result).toContain('<hr class="md-hr" />');
      expect(result).toContain('data-lang="python"');
      // Single quotes are not escaped by our escapeHtml, so they remain as-is
      expect(result).toContain("print('hello')");
    });
  });

  describe("negative paths / malformed markdown", () => {
    it("handles unclosed code block gracefully by auto-closing at end of input", () => {
      const md = "```javascript\nconst x = 1;\nno closing fence";
      const result = renderMarkdown(md);
      // The renderer should still produce valid HTML with a closing </code></pre>
      expect(result).toContain('<pre class="md-pre" data-lang="javascript"><code>');
      expect(result).toContain("const x = 1;");
      expect(result).toContain("no closing fence");
      expect(result).toContain("</code></pre>");
      // Content inside the unclosed block should be escaped, not treated as markdown
      expect(result).not.toContain('<p class="md-p">no closing fence</p>');
    });

    it("treats unclosed bold markers as literal text", () => {
      const result = renderMarkdown("This is **not closed");
      // Unclosed ** should not produce a dangling <strong> tag
      expect(result).toContain('<p class="md-p">');
      // The literal ** remain in the output since no closing marker was found
      expect(result).toContain("**not closed");
      // Should not have an unmatched opening <strong> without a closing tag
      const strongOpen = (result.match(/<strong>/g) || []).length;
      const strongClose = (result.match(/<\/strong>/g) || []).length;
      expect(strongOpen).toBe(strongClose);
    });
  });
});
