import { extOf } from "@/lib/attachments";

export type BadgeTone = "pdf" | "sheet" | "doc" | "slide" | "image" | "text" | "archive" | "other";

const TONES: Record<string, BadgeTone> = {
  ".pdf": "pdf",
  ".xlsx": "sheet", ".xlsm": "sheet", ".xls": "sheet", ".csv": "sheet", ".tsv": "sheet",
  ".docx": "doc", ".doc": "doc",
  ".pptx": "slide", ".ppt": "slide",
  ".png": "image", ".jpg": "image", ".jpeg": "image", ".gif": "image", ".webp": "image", ".bmp": "image",
  ".tif": "image", ".tiff": "image", ".heic": "image", ".heif": "image",
  ".zip": "archive", ".gz": "archive", ".tgz": "archive", ".tar": "archive", ".7z": "archive", ".rar": "archive",
  ...Object.fromEntries([".txt", ".log", ".md", ".json", ".jsonl", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf",
    ".sh", ".py", ".js", ".ts", ".xml", ".html", ".htm", ".tf", ".hcl"].map((e) => [e, "text" as BadgeTone])),
};

/** The coloured badge a file shows in the composer: its extension (≤ 4 letters) and its family's colour. */
export function attachmentBadge(name: string): { label: string; tone: BadgeTone } {
  const ext = extOf(name);
  return { label: ext ? ext.slice(1).toUpperCase().slice(0, 4) : "FILE", tone: TONES[ext] ?? "other" };
}

export const BADGE_CLASS: Record<BadgeTone, string> = {
  pdf: "bg-red-500", sheet: "bg-green-600", doc: "bg-blue-600", slide: "bg-orange-500",
  image: "bg-sky-500", text: "bg-slate-500", archive: "bg-amber-600", other: "bg-gray-400",
};
