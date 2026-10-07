/** A complete-frame SSE parser (MVP-2.7.0 S5): frames end at a blank line; CRLF / CR are line ends; `data:` lines
 *  join with "\n"; comments are skipped; text is already decoded (the caller's TextDecoder keeps split UTF-8 whole). */
export interface SseFrame { event: string; data: string }

export class SseParser {
  private buf = "";
  private event = "";
  private data: string[] = [];

  push(chunk: string): SseFrame[] {
    this.buf += chunk;
    const out: SseFrame[] = [];
    for (;;) {
      const m = /\r\n|\r|\n/.exec(this.buf);
      if (!m) break;
      if (m[0] === "\r" && m.index === this.buf.length - 1) break;  // a lone CR at the end may be half of CRLF
      const line = this.buf.slice(0, m.index);
      this.buf = this.buf.slice(m.index + m[0].length);
      const frame = this.line(line);
      if (frame) out.push(frame);
    }
    return out;
  }

  flush(): SseFrame[] {
    const out = this.buf ? this.push("\n") : [];
    const last = this.line("");
    return last ? [...out, last] : out;
  }

  private line(line: string): SseFrame | null {
    if (line === "") {
      if (!this.data.length) { this.event = ""; return null; }
      const frame = { event: this.event || "message", data: this.data.join("\n") };
      this.event = ""; this.data = [];
      return frame;
    }
    if (line.startsWith(":")) return null;
    const i = line.indexOf(":");
    const field = i < 0 ? line : line.slice(0, i);
    let value = i < 0 ? "" : line.slice(i + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "event") this.event = value;
    else if (field === "data") this.data.push(value);
    return null;
  }
}
