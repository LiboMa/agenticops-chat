import { useEffect, useRef } from "react";
import { useLocation } from "react-router-dom";
import { leavesNew, readChoice, shellFor, type Shell } from "@/lib/shellChoice";
import { AppShell } from "./AppShell";
import { NewFrame } from "./NewFrame";

/** The one layout route of /app (MVP-2.9.0 round 3): the classic workspace, or NewUI's frame around the same pages —
 *  the person's own choice (lib/shellChoice), read as the route renders so the right shell paints first. NewUI's own
 *  addresses (/app/new/…) are always its frame. The classic branch is what it always was: nothing waits, and nothing
 *  of NewUI is in this chunk (`__tests__/shellChunks.test.ts`). */
export function ShellSwitch() {
  const { pathname, state } = useLocation();
  // the shell that drew the address before this one, in this tab: a person stays in the frame they are in
  // (lib/shellChoice.shellFor) — recorded once the page is on the screen, never from a render that was dropped
  const was = useRef<Shell | null>(null);
  const shell = shellFor(pathname, readChoice(), was.current, leavesNew(state));
  useEffect(() => { was.current = shell; });
  return shell === "new" ? <NewFrame /> : <AppShell />;
}
