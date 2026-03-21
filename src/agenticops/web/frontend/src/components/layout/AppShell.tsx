import { useState, useEffect, useCallback } from "react";
import { Outlet } from "react-router-dom";
import { IconSidebar } from "./IconSidebar";
import { MinimalTopBar } from "./MinimalTopBar";
import { CommandPalette } from "../CommandPalette";

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
    <div className="min-h-screen bg-background text-foreground">
      <IconSidebar />
      <div className="pl-[52px]">
        <MinimalTopBar />
        <main className="p-6">
          <Outlet />
        </main>
      </div>
      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
    </div>
  );
}
