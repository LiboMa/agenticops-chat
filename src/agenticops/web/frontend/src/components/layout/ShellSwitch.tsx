import { useLocation } from "react-router-dom";
import { readChoice, shellFor } from "@/lib/shellChoice";
import { AppShell } from "./AppShell";
import { NewFrame } from "./NewFrame";

/** The one layout route of /app (MVP-2.9.0 round 3): the classic workspace, or NewUI's frame around the same pages —
 *  the person's own choice (lib/shellChoice), read as the route renders so the right shell paints first. NewUI's own
 *  addresses (/app/new/…) are always its frame. The classic branch is what it always was: nothing waits, and nothing
 *  of NewUI is in this chunk (`__tests__/shellChunks.test.ts`). */
export function ShellSwitch() {
  const { pathname } = useLocation();
  return shellFor(pathname, readChoice()) === "new" ? <NewFrame /> : <AppShell />;
}
