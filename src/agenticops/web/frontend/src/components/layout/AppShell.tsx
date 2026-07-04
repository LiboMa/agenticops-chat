import { useState, useEffect, useCallback } from "react";
import { Outlet } from "react-router-dom";
import { IconSidebar } from "./IconSidebar";
import { MinimalTopBar } from "./MinimalTopBar";
import { CommandPalette } from "../CommandPalette";
import { usePersistedState } from "@/hooks/usePersistedState";

export function AppShell() {
  const [paletteOpen, setPaletteOpen] = useState(false);
  // Nav expanded state lives here (not in IconSidebar) so the content
  // padding follows in the same tab — storage events only fire cross-tab.
  const [navExpanded, setNavExpanded] = usePersistedState<boolean>("aiops-nav-expanded", false);

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
      <IconSidebar expanded={navExpanded} onToggle={() => setNavExpanded(!navExpanded)} />
      <div className={`transition-[padding] duration-200 ${navExpanded ? "pl-[200px]" : "pl-[52px]"}`}>
        <MinimalTopBar />
        <main className="p-6">
          <Outlet />
        </main>
      </div>
      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
    </div>
  );
}
