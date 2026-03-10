import { Outlet } from "react-router-dom";
import { Sidebar } from "./Sidebar";

export function AppShell() {
  return (
    <div className="min-h-screen bg-[#212121] text-[#ececec]">
      <Sidebar />
      <div className="pl-[260px]">
        <main className="mx-auto max-w-5xl px-8 py-8">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
