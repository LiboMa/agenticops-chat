/** Downloads (MVP-2.7.0 S6): an authenticated fetch → a Blob → a file, so a token never appears in a URL. */

/** The file name a Content-Disposition header gives (filename*= wins, decoded), or null. */
export function filenameFromDisposition(header: string | null | undefined): string | null {
  if (!header) return null;
  const star = /filename\*\s*=\s*(?:UTF-8|utf-8)''([^;]+)/.exec(header);
  if (star) {
    try { return decodeURIComponent(star[1].trim()); } catch { /* fall through to filename= */ }
  }
  const plain = /filename\s*=\s*"([^"]+)"|filename\s*=\s*([^;]+)/.exec(header);
  return plain ? (plain[1] ?? plain[2]).trim() : null;
}

/** Save a Blob as a file in the browser. */
export function saveBlob(blob: Blob, name: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
