import { useState, useEffect, useCallback } from "react";
import { Outlet, useLocation } from "react-router-dom";
import { isRailRoute } from "@/lib/navGroups";
import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";
import { CommandPalette } from "../CommandPalette";
import { RestoreNotice, ShellEffects } from "./ShellEffects";
import { AccountScopeProvider, ScopeNotice } from "./AccountScope";

/** The blue/white workspace frame: a 200px white sidebar (166px ≤1100px, hidden ≤800px — the top bar then
 *  carries a menu), the top bar, and the page on the canvas. ⌘K / Ctrl+K opens search. */
export function AppShell() {
  const [paletteOpen, setPaletteOpen] = useState(false);
  const rail = isRailRoute(useLocation().pathname);   // 2026-11-07: Chat keeps the width for its chat list

  const handleKeyDown = useCallback((e: KeyboardEvent) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "k") {
      e.preventDefault();
      setPaletteOpen((prev) => !prev);
    }
  }, []);

  useEffect(() => {
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [handleKeyDown]);

  return (
    <AccountScopeProvider>
    <div className="min-h-screen bg-canvas text-foreground">
      <Sidebar rail={rail} />
      <div className={rail ? "min-[801px]:pl-[56px]" : "min-[801px]:pl-[166px] min-[1101px]:pl-[200px]"}>
        <TopBar onSearch={() => setPaletteOpen(true)} />
        <main className="p-6">
          <RestoreNotice />
          <ScopeNotice />
          <Outlet />
        </main>
      </div>
      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
      <ShellEffects />
    </div>
    </AccountScopeProvider>
  );
}
