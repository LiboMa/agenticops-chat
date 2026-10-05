import { useState, useEffect, useCallback } from "react";
import { Outlet } from "react-router-dom";
import { Sidebar } from "./Sidebar";
import { MinimalTopBar } from "./MinimalTopBar";
import { CommandPalette } from "../CommandPalette";
import { RestoreNotice, ShellEffects } from "./ShellEffects";

/** The blue/white workspace frame: a 200px white sidebar (166px ≤1100px, hidden ≤800px — the top bar then
 *  carries a menu), the top bar, and the page on the canvas. ⌘K / Ctrl+K opens search. */
export function AppShell() {
  const [paletteOpen, setPaletteOpen] = useState(false);

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
    <div className="min-h-screen bg-canvas text-foreground">
      <Sidebar />
      <div className="min-[801px]:pl-[166px] min-[1101px]:pl-[200px]">
        <MinimalTopBar />
        <main className="p-6">
          <RestoreNotice />
          <Outlet />
        </main>
      </div>
      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
      <ShellEffects />
    </div>
  );
}
